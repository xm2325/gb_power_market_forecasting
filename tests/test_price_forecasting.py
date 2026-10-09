import numpy as np
import pandas as pd

from gb_power_market.price_forecasting import (
    NumpyRidge,
    PricePromotionRule,
    audit_asof_feature_publications,
    build_information_safe_price_frame,
    run_chronological_price_experiment,
)


def _market(n=900):
    t = pd.date_range("2026-01-01", periods=n, freq="30min", tz="UTC")
    i = np.arange(n)
    price = 70 + 12 * np.sin(2 * np.pi * i / 48) + 4 * np.cos(2 * np.pi * i / (48 * 7)) + 0.01 * i
    return pd.DataFrame({"target_start_utc": t, "reference_market_price_gbp_mwh": price})


def test_safe_price_lag_respects_30min_decision_boundary():
    df = build_information_safe_price_frame(_market(60), horizon_minutes=30)
    # 30-minute-ahead decision uses the period two half-hours behind target:
    # the immediately preceding period is still the decision settlement period.
    assert df.loc[10, "price_lag_last_completed"] == df.loc[8, "reference_market_price_gbp_mwh"]
    assert df.loc[10, "safe_price_shift_periods"] == 2


def test_future_target_change_does_not_change_earlier_safe_feature():
    m = _market(80)
    a = build_information_safe_price_frame(m, horizon_minutes=120)
    m.loc[40:, "reference_market_price_gbp_mwh"] += 10000
    b = build_information_safe_price_frame(m, horizon_minutes=120)
    assert a.loc[39, "price_lag_last_completed"] == b.loc[39, "price_lag_last_completed"]


def test_publication_audit_blocks_future_exogenous_forecast():
    df = pd.DataFrame({
        "decision_time_utc": ["2026-08-01T10:00:00Z", "2026-08-01T10:30:00Z"],
        "wind_publish_time_utc": ["2026-08-01T09:00:00Z", "2026-08-01T11:00:00Z"],
    })
    out = audit_asof_feature_publications(df, publish_cols=["wind_publish_time_utc"])
    assert out["status"] == "BLOCKED"
    assert out["future_publications"] == 1


def test_numpy_ridge_runs_deterministically():
    x = np.arange(20, dtype=float).reshape(-1, 1)
    y = 2 * x[:, 0] + 3
    model = NumpyRidge(alpha=0.0).fit(x, y)
    pred = model.predict(np.array([[20.0]]))[0]
    assert abs(pred - 43.0) < 1e-8


def test_chronological_experiment_selects_before_final():
    frame = build_information_safe_price_frame(_market(), horizon_minutes=30)
    out = run_chronological_price_experiment(
        frame,
        promotion_rule=PricePromotionRule(minimum_validation_improvement_pct=0.0, minimum_validation_rows=50),
    )
    assert out["split"]["validation_rows"] >= 50
    assert out["final_test"]["deployed_source"] in {"RIDGE_MODEL", "PREVIOUS_DAY_FALLBACK"}
    assert "final test scored once" in out["selection_boundary"]


def test_numpy_ridge_alpha_zero_handles_collinear_constant_features():
    x = np.column_stack([np.arange(20, dtype=float), np.ones(20), np.ones(20)])
    y = 2 * x[:, 0] + 3
    model = NumpyRidge(alpha=0.0).fit(x, y)
    pred = model.predict(np.array([[20.0, 1.0, 1.0]]))[0]
    assert abs(pred - 43.0) < 1e-8
