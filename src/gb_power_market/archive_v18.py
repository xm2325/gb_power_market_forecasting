from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

GB_TZ = ZoneInfo("Europe/London")
OUTTURN_2026_RESOURCE_ID = "8a4a771c-3929-4e56-93ad-cdf13219dea5"


@dataclass(frozen=True)
class HorizonSpec:
    name: str
    periods: int

    @property
    def cutoff_minutes_to_target_end(self) -> int:
        # Forecasting horizon is measured to target start. The archive key is
        # target end, one half-hour later.
        return (int(self.periods) + 1) * 30


DEFAULT_HORIZONS = (
    HorizonSpec("30m", 1),
    HorizonSpec("2h", 4),
    HorizonSpec("6h", 12),
    HorizonSpec("12h", 24),
)


def canonical_period_end_utc(settlement_date: str, settlement_period: int) -> pd.Timestamp:
    d = pd.Timestamp(settlement_date).date()
    start_local = pd.Timestamp(datetime.combine(d, datetime.min.time()), tz=GB_TZ)
    end_local = pd.Timestamp(datetime.combine(d + timedelta(days=1), datetime.min.time()), tz=GB_TZ)
    ends = pd.date_range(start_local.tz_convert("UTC"), end_local.tz_convert("UTC"), freq="30min", inclusive="right")
    sp = int(settlement_period)
    if sp < 1 or sp > len(ends):
        raise ValueError(f"settlement period {sp} invalid for {d}; expected 1..{len(ends)}")
    return ends[sp - 1]


def normalise_outturn_2026(payload: pd.DataFrame | list[dict] | dict) -> pd.DataFrame:
    if isinstance(payload, pd.DataFrame):
        raw = payload.copy()
    elif isinstance(payload, dict) and "result" in payload:
        raw = pd.DataFrame(payload["result"].get("records", []))
    elif isinstance(payload, dict) and "records" in payload:
        raw = pd.DataFrame(payload["records"])
    else:
        raw = pd.DataFrame(payload)

    required = {
        "SETTLEMENT_DATE", "SETTLEMENT_PERIOD", "FORECAST_ACTUAL_INDICATOR",
        "EMBEDDED_WIND_GENERATION", "EMBEDDED_SOLAR_GENERATION",
    }
    missing = required.difference(raw.columns)
    if missing:
        raise ValueError(f"outturn missing fields: {sorted(missing)}")

    actual = raw[raw["FORECAST_ACTUAL_INDICATOR"].astype(str).str.upper().eq("A")].copy()
    if actual.empty:
        raise ValueError("outturn contains no actual rows")
    actual["settlement_period"] = pd.to_numeric(actual["SETTLEMENT_PERIOD"], errors="raise").astype(int)
    actual["settlement_date_local"] = pd.to_datetime(actual["SETTLEMENT_DATE"], errors="raise").dt.date.astype(str)

    pairs = actual[["settlement_date_local", "settlement_period"]].drop_duplicates()
    lookup = {
        (d, int(sp)): canonical_period_end_utc(d, int(sp))
        for d, sp in pairs.itertuples(index=False, name=None)
    }
    target_end = [lookup[(d, int(sp))] for d, sp in actual[["settlement_date_local", "settlement_period"]].itertuples(index=False, name=None)]

    out = pd.DataFrame({
        "target_end_utc": pd.DatetimeIndex(target_end),
        "target_start_utc": pd.DatetimeIndex(target_end) - pd.Timedelta(minutes=30),
        "settlement_date_local": actual["settlement_date_local"].to_numpy(),
        "settlement_period": actual["settlement_period"].to_numpy(),
        "actual_wind_mw": pd.to_numeric(actual["EMBEDDED_WIND_GENERATION"], errors="coerce").to_numpy(float),
        "actual_solar_mw": pd.to_numeric(actual["EMBEDDED_SOLAR_GENERATION"], errors="coerce").to_numpy(float),
    })
    if out.duplicated(["target_end_utc"]).any():
        raise ValueError("duplicate actual outturn target_end_utc")
    return out.sort_values("target_end_utc").reset_index(drop=True)


def select_latest_asof(forecasts: pd.DataFrame, *, horizon_periods: int) -> pd.DataFrame:
    required = {"target_end_utc", "publish_time_utc", "wind_mw", "solar_mw"}
    missing = required.difference(forecasts.columns)
    if missing:
        raise ValueError(f"forecast frame missing: {sorted(missing)}")
    h = int(horizon_periods)
    cutoff_minutes = (h + 1) * 30
    f = forecasts.copy()
    f["target_end_utc"] = pd.to_datetime(f["target_end_utc"], utc=True, errors="raise")
    f["publish_time_utc"] = pd.to_datetime(f["publish_time_utc"], utc=True, errors="raise")
    f["decision_time_utc"] = f["target_end_utc"] - pd.to_timedelta(cutoff_minutes, unit="m")
    eligible = f[f["publish_time_utc"] <= f["decision_time_utc"]].copy()
    if eligible.empty:
        return eligible
    idx = eligible.groupby("target_end_utc")["publish_time_utc"].idxmax()
    out = eligible.loc[idx].sort_values("target_end_utc").reset_index(drop=True)
    if (out["publish_time_utc"] > out["decision_time_utc"]).any():
        raise AssertionError("future forecast publication selected")
    return out


def metric_row(y: pd.Series, pred: pd.Series) -> dict:
    a = pd.to_numeric(y, errors="coerce").to_numpy(float)
    p = pd.to_numeric(pred, errors="coerce").to_numpy(float)
    mask = np.isfinite(a) & np.isfinite(p)
    if not mask.any():
        return {"n": 0, "mae": None, "rmse": None, "bias": None, "p95_abs_error": None}
    e = p[mask] - a[mask]
    ae = np.abs(e)
    return {
        "n": int(mask.sum()),
        "mae": float(ae.mean()),
        "rmse": float(np.sqrt(np.mean(e ** 2))),
        "bias": float(e.mean()),
        "p95_abs_error": float(np.quantile(ae, 0.95)),
    }


def benchmark_asof_forecasts(
    forecasts: pd.DataFrame,
    outturn: pd.DataFrame,
    *,
    horizon_periods: int,
) -> dict:
    selected = select_latest_asof(forecasts, horizon_periods=horizon_periods)
    actual = outturn.copy()
    actual["target_end_utc"] = pd.to_datetime(actual["target_end_utc"], utc=True, errors="raise")
    merged = actual.merge(
        selected[["target_end_utc", "publish_time_utc", "decision_time_utc", "wind_mw", "solar_mw"]],
        on="target_end_utc",
        how="left",
    )
    n_total = len(merged)
    n_selected = int(merged["publish_time_utc"].notna().sum())
    return {
        "horizon_periods": int(horizon_periods),
        "cutoff_minutes_to_target_end": (int(horizon_periods) + 1) * 30,
        "n_targets": int(n_total),
        "n_with_asof_forecast": n_selected,
        "coverage": float(n_selected / n_total) if n_total else 0.0,
        "future_publications": int((merged["publish_time_utc"].notna() & (merged["publish_time_utc"] > merged["decision_time_utc"])).sum()),
        "wind": metric_row(merged["actual_wind_mw"], merged["wind_mw"]),
        "solar": metric_row(merged["actual_solar_mw"], merged["solar_mw"]),
    }
