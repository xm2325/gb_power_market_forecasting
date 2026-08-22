from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from gb_power_market.adaptive_ewma_v26 import (
    EWMACorrectionRule,
    V26_DEVELOPMENT_END_EXCLUSIVE_UTC,
    V26_FORWARD_START_UTC,
    apply_causal_ewma_correction,
    select_v26_candidate,
)


def _rows(
    n: int = 500,
    *,
    start: str = "2026-08-10T00:00:00Z",
    residual: float = 10.0,
) -> pd.DataFrame:
    target = pd.date_range(start, periods=n, freq="30min")
    frozen = 100.0 + 8.0 * np.sin(np.arange(n) / 20.0)
    realised = frozen + residual
    reference = realised + 20.0
    return pd.DataFrame(
        {
            "target_start_utc": target,
            "decision_time_utc": target - pd.Timedelta(hours=2),
            "realised_price_gbp_mwh": realised,
            "frozen_prediction_gbp_mwh": frozen,
            "previous_settlement_day_reference_gbp_mwh": reference,
        }
    )


def test_current_target_cannot_change_its_own_ewma_correction() -> None:
    rows = _rows()
    rule = EWMACorrectionRule(half_life_hours=6.0, shrinkage=1.0)
    base = apply_causal_ewma_correction(rows, rule=rule)
    j = 300
    changed = rows.copy()
    changed.loc[j, "realised_price_gbp_mwh"] += 5000.0
    mutated = apply_causal_ewma_correction(changed, rule=rule)
    assert mutated.loc[j, "ewma_correction_gbp_mwh"] == pytest.approx(
        base.loc[j, "ewma_correction_gbp_mwh"], abs=1e-12
    )
    assert mutated.loc[j, "ewma_history_latest_target_utc"] == base.loc[
        j, "ewma_history_latest_target_utc"
    ]


def test_latest_history_is_available_by_decision_time() -> None:
    scored = apply_causal_ewma_correction(
        _rows(), rule=EWMACorrectionRule(half_life_hours=6.0, shrinkage=1.0)
    )
    latest = pd.to_datetime(scored["ewma_history_latest_target_utc"], utc=True, errors="coerce")
    decision = pd.to_datetime(scored["decision_time_utc"], utc=True)
    observed = latest.notna()
    # Conservative outcome availability is target + 30 minutes.
    assert ((latest[observed] + pd.Timedelta(minutes=30)) <= decision[observed]).all()


def test_short_half_life_responds_faster_to_recent_level_change() -> None:
    rows = _rows(residual=0.0)
    # The last 40 realised outcomes shift up by 20 £/MWh.
    rows.loc[len(rows) - 40 :, "realised_price_gbp_mwh"] += 20.0
    short = apply_causal_ewma_correction(
        rows, rule=EWMACorrectionRule(half_life_hours=3.0, shrinkage=1.0)
    )
    long = apply_causal_ewma_correction(
        rows, rule=EWMACorrectionRule(half_life_hours=24.0, shrinkage=1.0)
    )
    assert short.iloc[-1]["ewma_correction_gbp_mwh"] > long.iloc[-1]["ewma_correction_gbp_mwh"]


def test_forward_boundary_is_strictly_after_locked_development_end() -> None:
    assert V26_FORWARD_START_UTC > V26_DEVELOPMENT_END_EXCLUSIVE_UTC


def test_selection_uses_chronological_validation_and_can_pass_stable_bias() -> None:
    rows = _rows(n=650, start="2026-08-09T00:00:00Z", residual=10.0)
    result = select_v26_candidate(rows)
    assert result["validation_rows"] == 96
    assert pd.Timestamp(result["selection_end_exclusive_utc"]) < V26_DEVELOPMENT_END_EXCLUSIVE_UTC
    assert result["selected"] is not None
    assert result["forward_test_allowed"] is True
    assert result["validation_guards"]["passed"] is True


def test_development_cannot_extend_past_locked_artifact_boundary() -> None:
    rows = _rows(n=650, start="2026-08-09T00:00:00Z", residual=10.0)
    with pytest.raises(ValueError, match="cannot extend"):
        select_v26_candidate(
            rows,
            development_end_exclusive_utc=V26_DEVELOPMENT_END_EXCLUSIVE_UTC
            + pd.Timedelta(minutes=30),
        )


def test_invalid_shrinkage_is_rejected() -> None:
    with pytest.raises(ValueError, match="shrinkage"):
        apply_causal_ewma_correction(
            _rows(), rule=EWMACorrectionRule(half_life_hours=6.0, shrinkage=1.1)
        )
