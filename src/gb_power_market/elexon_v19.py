from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import date, timedelta
from pathlib import Path
import hashlib
import json
import math

import numpy as np
import pandas as pd

from .neso_embedded import canonical_period_end_utc

ELEXON_BASE = "https://data.elexon.co.uk/bmrs/api/v1"
MID_PATH = "/balancing/pricing/market-index"
SYSTEM_PRICE_PATH = "/balancing/settlement/system-prices/{settlement_date}"
ALLOWED_MIDP = {"APXMIDP", "N2EXMIDP"}


@dataclass(frozen=True)
class ElexonCoverageGate:
    minimum_expected_coverage: float = 0.95
    maximum_duplicate_rows: int = 0
    maximum_clock_error_seconds: float = 1.0


def expected_settlement_keys(start_date: str | date, end_date_exclusive: str | date) -> pd.DataFrame:
    start = pd.Timestamp(start_date).date()
    end = pd.Timestamp(end_date_exclusive).date()
    rows: list[dict] = []
    d = start
    while d < end:
        # 46/48/50 periods are derived by the Europe/London settlement clock.
        sp = 1
        while True:
            try:
                target_end = canonical_period_end_utc(d, sp)
            except ValueError:
                break
            rows.append({
                "settlement_date": d.isoformat(),
                "settlement_period": sp,
                "target_end_utc": target_end,
                "target_start_utc": target_end - pd.Timedelta(minutes=30),
            })
            sp += 1
        d += timedelta(days=1)
    return pd.DataFrame(rows)


def _rows(payload: dict | list[dict] | pd.DataFrame) -> pd.DataFrame:
    if isinstance(payload, pd.DataFrame):
        return payload.copy()
    if isinstance(payload, dict):
        if "data" in payload:
            return pd.DataFrame(payload["data"])
        # Some endpoints return a single settlement-period object.
        if "settlementDate" in payload and "settlementPeriod" in payload:
            return pd.DataFrame([payload])
    return pd.DataFrame(payload)


def _settlement_clock_error_seconds(df: pd.DataFrame, start_col: str = "target_start_utc") -> np.ndarray:
    canonical = pd.DatetimeIndex([
        canonical_period_end_utc(d, int(sp)) - pd.Timedelta(minutes=30)
        for d, sp in df[["settlement_date", "settlement_period"]].itertuples(index=False, name=None)
    ])
    observed = pd.to_datetime(df[start_col], utc=True, errors="raise")
    return np.abs((observed - canonical).dt.total_seconds().to_numpy(float))


def normalise_mid(payload: dict | list[dict] | pd.DataFrame, *, clock_tolerance_seconds: float = 1.0) -> pd.DataFrame:
    raw = _rows(payload)
    required = {"startTime", "dataProvider", "settlementDate", "settlementPeriod", "price", "volume"}
    missing = required.difference(raw.columns)
    if missing:
        raise ValueError(f"MID payload missing fields: {sorted(missing)}")
    if raw.empty:
        return pd.DataFrame(columns=[
            "target_start_utc", "target_end_utc", "settlement_date", "settlement_period",
            "data_provider", "market_index_price_gbp_mwh", "market_index_volume_mwh",
            "clock_error_seconds",
        ])
    out = pd.DataFrame({
        "target_start_utc": pd.to_datetime(raw["startTime"], utc=True, errors="raise"),
        "settlement_date": pd.to_datetime(raw["settlementDate"], errors="raise").dt.date.astype(str),
        "settlement_period": pd.to_numeric(raw["settlementPeriod"], errors="raise").astype(int),
        "data_provider": raw["dataProvider"].astype(str),
        "market_index_price_gbp_mwh": pd.to_numeric(raw["price"], errors="raise").astype(float),
        "market_index_volume_mwh": pd.to_numeric(raw["volume"], errors="raise").astype(float),
    })
    if (~out["data_provider"].isin(ALLOWED_MIDP)).any():
        bad = sorted(set(out.loc[~out["data_provider"].isin(ALLOWED_MIDP), "data_provider"]))
        raise ValueError(f"unexpected MID provider(s): {bad}")
    if out.duplicated(["settlement_date", "settlement_period", "data_provider"]).any():
        raise ValueError("duplicate MID settlement/provider rows")
    if not np.isfinite(out["market_index_price_gbp_mwh"].to_numpy(float)).all():
        raise ValueError("non-finite MID price")
    if (out["market_index_volume_mwh"] < 0).any():
        raise ValueError("negative MID volume")
    err = _settlement_clock_error_seconds(out)
    out["clock_error_seconds"] = err
    if len(err) and float(np.nanmax(err)) > float(clock_tolerance_seconds):
        raise ValueError(f"MID settlement clock mismatch: max={float(np.nanmax(err)):.1f}s")
    out["target_end_utc"] = out["target_start_utc"] + pd.Timedelta(minutes=30)
    return out.sort_values(["target_start_utc", "data_provider"]).reset_index(drop=True)


def normalise_system_prices(payload: dict | list[dict] | pd.DataFrame, *, clock_tolerance_seconds: float = 1.0) -> pd.DataFrame:
    raw = _rows(payload)
    if raw.empty:
        return pd.DataFrame(columns=[
            "target_start_utc", "target_end_utc", "settlement_date", "settlement_period",
            "system_buy_price_gbp_mwh", "system_sell_price_gbp_mwh", "net_imbalance_volume_mwh",
            "clock_error_seconds",
        ])
    required = {"startTime", "settlementDate", "settlementPeriod"}
    missing = required.difference(raw.columns)
    if missing:
        raise ValueError(f"system-price payload missing fields: {sorted(missing)}")
    buy = next((c for c in ("systemBuyPrice", "system_buy_price", "price") if c in raw.columns), None)
    sell = next((c for c in ("systemSellPrice", "system_sell_price", "price") if c in raw.columns), None)
    if buy is None or sell is None:
        raise ValueError("system-price payload has no recognised price fields")
    niv = next((c for c in ("netImbalanceVolume", "net_imbalance_volume", "niv") if c in raw.columns), None)
    out = pd.DataFrame({
        "target_start_utc": pd.to_datetime(raw["startTime"], utc=True, errors="raise"),
        "settlement_date": pd.to_datetime(raw["settlementDate"], errors="raise").dt.date.astype(str),
        "settlement_period": pd.to_numeric(raw["settlementPeriod"], errors="raise").astype(int),
        "system_buy_price_gbp_mwh": pd.to_numeric(raw[buy], errors="raise").astype(float),
        "system_sell_price_gbp_mwh": pd.to_numeric(raw[sell], errors="raise").astype(float),
        "net_imbalance_volume_mwh": (
            pd.to_numeric(raw[niv], errors="coerce").astype(float) if niv else np.nan
        ),
    })
    if out.duplicated(["settlement_date", "settlement_period"]).any():
        raise ValueError("duplicate system-price settlement rows")
    err = _settlement_clock_error_seconds(out)
    out["clock_error_seconds"] = err
    if len(err) and float(np.nanmax(err)) > float(clock_tolerance_seconds):
        raise ValueError(f"system-price settlement clock mismatch: max={float(np.nanmax(err)):.1f}s")
    out["target_end_utc"] = out["target_start_utc"] + pd.Timedelta(minutes=30)
    return out.sort_values("target_start_utc").reset_index(drop=True)


def build_volume_weighted_market_reference(mid: pd.DataFrame) -> pd.DataFrame:
    required = {
        "target_start_utc", "target_end_utc", "settlement_date", "settlement_period",
        "data_provider", "market_index_price_gbp_mwh", "market_index_volume_mwh",
    }
    missing = required.difference(mid.columns)
    if missing:
        raise ValueError(f"normalised MID missing fields: {sorted(missing)}")
    rows: list[dict] = []
    for key, g in mid.groupby(["target_start_utc", "target_end_utc", "settlement_date", "settlement_period"], sort=True):
        p = g["market_index_price_gbp_mwh"].to_numpy(float)
        v = g["market_index_volume_mwh"].to_numpy(float)
        if v.sum() > 0:
            ref = float(np.average(p, weights=v))
        else:
            ref = float(np.mean(p))
        rows.append({
            "target_start_utc": key[0],
            "target_end_utc": key[1],
            "settlement_date": key[2],
            "settlement_period": int(key[3]),
            "reference_market_price_gbp_mwh": ref,
            "reference_market_volume_mwh": float(v.sum()),
            "n_midp": int(len(g)),
            "has_apx": bool((g["data_provider"] == "APXMIDP").any()),
            "has_n2ex": bool((g["data_provider"] == "N2EXMIDP").any()),
        })
    return pd.DataFrame(rows).sort_values("target_start_utc").reset_index(drop=True)


def audit_elexon_bundle(
    *,
    reference: pd.DataFrame,
    system_prices: pd.DataFrame,
    start_date: str,
    end_date_exclusive: str,
    gate: ElexonCoverageGate = ElexonCoverageGate(),
) -> dict:
    expected = expected_settlement_keys(start_date, end_date_exclusive)
    ref = expected.merge(
        reference[["settlement_date", "settlement_period", "reference_market_price_gbp_mwh", "n_midp"]],
        on=["settlement_date", "settlement_period"], how="left",
    )
    sys = expected.merge(
        system_prices[["settlement_date", "settlement_period", "system_buy_price_gbp_mwh", "system_sell_price_gbp_mwh"]],
        on=["settlement_date", "settlement_period"], how="left",
    )
    n = len(expected)
    ref_cov = float(ref["reference_market_price_gbp_mwh"].notna().mean()) if n else 0.0
    sys_cov = float((sys["system_buy_price_gbp_mwh"].notna() & sys["system_sell_price_gbp_mwh"].notna()).mean()) if n else 0.0
    joint = expected.merge(
        reference[["settlement_date", "settlement_period", "reference_market_price_gbp_mwh"]],
        on=["settlement_date", "settlement_period"], how="left",
    ).merge(
        system_prices[["settlement_date", "settlement_period", "system_buy_price_gbp_mwh"]],
        on=["settlement_date", "settlement_period"], how="left",
    )
    joint_cov = float((joint["reference_market_price_gbp_mwh"].notna() & joint["system_buy_price_gbp_mwh"].notna()).mean()) if n else 0.0
    dup_ref = int(reference.duplicated(["settlement_date", "settlement_period"]).sum())
    dup_sys = int(system_prices.duplicated(["settlement_date", "settlement_period"]).sum())
    passed = (
        ref_cov >= gate.minimum_expected_coverage
        and sys_cov >= gate.minimum_expected_coverage
        and joint_cov >= gate.minimum_expected_coverage
        and dup_ref <= gate.maximum_duplicate_rows
        and dup_sys <= gate.maximum_duplicate_rows
    )
    return {
        "status": "PASS_REAL" if passed else "BLOCKED",
        "expected_settlement_periods": int(n),
        "reference_market_coverage": ref_cov,
        "system_price_coverage": sys_cov,
        "joint_price_coverage": joint_cov,
        "duplicate_reference_rows": dup_ref,
        "duplicate_system_price_rows": dup_sys,
        "gate": asdict(gate),
        "claim": (
            "timestamp-aligned historical market/system price analysis enabled"
            if passed else "real market-aware numerical claims blocked"
        ),
    }


def sha256(path: str | Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def dump_json(path: str | Path, payload: dict) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")


def build_information_safe_market_frame(
    reference: pd.DataFrame,
    *,
    horizon_minutes: int,
    price_col: str = "reference_market_price_gbp_mwh",
) -> pd.DataFrame:
    """Build price lags on the GB settlement clock, including DST-safe seasonal baselines.

    `price_lag_1d_same_target` means previous *settlement date* and the same
    settlement-period number. It is deliberately not implemented as shift(48).
    Rolling and last-completed lags remain UTC elapsed-time lags because those
    answer what was actually observable at a given decision timestamp.
    """
    if horizon_minutes <= 0 or horizon_minutes % 30:
        raise ValueError("horizon_minutes must be a positive multiple of 30")
    required = {"target_start_utc", "settlement_date", "settlement_period", price_col}
    missing = required.difference(reference.columns)
    if missing:
        raise ValueError(f"reference market frame missing fields: {sorted(missing)}")
    df = reference[["target_start_utc", "settlement_date", "settlement_period", price_col]].copy()
    df["target_start_utc"] = pd.to_datetime(df["target_start_utc"], utc=True, errors="raise")
    df["settlement_date"] = pd.to_datetime(df["settlement_date"], errors="raise").dt.date.astype(str)
    df["settlement_period"] = pd.to_numeric(df["settlement_period"], errors="raise").astype(int)
    df[price_col] = pd.to_numeric(df[price_col], errors="raise").astype(float)
    df = df.sort_values("target_start_utc").reset_index(drop=True)
    if df.duplicated(["settlement_date", "settlement_period"]).any():
        raise ValueError("duplicate settlement keys in reference market frame")
    if len(df) >= 2 and not (df["target_start_utc"].diff().dropna() == pd.Timedelta(minutes=30)).all():
        raise ValueError("reference market price must be a complete 30-minute UTC grid")

    h = horizon_minutes // 30
    safe_shift = h + 1
    df["decision_time_utc"] = df["target_start_utc"] - pd.to_timedelta(horizon_minutes, unit="m")
    df["price_lag_last_completed"] = df[price_col].shift(safe_shift)
    df["price_lag_2_completed"] = df[price_col].shift(safe_shift + 1)
    shifted = df[price_col].shift(safe_shift)
    df["price_roll_3h_mean"] = shifted.rolling(6, min_periods=6).mean()
    df["price_roll_24h_median"] = shifted.rolling(48, min_periods=48).median()
    df["price_lag_24h_utc"] = df[price_col].shift(48)

    lookup = df[["settlement_date", "settlement_period", price_col]].rename(columns={price_col: "lookup_price"})
    for days, out_col in ((1, "price_lag_1d_same_target"), (7, "price_lag_7d_same_target")):
        key = df[["settlement_date", "settlement_period"]].copy()
        key["settlement_date"] = (
            pd.to_datetime(key["settlement_date"], errors="raise") - pd.Timedelta(days=days)
        ).dt.date.astype(str)
        keyed = key.merge(lookup, on=["settlement_date", "settlement_period"], how="left")
        df[out_col] = keyed["lookup_price"].to_numpy(float)

    local = df["target_start_utc"].dt.tz_convert("Europe/London")
    hour = local.dt.hour + local.dt.minute / 60.0
    dow = local.dt.dayofweek.astype(float)
    df["hour_sin"] = np.sin(2 * np.pi * hour / 24.0)
    df["hour_cos"] = np.cos(2 * np.pi * hour / 24.0)
    df["dow_sin"] = np.sin(2 * np.pi * dow / 7.0)
    df["dow_cos"] = np.cos(2 * np.pi * dow / 7.0)
    df["local_market_time"] = local.astype(str)
    df["horizon_minutes"] = int(horizon_minutes)
    df["safe_price_shift_periods"] = int(safe_shift)
    return df
