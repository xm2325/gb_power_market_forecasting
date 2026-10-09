from __future__ import annotations

import pandas as pd


VALIDATION_END_UTC = pd.Timestamp("2026-08-24T22:00:00Z")
SAFETY_LAG_MINUTES = 90
MARKET_GRID_MINUTES = 30


def _utc(value: str | pd.Timestamp) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    if ts.tzinfo is None:
        raise ValueError("v0.27 maturity timestamps must be timezone-aware")
    return ts.tz_convert("UTC")


def safe_market_data_boundary(now_utc: str | pd.Timestamp) -> pd.Timestamp:
    now = _utc(now_utc)
    lagged = now - pd.Timedelta(minutes=SAFETY_LAG_MINUTES)
    return lagged.floor(f"{MARKET_GRID_MINUTES}min")


def assess_validation_maturity(now_utc: str | pd.Timestamp) -> dict:
    now = _utc(now_utc)
    safe = safe_market_data_boundary(now)
    ready = safe >= VALIDATION_END_UTC
    return {
        "now_utc": now.isoformat(),
        "safe_market_data_boundary_utc": safe.isoformat(),
        "required_validation_end_utc": VALIDATION_END_UTC.isoformat(),
        "safety_lag_minutes": SAFETY_LAG_MINUTES,
        "market_grid_minutes": MARKET_GRID_MINUTES,
        "sealed_validation_mature": ready,
        "network_label_access_allowed": ready,
    }
