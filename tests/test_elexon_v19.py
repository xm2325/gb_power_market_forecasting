from __future__ import annotations

import numpy as np
import pandas as pd

from gb_power_market.elexon_v19 import (
    audit_elexon_bundle,
    build_information_safe_market_frame,
    build_volume_weighted_market_reference,
    expected_settlement_keys,
    normalise_mid,
    normalise_system_prices,
)


def test_expected_settlement_periods_follow_gb_dst_clock():
    spring = expected_settlement_keys("2026-03-29", "2026-03-30")
    autumn = expected_settlement_keys("2026-10-25", "2026-10-26")
    ordinary = expected_settlement_keys("2026-08-01", "2026-08-02")
    assert len(spring) == 46
    assert len(autumn) == 50
    assert len(ordinary) == 48


def test_normalisers_validate_bst_settlement_clock_and_weight_midp():
    # 2026-08-01 SP1 begins at 2026-07-31 23:00 UTC because GB is on BST.
    mid_payload = {"data": [
        {"startTime": "2026-07-31T23:00:00Z", "dataProvider": "APXMIDP", "settlementDate": "2026-08-01", "settlementPeriod": 1, "price": 81.0, "volume": 100.0},
        {"startTime": "2026-07-31T23:00:00Z", "dataProvider": "N2EXMIDP", "settlementDate": "2026-08-01", "settlementPeriod": 1, "price": 79.0, "volume": 300.0},
    ]}
    sys_payload = {"data": [
        {"startTime": "2026-07-31T23:00:00Z", "settlementDate": "2026-08-01", "settlementPeriod": 1, "systemSellPrice": 100.0, "systemBuyPrice": 100.0, "netImbalanceVolume": 120.0}
    ]}
    mid = normalise_mid(mid_payload)
    system = normalise_system_prices(sys_payload)
    ref = build_volume_weighted_market_reference(mid)
    assert mid["clock_error_seconds"].max() == 0
    assert system["clock_error_seconds"].max() == 0
    assert np.isclose(ref.loc[0, "reference_market_price_gbp_mwh"], 79.5)
    assert ref.loc[0, "n_midp"] == 2


def test_previous_settlement_day_feature_is_not_hardcoded_shift48_across_dst():
    keys = expected_settlement_keys("2026-03-27", "2026-03-31")
    keys["reference_market_price_gbp_mwh"] = np.arange(len(keys), dtype=float)
    frame = build_information_safe_market_frame(keys, horizon_minutes=30)
    # 30 March has 48 SPs, but 29 March (spring-clock day) has only 46.
    mar30 = frame[frame["settlement_date"] == "2026-03-30"]
    assert mar30.loc[mar30["settlement_period"] == 47, "price_lag_1d_same_target"].isna().all()
    assert mar30.loc[mar30["settlement_period"] == 48, "price_lag_1d_same_target"].isna().all()
    # The diagnostic 24h-UTC lag still exists and is a different semantic object.
    assert mar30.loc[mar30["settlement_period"] == 47, "price_lag_24h_utc"].notna().all()


def test_real_market_coverage_audit_uses_expected_settlement_denominator():
    keys = expected_settlement_keys("2026-08-01", "2026-08-03")
    ref = keys.copy(); ref["reference_market_price_gbp_mwh"] = 80.0; ref["n_midp"] = 2
    sys = keys.copy(); sys["system_buy_price_gbp_mwh"] = 100.0; sys["system_sell_price_gbp_mwh"] = 100.0
    audit = audit_elexon_bundle(reference=ref, system_prices=sys, start_date="2026-08-01", end_date_exclusive="2026-08-03")
    assert audit["status"] == "PASS_REAL"
    assert audit["expected_settlement_periods"] == 96
