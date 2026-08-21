import json
from pathlib import Path

import pandas as pd
import pytest

from gb_power_market.neso_embedded import (
    NesoFeatureGate,
    audit_neso_feature_coverage,
    build_current_asof_pair_sql,
    normalise_neso_embedded_archive,
    select_asof_physical_features,
    settlement_period_ends_utc,
    stitch_2026_regimes,
)

FIX = Path(__file__).resolve().parents[1] / "fixtures"


def _load(name):
    return json.loads((FIX / name).read_text())


def test_legacy_sample_reconstructs_distinct_period_ends():
    out = normalise_neso_embedded_archive(
        _load("neso_legacy_2026_official_sample.json"),
        source_regime="legacy_2026_jan_jun",
    )
    assert out["target_end_utc"].nunique() == 5
    assert out.loc[0, "target_end_utc"] == pd.Timestamp("2026-01-01T00:30:00Z")
    assert out.loc[4, "target_end_utc"] == pd.Timestamp("2026-01-01T02:30:00Z")


def test_current_sample_date_gmt_cross_checks_period_end():
    out = normalise_neso_embedded_archive(
        _load("neso_current_2026_official_sample.json"),
        source_regime="current_2026_jun_dec",
    )
    assert out.loc[0, "target_end_utc"] == pd.Timestamp("2026-06-12T12:30:00Z")
    assert out.loc[0, "target_start_utc"] == pd.Timestamp("2026-06-12T12:00:00Z")
    assert out["target_clock_difference_seconds"].max() == 0


def test_current_clock_corruption_is_blocked():
    payload = _load("neso_current_2026_official_sample.json")
    payload["records"][0]["DATE_GMT"] = "2026-06-12T12:31:00"
    with pytest.raises(ValueError, match="settlement-clock cross-check"):
        normalise_neso_embedded_archive(payload, source_regime="current_2026_jun_dec")


def test_gb_settlement_clock_is_dst_safe():
    assert len(settlement_period_ends_utc("2026-03-29")) == 46
    assert len(settlement_period_ends_utc("2026-10-25")) == 50
    assert len(settlement_period_ends_utc("2026-02-01")) == 48


def test_stitch_uses_current_from_its_first_observed_target():
    legacy = normalise_neso_embedded_archive(
        _load("neso_legacy_2026_official_sample.json"), source_regime="legacy_2026_jan_jun"
    )
    current = normalise_neso_embedded_archive(
        _load("neso_current_2026_official_sample.json"), source_regime="current_2026_jun_dec"
    )
    combined, manifest = stitch_2026_regimes(legacy, current)
    assert len(combined) == 10
    assert manifest["current_first_target_end_utc"].startswith("2026-06-12T12:30")


def test_select_asof_uses_last_two_known_revisions_only():
    target_start = pd.Timestamp("2026-08-01T12:00:00Z")
    price_targets = pd.DataFrame({
        "target_start_utc": [target_start],
        "decision_time_utc": [target_start - pd.Timedelta(hours=2)],
    })
    target_end = target_start + pd.Timedelta(minutes=30)
    rev = pd.DataFrame({
        "target_end_utc": [target_end] * 3,
        "publish_time_utc": [
            target_start - pd.Timedelta(hours=4),
            target_start - pd.Timedelta(hours=3),
            target_start - pd.Timedelta(hours=1),  # future relative to decision
        ],
        "embedded_wind_forecast_mw": [4000, 4200, 9000],
        "embedded_wind_capacity_mw": [6500, 6500, 6500],
        "embedded_solar_forecast_mw": [7000, 7600, 9999],
        "embedded_solar_capacity_mw": [22000, 22000, 22000],
        "source_regime": ["current_2026_jun_dec"] * 3,
    })
    out = select_asof_physical_features(price_targets, rev)
    assert out.loc[0, "neso_embedded_solar_forecast_mw"] == 7600
    assert out.loc[0, "neso_embedded_solar_revision_delta_mw"] == 600
    assert out.loc[0, "neso_publish_time_utc"] <= out.loc[0, "decision_time_utc"]


def test_feature_coverage_gate_blocks_sparse_archive():
    target_start = pd.date_range("2026-08-01", periods=10, freq="30min", tz="UTC")
    targets = pd.DataFrame({
        "target_start_utc": target_start,
        "decision_time_utc": target_start - pd.Timedelta(minutes=30),
    })
    selected = pd.DataFrame({
        "target_start_utc": target_start[:2],
        "neso_publish_time_utc": target_start[:2] - pd.Timedelta(hours=1),
    })
    out = audit_neso_feature_coverage(
        targets, selected, gate=NesoFeatureGate(minimum_rows=5, minimum_coverage=0.8)
    )
    assert out["status"] == "BLOCKED"


def test_query_builder_uses_extra_half_hour_and_two_vintages():
    sql = build_current_asof_pair_sql(
        start_target_end_utc="2026-07-12T12:30:00Z",
        end_target_end_exclusive_utc="2026-08-15T08:00:00Z",
        horizon_periods=4,
    )
    assert "INTERVAL '150 minutes'" in sql
    assert "vintage_rank <= 2" in sql
    assert "31861619-0b86-47ba-bac2-d008a760af54" in sql
