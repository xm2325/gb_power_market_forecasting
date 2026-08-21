from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

LEGACY_2026_RESOURCE_ID = "d6375700-69c2-4c25-8bde-883a205d742e"
CURRENT_2026_RESOURCE_ID = "31861619-0b86-47ba-bac2-d008a760af54"
GB_TZ = ZoneInfo("Europe/London")


@dataclass(frozen=True)
class NesoFeatureGate:
    minimum_rows: int = 500
    minimum_coverage: float = 0.80
    future_publications_allowed: int = 0


def settlement_period_ends_utc(settlement_date: str | date) -> pd.DatetimeIndex:
    """Return canonical UTC period-end timestamps for one GB settlement day.

    The number of periods is 46, 48 or 50 depending on the Europe/London DST
    transition. This avoids hand-coded DST exceptions.
    """
    d = pd.Timestamp(settlement_date).date()
    start_local = pd.Timestamp(datetime.combine(d, datetime.min.time()), tz=GB_TZ)
    end_local = pd.Timestamp(datetime.combine(d + timedelta(days=1), datetime.min.time()), tz=GB_TZ)
    start_utc = start_local.tz_convert("UTC")
    end_utc = end_local.tz_convert("UTC")
    # Edges include local midnight at both ends. Drop the first edge so output
    # index i is the end of settlement period i+1.
    return pd.date_range(start_utc, end_utc, freq="30min", inclusive="right")


def canonical_period_end_utc(settlement_date: str | date, settlement_period: int) -> pd.Timestamp:
    ends = settlement_period_ends_utc(settlement_date)
    sp = int(settlement_period)
    if sp < 1 or sp > len(ends):
        raise ValueError(
            f"settlement period {sp} invalid for {settlement_date}; day has {len(ends)} periods"
        )
    return ends[sp - 1]


def _rows(payload: dict | list[dict] | pd.DataFrame) -> pd.DataFrame:
    if isinstance(payload, pd.DataFrame):
        return payload.copy()
    if isinstance(payload, dict):
        if "result" in payload and isinstance(payload["result"], dict):
            return pd.DataFrame(payload["result"].get("records", []))
        if "records" in payload:
            return pd.DataFrame(payload["records"])
        if "data" in payload:
            return pd.DataFrame(payload["data"])
    return pd.DataFrame(payload)


def normalise_neso_embedded_archive(
    payload: dict | list[dict] | pd.DataFrame,
    *,
    source_regime: str,
    current_clock_tolerance_seconds: float = 1.0,
) -> pd.DataFrame:
    """Normalise one official NESO 2026 embedded forecast archive resource.

    `legacy_2026_jan_jun` reconstructs the target period end from GB settlement
    date/period because the legacy resource's raw DATE_GMT field does not carry
    the same target-time semantics as the current resource.

    `current_2026_jun_dec` treats DATE_GMT as target period end only after a
    DST-safe cross-check against the settlement period clock.
    """
    if source_regime not in {"legacy_2026_jan_jun", "current_2026_jun_dec"}:
        raise ValueError("unknown source_regime")
    df = _rows(payload)
    required = {
        "DATE_GMT", "SETTLEMENT_DATE", "SETTLEMENT_PERIOD",
        "EMBEDDED_WIND_FORECAST", "EMBEDDED_WIND_CAPACITY",
        "EMBEDDED_SOLAR_FORECAST", "EMBEDDED_SOLAR_CAPACITY", "Forecast_Datetime",
    }
    missing = required.difference(df.columns)
    if missing:
        raise ValueError(f"NESO archive missing fields: {sorted(missing)}")
    if df.empty:
        return pd.DataFrame(columns=[
            "target_end_utc", "target_start_utc", "publish_time_utc",
            "settlement_date_local", "settlement_period",
            "embedded_wind_forecast_mw", "embedded_wind_capacity_mw",
            "embedded_solar_forecast_mw", "embedded_solar_capacity_mw",
            "source_regime", "target_clock_difference_seconds",
        ])

    sp = pd.to_numeric(df["SETTLEMENT_PERIOD"], errors="raise").astype(int)
    publish = pd.to_datetime(df["Forecast_Datetime"], utc=True, errors="raise")

    if source_regime == "legacy_2026_jan_jun":
        settlement_dates = pd.to_datetime(df["SETTLEMENT_DATE"], errors="raise").dt.date
        target_end = pd.DatetimeIndex([
            canonical_period_end_utc(d, p) for d, p in zip(settlement_dates, sp, strict=True)
        ])
        clock_diff = np.zeros(len(df), dtype=float)
    else:
        raw_target_end = pd.to_datetime(df["DATE_GMT"], utc=True, errors="raise")
        # Infer the local settlement date from the period *start*, not from raw
        # SETTLEMENT_DATE, whose representation changed with the new source.
        local_dates = (raw_target_end - pd.Timedelta(minutes=30)).dt.tz_convert(GB_TZ).dt.date
        canonical = pd.DatetimeIndex([
            canonical_period_end_utc(d, p) for d, p in zip(local_dates, sp, strict=True)
        ])
        clock_diff = np.abs((raw_target_end - canonical).dt.total_seconds().to_numpy(float))
        if np.nanmax(clock_diff) > current_clock_tolerance_seconds:
            raise ValueError(
                "current NESO DATE_GMT fails settlement-clock cross-check; "
                f"max difference {float(np.nanmax(clock_diff)):.1f}s"
            )
        settlement_dates = pd.Series(local_dates, index=df.index)
        target_end = pd.DatetimeIndex(raw_target_end)

    out = pd.DataFrame({
        "target_end_utc": target_end,
        "target_start_utc": target_end - pd.Timedelta(minutes=30),
        "publish_time_utc": publish,
        "settlement_date_local": [d.isoformat() for d in settlement_dates],
        "settlement_period": sp.to_numpy(),
        "embedded_wind_forecast_mw": pd.to_numeric(df["EMBEDDED_WIND_FORECAST"], errors="raise").astype(float),
        "embedded_wind_capacity_mw": pd.to_numeric(df["EMBEDDED_WIND_CAPACITY"], errors="raise").astype(float),
        "embedded_solar_forecast_mw": pd.to_numeric(df["EMBEDDED_SOLAR_FORECAST"], errors="raise").astype(float),
        "embedded_solar_capacity_mw": pd.to_numeric(df["EMBEDDED_SOLAR_CAPACITY"], errors="raise").astype(float),
        "source_regime": source_regime,
        "target_clock_difference_seconds": clock_diff,
    })
    if out.duplicated(["target_end_utc", "publish_time_utc"]).any():
        raise ValueError("duplicate NESO target/publish rows within resource")
    if (out["publish_time_utc"] > out["target_end_utc"] + pd.Timedelta(days=14)).any():
        raise ValueError("implausible forecast publication timestamp")
    return out.sort_values(["target_end_utc", "publish_time_utc"]).reset_index(drop=True)


def stitch_2026_regimes(legacy: pd.DataFrame, current: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Stitch the two 2026 resources using the observed start of current data.

    NESO recommends the Jun-Dec resource after its source-system move. We do not
    guess a hidden switch timestamp: the explicit transition key is the earliest
    target present in the supplied current resource. Legacy targets before that
    key are retained; current targets at/after it are retained.
    """
    if legacy.empty or current.empty:
        raise ValueError("both legacy and current regimes are required for stitching")
    current_start = pd.to_datetime(current["target_end_utc"], utc=True).min()
    left = legacy[pd.to_datetime(legacy["target_end_utc"], utc=True) < current_start].copy()
    right = current[pd.to_datetime(current["target_end_utc"], utc=True) >= current_start].copy()
    combined = pd.concat([left, right], ignore_index=True).sort_values(
        ["target_end_utc", "publish_time_utc"]
    ).reset_index(drop=True)
    if combined.duplicated(["target_end_utc", "publish_time_utc"]).any():
        raise ValueError("duplicate target/publish rows after regime stitch")
    manifest = {
        "policy": "legacy before first observed current target; current from that target onward",
        "current_first_target_end_utc": current_start.isoformat(),
        "legacy_rows_retained": int(len(left)),
        "current_rows_retained": int(len(right)),
        "claim": "resource transition is explicit; rows are not averaged across forecast systems",
    }
    return combined, manifest


def select_asof_physical_features(
    price_targets: pd.DataFrame,
    revisions: pd.DataFrame,
    *,
    target_start_col: str = "target_start_utc",
    decision_col: str = "decision_time_utc",
) -> pd.DataFrame:
    """Attach latest and previous NESO wind/solar vintages to price targets.

    The physical forecast target is the end of the same settlement half-hour,
    while the price target is keyed by its start. Only revisions published by
    the simulated decision time are eligible.
    """
    t = price_targets[[target_start_col, decision_col]].copy()
    t[target_start_col] = pd.to_datetime(t[target_start_col], utc=True, errors="raise")
    t[decision_col] = pd.to_datetime(t[decision_col], utc=True, errors="raise")
    t["target_end_utc"] = t[target_start_col] + pd.Timedelta(minutes=30)

    r = revisions.copy()
    r["target_end_utc"] = pd.to_datetime(r["target_end_utc"], utc=True, errors="raise")
    r["publish_time_utc"] = pd.to_datetime(r["publish_time_utc"], utc=True, errors="raise")
    if r.duplicated(["target_end_utc", "publish_time_utc"]).any():
        raise ValueError("duplicate NESO target/publish rows")

    cols = [
        "target_end_utc", "publish_time_utc", "embedded_wind_forecast_mw",
        "embedded_wind_capacity_mw", "embedded_solar_forecast_mw",
        "embedded_solar_capacity_mw", "source_regime",
    ]
    joined = t.merge(r[cols], on="target_end_utc", how="left")
    eligible = joined[
        joined["publish_time_utc"].notna()
        & (joined["publish_time_utc"] <= joined[decision_col])
    ].copy()

    rows: list[dict] = []
    for (target_start, decision, target_end), g in eligible.groupby(
        [target_start_col, decision_col, "target_end_utc"], sort=True
    ):
        g = g.sort_values("publish_time_utc")
        latest = g.iloc[-1]
        previous = g.iloc[-2] if len(g) >= 2 else None
        row = {
            target_start_col: target_start,
            decision_col: decision,
            "target_end_utc": target_end,
            "neso_publish_time_utc": latest["publish_time_utc"],
            "neso_previous_publish_time_utc": (
                previous["publish_time_utc"] if previous is not None else pd.NaT
            ),
            "neso_source_regime": latest["source_regime"],
            "neso_forecast_age_minutes": (
                (decision - latest["publish_time_utc"]).total_seconds() / 60.0
            ),
        }
        for base in ["embedded_wind", "embedded_solar"]:
            f = f"{base}_forecast_mw"
            c = f"{base}_capacity_mw"
            row[f"neso_{base}_forecast_mw"] = float(latest[f])
            row[f"neso_{base}_capacity_mw"] = float(latest[c])
            if previous is not None:
                prev = float(previous[f])
                cur = float(latest[f])
                row[f"neso_{base}_revision_delta_mw"] = cur - prev
                row[f"neso_{base}_abs_revision_delta_mw"] = abs(cur - prev)
            else:
                row[f"neso_{base}_revision_delta_mw"] = np.nan
                row[f"neso_{base}_abs_revision_delta_mw"] = np.nan
        rows.append(row)

    out = pd.DataFrame(rows)
    if out.empty:
        return t.assign(
            neso_publish_time_utc=pd.NaT,
            neso_previous_publish_time_utc=pd.NaT,
        )
    if (out["neso_publish_time_utc"] > out[decision_col]).any():
        raise AssertionError("future NESO publication selected")
    return out.sort_values(target_start_col).reset_index(drop=True)


def audit_neso_feature_coverage(
    price_targets: pd.DataFrame,
    selected: pd.DataFrame,
    *,
    gate: NesoFeatureGate = NesoFeatureGate(),
) -> dict:
    base = price_targets[["target_start_utc", "decision_time_utc"]].copy()
    sel = selected[["target_start_utc", "neso_publish_time_utc"]].copy()
    merged = base.merge(sel, on="target_start_utc", how="left")
    pub = pd.to_datetime(merged["neso_publish_time_utc"], utc=True, errors="coerce")
    dec = pd.to_datetime(merged["decision_time_utc"], utc=True, errors="raise")
    coverage = float(pub.notna().mean()) if len(merged) else 0.0
    n_future = int((pub.notna() & (pub > dec)).sum())
    status = "PASS" if (
        len(merged) >= gate.minimum_rows
        and coverage >= gate.minimum_coverage
        and n_future <= gate.future_publications_allowed
    ) else "BLOCKED"
    return {
        "status": status,
        "n_targets": int(len(merged)),
        "n_with_asof_neso": int(pub.notna().sum()),
        "coverage": coverage,
        "future_publications": n_future,
        "minimum_rows": gate.minimum_rows,
        "minimum_coverage": gate.minimum_coverage,
        "claim": (
            "NESO physical features eligible for controlled experiment"
            if status == "PASS"
            else "NESO feature-family result blocked"
        ),
    }


def build_current_asof_pair_sql(
    *,
    start_target_end_utc: str | pd.Timestamp,
    end_target_end_exclusive_utc: str | pd.Timestamp,
    horizon_periods: int,
    limit: int = 50000,
) -> str:
    """Build compact CKAN SQL returning latest + previous eligible vintages.

    Horizon periods are measured to target *start*. Because the official key is
    target period end, eligibility is Forecast_Datetime <= DATE_GMT -
    (horizon_periods + 1)*30 minutes.
    """
    h = int(horizon_periods)
    if h < 1:
        raise ValueError("horizon_periods must be >= 1")
    start = pd.Timestamp(start_target_end_utc)
    end = pd.Timestamp(end_target_end_exclusive_utc)
    if start.tzinfo is None:
        start = start.tz_localize("UTC")
    else:
        start = start.tz_convert("UTC")
    if end.tzinfo is None:
        end = end.tz_localize("UTC")
    else:
        end = end.tz_convert("UTC")
    if end <= start:
        raise ValueError("end must be after start")
    cutoff_minutes = (h + 1) * 30
    fmt = lambda x: x.strftime("%Y-%m-%d %H:%M:%S")
    return f'''WITH eligible AS (
    SELECT
        "DATE_GMT", "TIME_GMT", "SETTLEMENT_DATE", "SETTLEMENT_PERIOD",
        "EMBEDDED_SOLAR_FORECAST", "EMBEDDED_SOLAR_CAPACITY",
        "EMBEDDED_WIND_FORECAST", "EMBEDDED_WIND_CAPACITY", "Forecast_Datetime",
        ROW_NUMBER() OVER (
            PARTITION BY "DATE_GMT" ORDER BY "Forecast_Datetime" DESC
        ) AS vintage_rank
    FROM "{CURRENT_2026_RESOURCE_ID}"
    WHERE "DATE_GMT" >= TIMESTAMP '{fmt(start)}'
      AND "DATE_GMT" < TIMESTAMP '{fmt(end)}'
      AND "Forecast_Datetime" <= "DATE_GMT" - INTERVAL '{cutoff_minutes} minutes'
)
SELECT * FROM eligible
WHERE vintage_rank <= 2
ORDER BY "DATE_GMT", "Forecast_Datetime" DESC
LIMIT {int(limit)}'''
