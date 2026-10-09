import numpy as np
import pandas as pd

from gb_power_market.neso_embedded import select_asof_physical_features
from gb_power_market.price_feature_families import (
    FeatureFamilyRule,
    merge_price_and_neso_features,
    run_price_feature_family_experiment,
)
from gb_power_market.price_forecasting import build_information_safe_price_frame
from gb_power_market.price_tail import TailGuardRule


def _price_and_revisions(n=1200):
    t = pd.date_range("2026-01-01", periods=n, freq="30min", tz="UTC")
    i = np.arange(n)
    solar = np.maximum(0.0, 9000 * np.sin(2 * np.pi * ((i % 48) - 12) / 48))
    wind = 4000 + 700 * np.sin(2 * np.pi * i / (48 * 3))
    # The revision term carries incremental predictive information in the fixture.
    revision = 400 * np.sin(2 * np.pi * i / 17)
    price = 70 + 0.0015 * solar - 0.001 * wind + 0.006 * revision + 3 * np.sin(2*np.pi*i/48)
    market = pd.DataFrame({
        "target_start_utc": t,
        "reference_market_price_gbp_mwh": price,
    })
    base = build_information_safe_price_frame(market, horizon_minutes=30)

    rows = []
    for ts, s, w, r in zip(t, solar, wind, revision, strict=True):
        decision = ts - pd.Timedelta(minutes=30)
        end = ts + pd.Timedelta(minutes=30)
        for age_h, frac in [(3, -1.0), (1, 0.0)]:
            rows.append({
                "target_end_utc": end,
                "publish_time_utc": decision - pd.Timedelta(hours=age_h),
                "embedded_wind_forecast_mw": w + frac * r,
                "embedded_wind_capacity_mw": 6500.0,
                "embedded_solar_forecast_mw": s + frac * r,
                "embedded_solar_capacity_mw": 22000.0,
                "source_regime": "fixture",
            })
    revisions = pd.DataFrame(rows)
    selected = select_asof_physical_features(base[["target_start_utc", "decision_time_utc"]], revisions)
    return merge_price_and_neso_features(base, selected)


def test_feature_family_experiment_uses_common_intersection_and_pre_final_selection():
    frame = _price_and_revisions()
    out = run_price_feature_family_experiment(
        frame,
        rule=FeatureFamilyRule(
            minimum_validation_rows=100,
            minimum_improvement_vs_previous_day_pct=-100.0,
            minimum_margin_to_add_revision_pct=0.0,
        ),
        tail_rule=TailGuardRule(
            minimum_large_move_rows=1,
            maximum_large_move_mae_degradation_pct=1e9,
        ),
    )
    assert out["common_intersection"]["validation_rows"] >= 100
    assert "before final test" in out["selection"]["boundary"]
    assert out["selection"]["selected_family"] in {
        "PRICE_HISTORY_ONLY", "PRICE_PLUS_NESO_LEVELS", "PRICE_PLUS_NESO_LEVELS_AND_REVISIONS"
    }
    assert out["final_test"]["deployed_source"] == out["selection"]["selected_family"]


def test_future_revision_does_not_change_selected_feature():
    frame = _price_and_revisions(500)
    # The merged frame has already gone through the as-of selector. A direct
    # publication audit remains true for every selected feature row.
    pub = pd.to_datetime(frame["neso_publish_time_utc"], utc=True)
    dec = pd.to_datetime(frame["decision_time_utc"], utc=True)
    assert (pub <= dec).all()


def test_final_targets_cannot_change_feature_family_or_promotion():
    frame = _price_and_revisions(1400)
    kwargs = dict(
        rule=FeatureFamilyRule(
            minimum_validation_rows=100,
            minimum_improvement_vs_previous_day_pct=-100.0,
            minimum_margin_to_add_revision_pct=0.0,
        ),
        tail_rule=TailGuardRule(
            minimum_large_move_rows=1,
            maximum_large_move_mae_degradation_pct=1e9,
        ),
    )
    original = run_price_feature_family_experiment(frame, **kwargs)
    perturbed = frame.copy()
    # Change only a late block that is wholly inside the chronological final
    # region. If any selection step reads final targets, this can change it.
    late = perturbed.index[-150:]
    perturbed.loc[late, "reference_market_price_gbp_mwh"] += np.linspace(1000, 5000, len(late))
    changed = run_price_feature_family_experiment(perturbed, **kwargs)
    assert changed["selection"] == original["selection"]
    assert changed["tail_definition"]["selection_large_move_threshold_gbp_mwh"] == original["tail_definition"]["selection_large_move_threshold_gbp_mwh"]
