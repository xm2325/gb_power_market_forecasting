import pandas as pd
import pytest

from gb_power_market.v26_gate_diagnostics import summarise_v26_gate_diagnostics


def _rows() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "realised_price_gbp_mwh": [100.0, 100.0, 100.0, 100.0],
            "frozen_prediction_gbp_mwh": [98.0, 102.0, 99.0, 101.0],
            "v25_prediction_gbp_mwh": [95.0, 106.0, 103.0, 99.5],
            "v26_prediction_gbp_mwh": [99.0, 102.0, 99.0, 101.0],
            "v26_correction_gbp_mwh": [1.0, 0.0, 0.0, 0.0],
            "v26_gate_reason": [
                "CONSENSUS_CLIPPED_CORRECTION",
                "REGIME_DISAGREEMENT_FALLBACK_FROZEN",
                "REGIME_DISAGREEMENT_FALLBACK_FROZEN",
                "REGIME_DISAGREEMENT_FALLBACK_FROZEN",
            ],
        }
    )


def test_gate_diagnostics_separate_applied_and_fallback_behaviour() -> None:
    result = summarise_v26_gate_diagnostics(_rows())

    assert result["status"] == "DESCRIPTIVE_FORWARD_GATE_DIAGNOSTIC"
    assert result["monitoring_only"] is True
    assert result["rows"] == 4
    assert result["correction_applied_rows"] == 1
    assert result["fallback_rows"] == 3
    assert result["correction_applied_rate"] == pytest.approx(0.25)
    assert result["fallback_rate"] == pytest.approx(0.75)
    assert result["longest_regime_disagreement_streak_rows"] == 3
    assert result["current_regime_disagreement_streak_rows"] == 3
    assert result["mean_abs_correction_when_applied_gbp_mwh"] == pytest.approx(1.0)

    assert result["applied_rows_candidate_better_than_frozen"] == 1
    assert result["applied_rows_candidate_worse_than_frozen"] == 0
    assert result["fallback_rows_v25_worse_than_frozen"] == 2
    assert result["fallback_rows_v25_better_than_frozen"] == 1
    assert result["fallback_total_abs_error_avoided_vs_v25_gbp_mwh"] == pytest.approx(5.5)
    assert result["fallback_mean_abs_error_avoided_vs_v25_gbp_mwh"] == pytest.approx(5.5 / 3.0)
    assert result["prediction_reconstruction_max_abs_diff_gbp_mwh"] == pytest.approx(0.0)


def test_gate_diagnostics_reject_fallback_that_does_not_reproduce_frozen() -> None:
    rows = _rows()
    rows.loc[1, "v26_prediction_gbp_mwh"] = 103.0
    rows.loc[1, "v26_correction_gbp_mwh"] = 1.0

    with pytest.raises(ValueError, match="fallback row does not reproduce frozen prediction"):
        summarise_v26_gate_diagnostics(rows)


def test_gate_diagnostics_reject_prediction_reconstruction_mismatch() -> None:
    rows = _rows()
    rows.loc[0, "v26_prediction_gbp_mwh"] = 99.5

    with pytest.raises(ValueError, match="not frozen prediction plus recorded correction"):
        summarise_v26_gate_diagnostics(rows)


def test_gate_diagnostics_empty_rows() -> None:
    result = summarise_v26_gate_diagnostics(_rows().iloc[:0])
    assert result == {"rows": 0, "status": "NO_ROWS", "monitoring_only": True}
