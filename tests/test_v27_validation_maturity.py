import pandas as pd

from gb_power_market.v27_validation_maturity import (
    assess_validation_maturity,
    safe_market_data_boundary,
)


def test_safe_boundary_applies_90_minute_lag_then_30_minute_floor() -> None:
    assert safe_market_data_boundary("2026-08-24T23:29:59Z") == pd.Timestamp("2026-08-24T21:30:00Z")
    assert safe_market_data_boundary("2026-08-24T23:30:00Z") == pd.Timestamp("2026-08-24T22:00:00Z")
    assert safe_market_data_boundary("2026-08-24T23:59:59Z") == pd.Timestamp("2026-08-24T22:00:00Z")


def test_validation_is_closed_one_second_before_first_safe_opening() -> None:
    result = assess_validation_maturity("2026-08-24T23:29:59Z")
    assert result["sealed_validation_mature"] is False
    assert result["network_label_access_allowed"] is False
    assert result["safe_market_data_boundary_utc"] == "2026-08-24T21:30:00+00:00"


def test_validation_first_opens_at_2330_utc() -> None:
    result = assess_validation_maturity("2026-08-24T23:30:00Z")
    assert result["sealed_validation_mature"] is True
    assert result["network_label_access_allowed"] is True
    assert result["safe_market_data_boundary_utc"] == "2026-08-24T22:00:00+00:00"
