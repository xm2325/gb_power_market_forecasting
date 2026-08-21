from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from gb_power_market.archive_v18 import (
    DEFAULT_HORIZONS,
    benchmark_asof_forecasts,
    normalise_outturn_2026,
)

ROOT = Path(__file__).resolve().parents[1]


def test_horizon_cutoffs_are_target_start_safe():
    assert [h.cutoff_minutes_to_target_end for h in DEFAULT_HORIZONS] == [60, 150, 390, 750]


def test_official_outturn_sample_maps_sp1_to_0030_utc():
    payload = json.loads((ROOT / "fixtures" / "neso_historic_demand_2026_official_sample.json").read_text())
    out = normalise_outturn_2026(payload)
    assert len(out) == 5
    assert out.iloc[0]["target_end_utc"] == pd.Timestamp("2026-01-01T00:30:00Z")
    assert out.iloc[0]["actual_wind_mw"] == 4146.0
    assert out.iloc[0]["actual_solar_mw"] == 0.0


def test_asof_benchmark_never_uses_future_publication():
    payload = json.loads((ROOT / "fixtures" / "neso_historic_demand_2026_official_sample.json").read_text())
    outturn = normalise_outturn_2026(payload)
    targets = outturn["target_end_utc"]
    rows = []
    for i, t in enumerate(targets):
        rows.append({"target_end_utc": t, "publish_time_utc": t - pd.Timedelta(minutes=90), "wind_mw": 4100+i, "solar_mw": 0})
        rows.append({"target_end_utc": t, "publish_time_utc": t - pd.Timedelta(minutes=20), "wind_mw": 9999, "solar_mw": 9999})
    forecasts = pd.DataFrame(rows)
    res = benchmark_asof_forecasts(forecasts, outturn, horizon_periods=1)
    assert res["future_publications"] == 0
    assert res["n_with_asof_forecast"] == 5
    assert res["wind"]["mae"] < 100


def test_official_forecast_and_outturn_samples_join_with_asof_cutoff():
    from gb_power_market.neso_embedded import normalise_neso_embedded_archive
    fp = json.loads((ROOT / "fixtures" / "neso_legacy_2026_official_sample.json").read_text())
    op = json.loads((ROOT / "fixtures" / "neso_historic_demand_2026_official_sample.json").read_text())
    f = normalise_neso_embedded_archive(fp, source_regime="legacy_2026_jan_jun").rename(columns={
        "embedded_wind_forecast_mw": "wind_mw",
        "embedded_solar_forecast_mw": "solar_mw",
    })
    o = normalise_outturn_2026(op)
    res = benchmark_asof_forecasts(f, o, horizon_periods=1)
    # The issue was published at 00:12. At a 30-minute horizon the first
    # eligible target in this five-row sample is SP3 (target end 01:30,
    # decision time 00:30), so exactly three rows are eligible.
    assert res["n_with_asof_forecast"] == 3
    assert res["future_publications"] == 0
