import numpy as np
import pandas as pd

from gb_power_market.market_stress import (
    StressGate,
    apply_spread_regimes,
    audit_stress_population,
    conditioned_forecast_metrics,
    daily_block_bootstrap_exposure_delta,
    fit_spread_regime_thresholds,
)


def test_thresholds_fit_on_supplied_calibration_only():
    cal = pd.DataFrame({"absolute_spread_gbp_mwh": np.arange(1, 101, dtype=float)})
    t = fit_spread_regime_thresholds(cal)
    assert t["n_calibration_rows"] == 100
    assert t["high_threshold_gbp_mwh"] > 79
    assert t["extreme_threshold_gbp_mwh"] > t["high_threshold_gbp_mwh"]


def test_apply_regimes_uses_frozen_thresholds():
    cal = pd.DataFrame({"absolute_spread_gbp_mwh": np.arange(1, 101, dtype=float)})
    t = fit_spread_regime_thresholds(cal)
    final = pd.DataFrame({"absolute_spread_gbp_mwh": [5.0, 85.0, 99.0]})
    got = apply_spread_regimes(final, t)
    assert list(got["spread_regime"].astype(str)) == ["normal", "high", "extreme"]


def test_conditioned_metrics_keep_price_weighted_boundary():
    df = pd.DataFrame({
        "actual": [100, 100, 100],
        "ref": [80, 80, 80],
        "model": [90, 95, 100],
        "spread_regime": ["normal", "high", "extreme"],
        "absolute_spread_gbp_mwh": [10.0, 50.0, 100.0],
    })
    out = conditioned_forecast_metrics(
        df, actual_col="actual", reference_col="ref", challenger_col="model"
    )
    assert out["overall"]["challenger_mae_mw"] < out["overall"]["reference_mae_mw"]
    assert "not realised trading P&L" in out["metric_semantics"]


def test_stress_gate_can_fail_closed():
    df = pd.DataFrame({"spread_regime": ["normal"] * 10, "price": [1.0] * 10})
    out = audit_stress_population(
        df, price_present_col="price", gate=StressGate(minimum_rows=20, minimum_stress_rows=2)
    )
    assert out["status"] == "BLOCKED"


def test_daily_block_bootstrap_exposure_delta_sign():
    ts = pd.date_range("2026-08-01", periods=96, freq="30min", tz="UTC")
    df = pd.DataFrame({
        "target_start_utc": ts,
        "ref_exp": np.full(len(ts), 10.0),
        "model_exp": np.full(len(ts), 6.0),
    })
    out = daily_block_bootstrap_exposure_delta(
        df, reference_exposure_col="ref_exp", challenger_exposure_col="model_exp", n_boot=200
    )
    assert out["total_exposure_delta_gbp"] < 0
    assert out["prob_challenger_lower_exposure"] == 1.0
