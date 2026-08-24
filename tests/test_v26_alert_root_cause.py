import pandas as pd
import pytest

from gb_power_market.v26_alert_root_cause import summarise_v26_alert_root_cause


def _ledger() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "target_start_utc": [
                "2026-01-01T00:00:00Z",
                "2026-01-01T00:30:00Z",
                "2026-01-01T01:00:00Z",
                "2026-01-01T01:30:00Z",
                "2026-01-01T02:00:00Z",
            ],
            "realised_price_gbp_mwh": [100.0, 100.0, 100.0, 100.0, 100.0],
            "frozen_prediction_gbp_mwh": [105.0, 98.0, 101.0, 110.0, 95.0],
            "v26_short_residual_mean_gbp_mwh": [-2.0, -1.0, 2.0, -3.0, -2.0],
            "v26_long_residual_mean_gbp_mwh": [-4.0, -3.0, -2.0, -5.0, -4.0],
            "v26_gate_reason": [
                "CONSENSUS_CLIPPED_CORRECTION",
                "CONSENSUS_CLIPPED_CORRECTION",
                "REGIME_DISAGREEMENT_FALLBACK_FROZEN",
                "CONSENSUS_CLIPPED_CORRECTION",
                "CONSENSUS_CLIPPED_CORRECTION",
            ],
            "v26_correction_gbp_mwh": [-2.0, -1.0, 0.0, -3.0, -2.0],
            "v26_prediction_gbp_mwh": [103.0, 97.0, 101.0, 107.0, 93.0],
        }
    )


def test_alert_root_cause_separates_applied_runs_and_error_contributions() -> None:
    result = summarise_v26_alert_root_cause(_ledger())

    assert result["status"] == "DESCRIPTIVE_ALERT_ROOT_CAUSE"
    assert result["monitoring_only"] is True
    assert result["rows"] == 5
    assert result["correction_applied_rows"] == 4
    assert result["fallback_rows"] == 1
    assert result["applied_rows_candidate_better_than_frozen"] == 2
    assert result["applied_rows_candidate_worse_than_frozen"] == 2
    assert result["candidate_excess_abs_error_vs_frozen_gbp_mwh"] == pytest.approx(2.0)
    assert result["harmful_applied_excess_abs_error_gbp_mwh"] == pytest.approx(3.0)
    assert result["helpful_applied_abs_error_saved_gbp_mwh"] == pytest.approx(1.0)
    assert len(result["applied_runs"]) == 2
    assert result["longest_applied_run"]["rows"] == 2
    assert result["prediction_reconstruction_max_abs_diff_gbp_mwh"] == pytest.approx(0.0)


def test_alert_root_cause_rejects_fallback_that_changes_frozen_prediction() -> None:
    ledger = _ledger()
    ledger.loc[2, "v26_correction_gbp_mwh"] = 1.0
    ledger.loc[2, "v26_prediction_gbp_mwh"] = 102.0

    with pytest.raises(ValueError, match="fallback row does not reproduce frozen prediction"):
        summarise_v26_alert_root_cause(ledger)


def test_alert_root_cause_empty_rows() -> None:
    result = summarise_v26_alert_root_cause(_ledger().iloc[:0])
    assert result == {"rows": 0, "status": "NO_ROWS", "monitoring_only": True}
