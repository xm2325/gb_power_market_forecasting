from __future__ import annotations

import numpy as np
import pandas as pd

from gb_power_market.elexon_v19 import build_information_safe_market_frame, expected_settlement_keys
from gb_power_market.fixed_market_experiment import FixedMarketWindows, run_fixed_window_real_price_experiment


def make_frame(horizon_minutes=30):
    keys = expected_settlement_keys("2026-01-01", "2026-08-16")
    t = pd.to_datetime(keys["target_start_utc"], utc=True)
    local = t.dt.tz_convert("Europe/London")
    hour = local.dt.hour + local.dt.minute / 60
    rng = np.random.default_rng(19)
    # Deterministic daily/weekly signal plus modest noise; the previous-day baseline is useful but not perfect.
    price = 70 + 18*np.sin(2*np.pi*hour/24) + 7*np.cos(2*np.pi*local.dt.dayofweek/7) + rng.normal(0, 2.5, len(keys))
    keys["reference_market_price_gbp_mwh"] = price
    base = build_information_safe_market_frame(keys, horizon_minutes=horizon_minutes)
    decision = base["decision_time_utc"]
    # Physical features are all as-of and deliberately informative about price.
    base["neso_publish_time_utc"] = decision - pd.Timedelta(minutes=6)
    base["neso_source_regime"] = "fixture"
    base["neso_forecast_age_minutes"] = 6.0
    base["neso_embedded_wind_forecast_mw"] = 5000 + 300*base["hour_cos"]
    base["neso_embedded_solar_forecast_mw"] = 8000*np.maximum(0, base["hour_sin"])
    base["neso_embedded_wind_capacity_mw"] = 30000.0
    base["neso_embedded_solar_capacity_mw"] = 25000.0
    base["neso_embedded_wind_revision_delta_mw"] = 30*base["dow_sin"]
    base["neso_embedded_wind_abs_revision_delta_mw"] = base["neso_embedded_wind_revision_delta_mw"].abs()
    base["neso_embedded_solar_revision_delta_mw"] = 40*base["hour_cos"]
    base["neso_embedded_solar_abs_revision_delta_mw"] = base["neso_embedded_solar_revision_delta_mw"].abs()
    return base


def test_fixed_window_final_target_attack_cannot_change_selection():
    frame = make_frame(30)
    a = run_fixed_window_real_price_experiment(frame, horizon_minutes=30)
    attacked = frame.copy()
    w = FixedMarketWindows().parsed()
    m = (attacked["target_start_utc"] >= w["final_start_utc"]) & (attacked["target_start_utc"] < w["final_end_exclusive_utc"])
    attacked.loc[m, "reference_market_price_gbp_mwh"] += np.linspace(1000, 5000, int(m.sum()))
    b = run_fixed_window_real_price_experiment(attacked, horizon_minutes=30)
    assert a["selection"]["selected_family"] == b["selection"]["selected_family"]
    assert a["selection"]["promoted"] == b["selection"]["promoted"]
    assert a["selection"]["by_family"] == b["selection"]["by_family"]
    assert a["calibration"]["absolute_residual_quantile_gbp_mwh"] == b["calibration"]["absolute_residual_quantile_gbp_mwh"]


def test_fixed_window_final_has_frozen_1623_target_denominator():
    r = run_fixed_window_real_price_experiment(make_frame(30), horizon_minutes=30)
    assert r["rows"]["expected_final"] == 1623
    assert r["rows"]["final_coverage"] > 0.95
    assert r["claim_gate"]["status"] == "PASS_REAL"


def test_future_neso_publication_blocks_real_claim():
    frame = make_frame(30)
    w = FixedMarketWindows().parsed()
    idx = frame.index[(frame["target_start_utc"] >= w["final_start_utc"]) & (frame["target_start_utc"] < w["final_end_exclusive_utc"])][0]
    frame.loc[idx, "neso_publish_time_utc"] = frame.loc[idx, "decision_time_utc"] + pd.Timedelta(minutes=1)
    r = run_fixed_window_real_price_experiment(frame, horizon_minutes=30)
    assert r["information_audit"]["future_neso_publications"] == 1
    assert r["claim_gate"]["status"] == "BLOCKED"
