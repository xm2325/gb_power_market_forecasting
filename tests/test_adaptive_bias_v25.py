import numpy as np
import pandas as pd

from gb_power_market.adaptive_bias_v25 import (
    BiasCorrectionRule,
    V25_FORWARD_START_UTC,
    apply_causal_bias_correction,
    candidate_spec,
    summarise_candidate,
)


def _rows(n=240):
    target = pd.date_range("2026-08-15T00:00:00Z", periods=n, freq="30min")
    frozen = np.linspace(90.0, 110.0, n)
    realised = frozen + 10.0
    return pd.DataFrame({
        "target_start_utc": target,
        "decision_time_utc": target - pd.Timedelta(minutes=120),
        "realised_price_gbp_mwh": realised,
        "frozen_prediction_gbp_mwh": frozen,
        "previous_settlement_day_reference_gbp_mwh": realised + 5.0,
    })


def test_correction_cannot_use_own_or_recent_unavailable_label():
    base = _rows()
    a = apply_causal_bias_correction(base)
    changed = base.copy()
    probe = 160
    changed.loc[probe:, "realised_price_gbp_mwh"] = 5000.0
    b = apply_causal_bias_correction(changed)
    # The target at probe and the next four half-hours are decided before the
    # changed probe outcome can be available. Their predictions must be identical.
    np.testing.assert_allclose(
        a.loc[probe:probe + 4, "adaptive_prediction_gbp_mwh"],
        b.loc[probe:probe + 4, "adaptive_prediction_gbp_mwh"],
    )


def test_48h_mean_removes_persistent_level_bias_after_warmup():
    x = apply_causal_bias_correction(_rows())
    mature = x[x["bias_history_rows"] >= 24]
    assert len(mature) > 100
    assert abs(float(mature["bias_correction_gbp_mwh"].median()) - 10.0) < 1e-9
    assert float(mature["adaptive_abs_error_gbp_mwh"].max()) < 1e-9


def test_candidate_segment_is_versioned_and_summarised():
    x = apply_causal_bias_correction(_rows(400))
    result = summarise_candidate(x, start_utc=V25_FORWARD_START_UTC)
    assert result["status"] in {"NO_FORWARD_ROWS", "FORWARD_MONITORING"}
    spec = candidate_spec()
    assert spec["version"] == "0.25.0"
    assert spec["candidate"] == "2H_FROZEN_PLUS_CAUSAL_48H_RESIDUAL_MEAN"
    assert spec["rule"]["lookback_hours"] == 48
    assert spec["rule"]["horizon_minutes"] == 120


def test_wrong_decision_clock_fails_closed():
    x = _rows(50)
    x.loc[0, "decision_time_utc"] = pd.Timestamp("2026-08-14T20:00:00Z")
    try:
        apply_causal_bias_correction(x, rule=BiasCorrectionRule())
    except ValueError as exc:
        assert "decision_time_utc" in str(exc)
    else:
        raise AssertionError("expected decision-clock validation to fail")
