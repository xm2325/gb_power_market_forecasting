import numpy as np
import pandas as pd

from gb_power_market.adaptive_direction_v27_candidate import (
    V27_VALIDATION_END_UTC,
    V27_VALIDATION_START_UTC,
    apply_causal_direction_veto_candidate,
    candidate_spec,
    summarise_validation_block,
)


def _rows(*, slope: float, n: int = 36) -> pd.DataFrame:
    target = pd.date_range("2026-01-01T00:00:00Z", periods=n, freq="30min")
    frozen = 100.0 + slope * np.arange(n)
    realised = frozen - 10.0
    return pd.DataFrame(
        {
            "target_start_utc": target,
            "decision_time_utc": target - pd.Timedelta(hours=2),
            "realised_price_gbp_mwh": realised,
            "frozen_prediction_gbp_mwh": frozen,
            "previous_settlement_day_reference_gbp_mwh": frozen + 20.0,
        }
    )


def test_direction_veto_blocks_stale_negative_correction_during_rising_frozen_path() -> None:
    out = apply_causal_direction_veto_candidate(_rows(slope=1.0))
    row = out.iloc[30]

    assert row["v26_correction_gbp_mwh"] < 0
    assert row["v27_frozen_direction_delta_gbp_mwh"] > 0
    assert row["v27_gate_reason"] == "FROZEN_DIRECTION_VETO_FALLBACK_FROZEN"
    assert row["v27_correction_gbp_mwh"] == 0.0
    assert row["v27_prediction_gbp_mwh"] == row["frozen_prediction_gbp_mwh"]


def test_direction_veto_allows_consensus_when_frozen_path_agrees() -> None:
    out = apply_causal_direction_veto_candidate(_rows(slope=-1.0))
    row = out.iloc[30]

    assert row["v26_correction_gbp_mwh"] < 0
    assert row["v27_frozen_direction_delta_gbp_mwh"] < 0
    assert row["v27_gate_reason"] == "CONSENSUS_DIRECTION_ALIGNED_CORRECTION"
    assert row["v27_correction_gbp_mwh"] == row["v26_correction_gbp_mwh"]


def test_direction_candidate_does_not_use_current_or_future_realised_prices() -> None:
    base = _rows(slope=1.0)
    altered = base.copy()
    altered.loc[30:, "realised_price_gbp_mwh"] += 1000.0

    a = apply_causal_direction_veto_candidate(base)
    b = apply_causal_direction_veto_candidate(altered)

    assert a.iloc[30]["v27_prediction_gbp_mwh"] == b.iloc[30]["v27_prediction_gbp_mwh"]
    assert a.iloc[30]["v27_gate_reason"] == b.iloc[30]["v27_gate_reason"]


def test_validation_summary_requires_exact_sealed_48_row_block() -> None:
    target = pd.date_range(
        start=V27_VALIDATION_START_UTC,
        end=V27_VALIDATION_END_UTC,
        freq="30min",
        inclusive="left",
    )
    rows = pd.DataFrame(
        {
            "target_start_utc": target,
            "realised_price_gbp_mwh": 100.0,
            "v27_prediction_gbp_mwh": 105.0,
            "frozen_prediction_gbp_mwh": 110.0,
            "previous_settlement_day_reference_gbp_mwh": 120.0,
            "v27_gate_reason": "CONSENSUS_DIRECTION_ALIGNED_CORRECTION",
        }
    )

    complete = summarise_validation_block(rows)
    incomplete = summarise_validation_block(rows.iloc[:-1])

    assert complete["rows"] == 48
    assert complete["gate_evaluated"] is True
    assert complete["all_validation_gates_passed"] is True
    assert complete["forward_launch_allowed"] is True
    assert complete["automatic_forward_launch"] is False
    assert incomplete["status"] == "INCOMPLETE_OR_NONCONTIGUOUS_VALIDATION_BLOCK"
    assert incomplete["gate_evaluated"] is False
    assert incomplete["forward_launch_allowed"] is False


def test_candidate_spec_freezes_exact_validation_window_and_no_search() -> None:
    spec = candidate_spec()
    assert spec["status"] == "DEVELOPMENT_CANDIDATE_FROZEN_NOT_FORWARD_LAUNCHED"
    assert spec["validation_start_utc"] == "2026-08-23T22:00:00+00:00"
    assert spec["validation_end_exclusive_utc"] == "2026-08-24T22:00:00+00:00"
    assert spec["new_structure"]["parameter_search"] is False
    assert spec["new_structure"]["magnitude_threshold_gbp_mwh"] == 0.0
