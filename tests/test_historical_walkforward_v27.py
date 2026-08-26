from __future__ import annotations

import numpy as np
import pandas as pd

from gb_power_market.historical_walkforward_v27 import (
    EVIDENCE_CLASS,
    WalkForwardConfig,
    apply_candidate_suite,
    build_deployed_base_rows,
    build_fold_schedule,
    summarise_score_rows,
)


def _base_rows(start: str = "2026-04-28T00:00:00Z", periods: int = 160) -> pd.DataFrame:
    target = pd.date_range(start, periods=periods, freq="30min", tz="UTC")
    frozen = 90.0 + pd.Series(range(periods), dtype=float).to_numpy() * 0.05
    realised = frozen + 4.0
    return pd.DataFrame(
        {
            "target_start_utc": target,
            "decision_time_utc": target - pd.Timedelta(minutes=120),
            "realised_price_gbp_mwh": realised,
            "frozen_prediction_gbp_mwh": frozen,
            "previous_settlement_day_reference_gbp_mwh": frozen - 10.0,
        }
    )


def test_first_fold_scores_may_1_without_training_window_leakage() -> None:
    folds = build_fold_schedule()
    first = folds[0]
    assert first["train_start_utc"] == "2026-01-08T00:00:00+00:00"
    assert first["selection_start_utc"] == "2026-03-31T00:00:00+00:00"
    assert first["calibration_start_utc"] == "2026-04-14T00:00:00+00:00"
    assert first["adaptation_warmup_start_utc"] == "2026-04-28T00:00:00+00:00"
    assert first["score_start_utc"] == "2026-05-01T00:00:00+00:00"
    assert first["score_end_exclusive_utc"] == "2026-05-08T00:00:00+00:00"
    assert first["evidence_class"] == EVIDENCE_CLASS


def test_folds_are_nonoverlapping_and_cover_requested_score_window() -> None:
    cfg = WalkForwardConfig(score_end_exclusive_utc="2026-05-20T00:00:00Z")
    folds = build_fold_schedule(cfg)
    assert len(folds) == 3
    assert folds[0]["score_end_exclusive_utc"] == folds[1]["score_start_utc"]
    assert folds[1]["score_end_exclusive_utc"] == folds[2]["score_start_utc"]
    assert folds[-1]["score_end_exclusive_utc"] == "2026-05-20T00:00:00+00:00"


def test_warmup_must_cover_causal_48h_residual_window() -> None:
    try:
        build_fold_schedule(WalkForwardConfig(adaptation_warmup_hours=48))
    except ValueError as exc:
        assert "full 48h residual window" in str(exc)
    else:
        raise AssertionError("48h wall-clock warm-up should be rejected because horizon/delay also matter")


def test_fallback_score_does_not_require_unused_revision_features() -> None:
    target = pd.date_range("2026-04-28T00:00:00Z", "2026-05-08T00:00:00Z", freq="30min", inclusive="left")
    frame = pd.DataFrame(
        {
            "target_start_utc": target,
            "decision_time_utc": target - pd.Timedelta(minutes=120),
            "reference_market_price_gbp_mwh": np.linspace(80.0, 100.0, len(target)),
            "price_lag_1d_same_target": np.linspace(78.0, 98.0, len(target)),
            "price_lag_last_completed": np.linspace(79.0, 99.0, len(target)),
            # Deliberately absent revision/NESO columns: fallback does not use them.
        }
    )
    fold = build_fold_schedule()[0]
    selection = {
        "deployed_source": "PREVIOUS_SETTLEMENT_DAY_FALLBACK",
        "selected_family": "PRICE_PLUS_NESO_LEVELS_AND_REVISIONS",
        "by_family": {},
    }
    base = build_deployed_base_rows(frame, fold=fold, selection=selection)
    assert len(base) == 480
    scored = base[pd.to_datetime(base["target_start_utc"], utc=True) >= pd.Timestamp("2026-05-01T00:00:00Z")]
    assert len(scored) == 336
    assert np.allclose(scored["frozen_prediction_gbp_mwh"], scored["previous_settlement_day_reference_gbp_mwh"])


def test_candidate_suite_uses_only_causally_available_residual_history() -> None:
    rows = apply_candidate_suite(_base_rows())
    scored = rows[pd.to_datetime(rows["target_start_utc"], utc=True) >= pd.Timestamp("2026-05-01T00:00:00Z")]
    assert len(scored) > 0
    assert scored["v26_long_history_rows"].min() >= 24
    latest = pd.to_datetime(scored["v26_history_latest_target_utc"], utc=True)
    decision = pd.to_datetime(scored["decision_time_utc"], utc=True)
    assert (latest < decision).all()
    assert scored["v27_prediction_gbp_mwh"].notna().all()


def test_summary_never_labels_historical_rows_as_live_forward() -> None:
    rows = apply_candidate_suite(_base_rows())
    scored = rows[pd.to_datetime(rows["target_start_utc"], utc=True) >= pd.Timestamp("2026-05-01T00:00:00Z")]
    summary = summarise_score_rows(scored)
    assert summary["evidence_class"] == EVIDENCE_CLASS
    assert "v0.27" in summary["models"]
    assert "causal_base" in summary["models"]
    assert summary["models"]["v0.27"]["mae_gbp_mwh"] >= 0.0
