from __future__ import annotations

import numpy as np
import pandas as pd

from gb_power_market.adaptive_2h_v25 import (
    Adaptive2hGateConfig,
    V25_FORWARD_START_UTC,
    adaptive_metrics,
    apply_adaptive_2h_gate,
)


def _rows(n: int = 240) -> pd.DataFrame:
    target = pd.date_range("2026-08-01T00:00:00Z", periods=n, freq="30min")
    realised = np.full(n, 100.0)
    frozen = np.full(n, 105.0)
    reference = np.full(n, 110.0)
    return pd.DataFrame(
        {
            "target_start_utc": target,
            "decision_time_utc": target - pd.Timedelta(hours=2),
            "realised_price_gbp_mwh": realised,
            "frozen_prediction_gbp_mwh": frozen,
            "previous_settlement_day_reference_gbp_mwh": reference,
            "model_abs_error_gbp_mwh": np.abs(realised - frozen),
            "reference_abs_error_gbp_mwh": np.abs(realised - reference),
        }
    )


def test_gate_uses_only_outcomes_available_by_decision_time() -> None:
    rows = _rows()
    gated = apply_adaptive_2h_gate(rows)
    available = pd.to_datetime(gated["gate_latest_outcome_available_utc"], utc=True)
    decision = pd.to_datetime(gated["decision_time_utc"], utc=True)
    observed = available.notna()
    assert (available[observed] <= decision[observed]).all()


def test_current_outcome_cannot_change_current_decision() -> None:
    rows = _rows()
    base = apply_adaptive_2h_gate(rows)
    j = 200
    changed = rows.copy()
    changed.loc[j, "realised_price_gbp_mwh"] = 5000.0
    changed.loc[j, "model_abs_error_gbp_mwh"] = abs(
        changed.loc[j, "realised_price_gbp_mwh"] - changed.loc[j, "frozen_prediction_gbp_mwh"]
    )
    changed.loc[j, "reference_abs_error_gbp_mwh"] = abs(
        changed.loc[j, "realised_price_gbp_mwh"]
        - changed.loc[j, "previous_settlement_day_reference_gbp_mwh"]
    )
    mutated = apply_adaptive_2h_gate(changed)
    assert mutated.loc[j, "adaptive_source"] == base.loc[j, "adaptive_source"]
    assert mutated.loc[j, "gate_model_minus_reference_mae_gbp_mwh"] == base.loc[
        j, "gate_model_minus_reference_mae_gbp_mwh"
    ]


def test_recent_bad_model_history_switches_to_reference() -> None:
    rows = _rows()
    # Make the latest completed history strongly favour the reference.
    rows.loc[40:190, "model_abs_error_gbp_mwh"] = 20.0
    rows.loc[40:190, "reference_abs_error_gbp_mwh"] = 5.0
    gated = apply_adaptive_2h_gate(rows)
    assert gated.loc[220, "gate_history_rows"] == 144
    assert gated.loc[220, "gate_model_minus_reference_mae_gbp_mwh"] > 0
    assert gated.loc[220, "adaptive_source"] == "REFERENCE"


def test_recent_good_model_history_keeps_frozen_model() -> None:
    gated = apply_adaptive_2h_gate(_rows())
    assert gated.loc[220, "gate_history_rows"] == 144
    assert gated.loc[220, "gate_model_minus_reference_mae_gbp_mwh"] < 0
    assert gated.loc[220, "adaptive_source"] == "FROZEN_MODEL"


def test_forward_segment_boundary_is_fixed() -> None:
    rows = _rows(1100)
    gated = apply_adaptive_2h_gate(rows)
    before = gated[gated["target_start_utc"] < V25_FORWARD_START_UTC]
    after = gated[gated["target_start_utc"] >= V25_FORWARD_START_UTC]
    assert not before.empty
    assert not after.empty
    assert set(before["candidate_evidence_segment"]) == {
        "RETROSPECTIVE_DEVELOPMENT_DIAGNOSTIC"
    }
    assert set(after["candidate_evidence_segment"]) == {"V0_25_FORWARD_SEGMENT"}


def test_adaptive_metrics_reports_reference_improvement() -> None:
    gated = apply_adaptive_2h_gate(_rows())
    metrics = adaptive_metrics(gated.iloc[100:])
    assert metrics["rows"] == 140
    assert metrics["adaptive_mae_gbp_mwh"] < metrics["reference_mae_gbp_mwh"]
    assert metrics["adaptive_improvement_vs_reference_pct"] > 0


def test_invalid_horizon_is_rejected() -> None:
    try:
        apply_adaptive_2h_gate(_rows(), config=Adaptive2hGateConfig(horizon_minutes=30))
    except ValueError as exc:
        assert "2h horizon" in str(exc)
    else:
        raise AssertionError("expected 30m adaptive gate config to be rejected")
