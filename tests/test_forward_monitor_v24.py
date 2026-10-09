from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from gb_power_market.forward_monitor_v24 import (
    AUGUST_MONITOR_START_UTC,
    LOCKED_FINAL_START_UTC,
    POST_LOCK_START_UTC,
    daily_metrics,
    score_frozen_forward_rows,
    segment_metrics,
)
from gb_power_market.price_feature_families import HISTORY_FEATURES, LEVEL_FEATURES
from gb_power_market.prospective_v21 import LOCKED_EVIDENCE_ID


def _state(family: str = "PRICE_HISTORY_ONLY") -> dict:
    features = list(HISTORY_FEATURES)
    horizon = 30
    if family == "PRICE_PLUS_NESO_LEVELS":
        features += list(LEVEL_FEATURES)
        horizon = 120
    # Intercept 50, zero slopes: deterministic frozen prediction = 50.
    return {
        "schema": "gb-power-market-frozen-ridge-v1",
        "source_evidence_id_sha256": LOCKED_EVIDENCE_ID,
        "horizon_minutes": horizon,
        "selected_family": family,
        "features": features,
        "alpha": 1.0,
        "mean": [0.0] * len(features),
        "scale": [1.0] * len(features),
        "coef": [50.0] + [0.0] * len(features),
        "conformal_absolute_residual_quantile_gbp_mwh": 5.0,
    }


def _frame(start: pd.Timestamp, n: int, *, family: str = "PRICE_HISTORY_ONLY") -> pd.DataFrame:
    t = pd.date_range(start, periods=n, freq="30min")
    horizon = 30 if family == "PRICE_HISTORY_ONLY" else 120
    realised = 50.0 + np.sin(np.arange(n) / 7.0)
    out = pd.DataFrame({
        "target_start_utc": t,
        "decision_time_utc": t - pd.Timedelta(minutes=horizon),
        "reference_market_price_gbp_mwh": realised,
        "price_lag_1d_same_target": np.full(n, 60.0),
        "price_lag_last_completed": np.full(n, 49.0),
    })
    for i, c in enumerate(HISTORY_FEATURES):
        out[c] = 0.1 * (i + 1)
    if family == "PRICE_PLUS_NESO_LEVELS":
        for i, c in enumerate(LEVEL_FEATURES):
            out[c] = 100.0 + i
        out["neso_publish_time_utc"] = out["decision_time_utc"] - pd.Timedelta(minutes=15)
    return out


def test_forward_monitor_can_start_inside_locked_historical_final():
    frame = _frame(LOCKED_FINAL_START_UTC, 96)
    end = LOCKED_FINAL_START_UTC + pd.Timedelta(hours=48)
    rows, audit = score_frozen_forward_rows(
        frame,
        frozen_state=_state(),
        start_utc=LOCKED_FINAL_START_UTC,
        end_exclusive_utc=end,
    )
    assert len(rows) == 96
    assert audit["coverage"] == 1.0
    assert set(rows["evidence_segment"]) == {"LOCKED_HISTORICAL_OOS"}
    assert rows["rolling_24h_model_mae_gbp_mwh"].notna().all()
    assert rows["cumulative_error_advantage_gbp_mwh"].iloc[-1] > 0


def test_forward_monitor_marks_post_lock_rows_without_refitting():
    start = POST_LOCK_START_UTC
    frame = _frame(start, 48)
    rows, audit = score_frozen_forward_rows(
        frame,
        frozen_state=_state(),
        start_utc=start,
        end_exclusive_utc=start + pd.Timedelta(days=1),
    )
    assert audit["future_neso_publications"] == 0
    assert set(rows["evidence_segment"]) == {"POST_LOCK_FORWARD_MONITORING"}
    assert rows["frozen_prediction_gbp_mwh"].eq(50.0).all()


def test_neso_future_publication_fails_closed():
    start = POST_LOCK_START_UTC
    frame = _frame(start, 20, family="PRICE_PLUS_NESO_LEVELS")
    frame.loc[3, "neso_publish_time_utc"] = frame.loc[3, "decision_time_utc"] + pd.Timedelta(minutes=1)
    with pytest.raises(ValueError, match="future NESO publications"):
        score_frozen_forward_rows(
            frame,
            frozen_state=_state("PRICE_PLUS_NESO_LEVELS"),
            start_utc=start,
            end_exclusive_utc=start + pd.Timedelta(hours=10),
        )


def test_duplicate_target_fails_closed():
    start = AUGUST_MONITOR_START_UTC
    frame = _frame(start, 20)
    frame = pd.concat([frame, frame.iloc[[4]]], ignore_index=True)
    with pytest.raises(ValueError, match="duplicate complete target"):
        score_frozen_forward_rows(
            frame,
            frozen_state=_state(),
            start_utc=start,
            end_exclusive_utc=start + pd.Timedelta(hours=10),
        )


def test_segment_metrics_separate_historical_recent_and_post_lock():
    start = AUGUST_MONITOR_START_UTC
    end = POST_LOCK_START_UTC + pd.Timedelta(days=2)
    n = int((end - start) / pd.Timedelta(minutes=30))
    rows, _ = score_frozen_forward_rows(
        _frame(start, n),
        frozen_state=_state(),
        start_utc=start,
        end_exclusive_utc=end,
    )
    segments = segment_metrics(rows, monitor_end_exclusive_utc=end)
    assert segments["august_1_to_latest"]["rows"] == n
    assert segments["post_lock_to_latest"]["rows"] == 96
    assert segments["post_lock_to_latest"]["evidence_role"] == "POST_LOCK_FORWARD_MONITORING"
    assert segments["latest_24h"]["rows"] == 48


def test_daily_metrics_are_one_row_per_utc_day():
    start = pd.Timestamp("2026-08-01T00:00:00Z")
    rows, _ = score_frozen_forward_rows(
        _frame(start, 96),
        frozen_state=_state(),
        start_utc=start,
        end_exclusive_utc=start + pd.Timedelta(days=2),
    )
    daily = daily_metrics(rows)
    assert daily["utc_day"].tolist() == ["2026-08-01", "2026-08-02"]
    assert daily["rows"].tolist() == [48, 48]
    assert (daily["improvement_pct"] > 0).all()
