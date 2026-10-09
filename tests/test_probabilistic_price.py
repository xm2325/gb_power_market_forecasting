import numpy as np
import pandas as pd

from gb_power_market.neso_embedded import select_asof_physical_features
from gb_power_market.price_feature_families import FeatureFamilyRule, merge_price_and_neso_features
from gb_power_market.price_forecasting import build_information_safe_price_frame
from gb_power_market.price_tail import TailGuardRule
from gb_power_market.probabilistic_price import (
    ProbabilisticRule,
    abstention_metrics,
    finite_sample_conformal_quantile,
    interval_metrics,
    run_probabilistic_price_experiment,
)


def _frame(n=1800, seed=14014):
    rng = np.random.default_rng(seed)
    t = pd.date_range("2026-01-01", periods=n, freq="30min", tz="UTC")
    i = np.arange(n)
    hour = t.hour.to_numpy() + t.minute.to_numpy() / 60.0
    solar = np.maximum(0.0, 9500 * np.sin(np.pi * (hour - 4.5) / 16.0))
    wind = 4800 + 800 * np.sin(2 * np.pi * i / (48 * 3.7))
    rev = 350 * np.sin(2 * np.pi * i / 19) + rng.normal(0, 40, n)
    # Heteroscedastic fixture makes local interval widths non-constant.
    sigma = 2.0 + 0.003 * np.abs(rev)
    price = 78 - 0.002 * wind - 0.0012 * solar - 0.012 * rev + 6 * np.sin(2*np.pi*i/48) + rng.normal(0, sigma)
    market = pd.DataFrame({"target_start_utc": t, "reference_market_price_gbp_mwh": price})
    base = build_information_safe_price_frame(market, horizon_minutes=30)
    rows = []
    for ts, s, w, r in zip(t, solar, wind, rev, strict=True):
        decision = ts - pd.Timedelta(minutes=30)
        end = ts + pd.Timedelta(minutes=30)
        for age_h, delta in [(3, -r), (1, 0.0)]:
            rows.append({
                "target_end_utc": end,
                "publish_time_utc": decision - pd.Timedelta(hours=age_h),
                "embedded_wind_forecast_mw": w + delta,
                "embedded_wind_capacity_mw": 15000.0,
                "embedded_solar_forecast_mw": max(0.0, s + delta),
                "embedded_solar_capacity_mw": 22000.0,
                "source_regime": "fixture",
            })
    selected = select_asof_physical_features(
        base[["target_start_utc", "decision_time_utc"]], pd.DataFrame(rows)
    )
    return merge_price_and_neso_features(base, selected)


def _kwargs():
    return dict(
        family_rule=FeatureFamilyRule(
            minimum_validation_rows=50,
            minimum_improvement_vs_previous_day_pct=-100.0,
            minimum_margin_to_add_revision_pct=0.0,
        ),
        tail_rule=TailGuardRule(
            minimum_large_move_rows=1,
            maximum_large_move_mae_degradation_pct=1e9,
        ),
        probabilistic_rule=ProbabilisticRule(minimum_calibration_rows=50),
    )


def test_finite_sample_conformal_quantile_uses_ceiling_rank():
    scores = np.arange(1.0, 10.0)
    # ceil((9 + 1) * .8) = 8 -> eighth ordered value
    assert finite_sample_conformal_quantile(scores, 0.8) == 8.0


def test_interval_and_abstention_metrics():
    y = np.array([10.0, 0.0, 5.0, 5.0])
    lo = np.array([8.0, -2.0, 4.0, 3.0])
    hi = np.array([12.0, 2.0, 6.0, 7.0])
    lk = np.array([7.0, 3.0, 5.0, 5.0])
    p = (lo + hi) / 2
    m = interval_metrics(y, lo, hi, 0.9)
    a = abstention_metrics(y, p, lo, hi, lk)
    assert m["empirical_coverage"] == 1.0
    assert a["n_actions"] == 2
    assert a["action_rate"] == 0.5


def test_probabilistic_experiment_has_four_way_boundary_and_variable_width():
    out = run_probabilistic_price_experiment(_frame(), **_kwargs())
    assert out["common_intersection"]["calibration_rows"] >= 50
    assert "before calibration and final" in out["point_selection"]["boundary"]
    assert out["final_test"]["interval"]["p95_width_gbp_mwh"] >= out["final_test"]["interval"]["median_width_gbp_mwh"]
    assert 0.0 <= out["final_test"]["abstention"]["action_rate"] <= 1.0


def test_final_target_attack_cannot_change_selection_or_conformal_quantile():
    frame = _frame(1800)
    original = run_probabilistic_price_experiment(frame, **_kwargs())
    perturbed = frame.copy()
    # Last 10% is wholly within the final block for the default 50/20/15/15 split.
    idx = perturbed.index[-180:]
    perturbed.loc[idx, "reference_market_price_gbp_mwh"] += np.linspace(1000, 5000, len(idx))
    changed = run_probabilistic_price_experiment(perturbed, **_kwargs())
    assert changed["point_selection"] == original["point_selection"]
    assert changed["calibration"]["finite_sample_quantile"] == original["calibration"]["finite_sample_quantile"]


def test_calibration_attack_can_change_interval_but_not_point_selection():
    frame = _frame(1800)
    original = run_probabilistic_price_experiment(frame, **_kwargs())
    changed_frame = frame.copy()
    # Complete rows start after lag warm-up. These indices are chosen to fall
    # in the calibration block but before the final block under the default split.
    # Compute from the run-reported common-row counts to avoid relying on raw warm-up.
    common = frame.dropna(subset=[
        "reference_market_price_gbp_mwh", "target_start_utc", "price_lag_1d_same_target", "price_lag_last_completed",
        *(__import__("gb_power_market.probabilistic_price", fromlist=["FAMILIES"]).FAMILIES["PRICE_PLUS_NESO_LEVELS_AND_REVISIONS"]),
    ]).sort_values("target_start_utc")
    n = len(common)
    cal_start = int(np.floor(n * 0.70))
    cal_end = int(np.floor(n * 0.85))
    attack_rows = common.index[cal_start:cal_end]
    changed_frame.loc[attack_rows, "reference_market_price_gbp_mwh"] += 300.0
    changed = run_probabilistic_price_experiment(changed_frame, **_kwargs())
    assert changed["point_selection"] == original["point_selection"]
    assert changed["calibration"]["finite_sample_quantile"] != original["calibration"]["finite_sample_quantile"]
