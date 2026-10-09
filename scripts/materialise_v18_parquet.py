#!/usr/bin/env python3
"""Materialise large NESO CSV snapshots into compact, normalised Parquet files.

This is intentionally chunked so the 3M+ forecast-vintage archive does not need
one large pandas object in memory. PyArrow is imported lazily and is only needed
for the live GitHub run.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from gb_power_market.archive_v18 import canonical_period_end_utc, normalise_outturn_2026


def _writer(path: Path, df: pd.DataFrame, writer=None):
    import pyarrow as pa
    import pyarrow.parquet as pq
    table = pa.Table.from_pandas(df, preserve_index=False)
    if writer is None:
        writer = pq.ParquetWriter(path, table.schema, compression="zstd", use_dictionary=True)
    writer.write_table(table)
    return writer


def _clock_lookup(dates: pd.Series, sps: pd.Series) -> dict[tuple[str, int], pd.Timestamp]:
    pairs = pd.DataFrame({"d": dates.astype(str), "sp": pd.to_numeric(sps, errors="raise").astype(int)}).drop_duplicates()
    return {(d, int(sp)): canonical_period_end_utc(d, int(sp)) for d, sp in pairs.itertuples(index=False, name=None)}


def _wrapped_clock_offset_seconds(raw_target: pd.DatetimeIndex, canonical: pd.DatetimeIndex) -> np.ndarray:
    """Return the shortest signed clock offset on a 24-hour circle.

    Some legacy NESO rows published on 20--21 April 2026 label ``TIME_GMT``
    with the BST/local clock.  A midnight wrap therefore appears as 23 hours
    if compared naively.  The settlement-date/period key remains internally
    consistent, so we use it as the canonical target and retain this raw-clock
    offset only as an audit field.
    """
    delta = (pd.DatetimeIndex(raw_target) - pd.DatetimeIndex(canonical)).total_seconds().to_numpy(float)
    return ((delta + 43200.0) % 86400.0) - 43200.0


def normalise_forecast_chunk(raw: pd.DataFrame, regime: str) -> tuple[pd.DataFrame, float]:
    if regime not in {"legacy", "current"}:
        raise ValueError(regime)

    sp = pd.to_numeric(raw["SETTLEMENT_PERIOD"], errors="raise").astype(int)
    pub = pd.to_datetime(raw["Forecast_Datetime"], utc=True, errors="raise")
    local_date = pd.to_datetime(raw["SETTLEMENT_DATE"], errors="raise").dt.date.astype(str)

    # The GB settlement key is authoritative.  DATE_GMT/TIME_GMT is retained
    # as an independent source-clock cross-check because the legacy archive
    # contains a small, identifiable BST-labelled subset.
    lookup = _clock_lookup(pd.Series(local_date), sp)
    canonical = pd.DatetimeIndex([lookup[(d, int(p))] for d, p in zip(local_date, sp, strict=True)])
    raw_target = pd.to_datetime(
        raw["DATE_GMT"].astype(str).str.slice(0, 10) + " " + raw["TIME_GMT"].astype(str),
        utc=True,
        errors="raise",
    )
    offset = _wrapped_clock_offset_seconds(pd.DatetimeIndex(raw_target), canonical)
    max_diff = float(np.nanmax(np.abs(offset))) if len(offset) else 0.0

    # One hour is an explainable GMT/BST labelling offset. Anything larger is
    # not silently repaired.
    if max_diff > 3600.0 + 1.0:
        raise ValueError(f"{regime} settlement clock mismatch exceeds one hour: {max_diff}s")

    out = pd.DataFrame({
        "target_end_utc": canonical,
        "target_start_utc": canonical - pd.Timedelta(minutes=30),
        "publish_time_utc": pub,
        "settlement_date_local": np.asarray(local_date, dtype=str),
        "settlement_period": sp.to_numpy(np.int16),
        "raw_clock_offset_seconds": offset,
        "wind_mw": pd.to_numeric(raw["EMBEDDED_WIND_FORECAST"], errors="coerce").to_numpy(float),
        "wind_capacity_mw": pd.to_numeric(raw["EMBEDDED_WIND_CAPACITY"], errors="coerce").to_numpy(float),
        "solar_mw": pd.to_numeric(raw["EMBEDDED_SOLAR_FORECAST"], errors="coerce").to_numpy(float),
        "solar_capacity_mw": pd.to_numeric(raw["EMBEDDED_SOLAR_CAPACITY"], errors="coerce").to_numpy(float),
        "source_regime": regime,
    })
    return out, max_diff


def materialise_forecast(src: Path, dst: Path, regime: str, chunksize: int) -> dict:
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.unlink(missing_ok=True)
    writer = None
    rows = 0
    max_clock = 0.0
    raw_clock_mismatch_rows = 0
    for chunk in pd.read_csv(src, chunksize=chunksize, low_memory=False):
        norm, clock = normalise_forecast_chunk(chunk, regime)
        writer = _writer(dst, norm, writer)
        rows += len(norm)
        max_clock = max(max_clock, clock)
        raw_clock_mismatch_rows += int((norm["raw_clock_offset_seconds"].abs() > 1.0).sum())
        print(f"{regime}: materialised {rows:,} rows", flush=True)
    if writer is not None:
        writer.close()
    return {
        "source": str(src),
        "parquet": str(dst),
        "rows": rows,
        "target_key": "GB settlement date + settlement period",
        "max_raw_clock_offset_seconds": max_clock,
        "raw_clock_mismatch_rows": raw_clock_mismatch_rows,
        "raw_clock_mismatch_policy": "canonicalise by settlement key; allow <=1h GMT/BST label offset; fail above 1h",
    }


def materialise_outturn(src: Path, dst: Path, chunksize: int) -> dict:
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.unlink(missing_ok=True)
    writer = None
    rows = 0
    for chunk in pd.read_csv(src, chunksize=chunksize, low_memory=False):
        actual = chunk[chunk["FORECAST_ACTUAL_INDICATOR"].astype(str).str.upper().eq("A")].copy()
        if actual.empty:
            continue
        norm = normalise_outturn_2026(actual)
        writer = _writer(dst, norm, writer)
        rows += len(norm)
        print(f"outturn: materialised {rows:,} actual rows", flush=True)
    if writer is not None:
        writer.close()
    return {"source": str(src), "parquet": str(dst), "actual_rows": rows}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bundle-dir", default="data/external/neso_2026_bundle")
    ap.add_argument("--out-dir", default="data/processed/v18_neso")
    ap.add_argument("--chunksize", type=int, default=150000)
    ap.add_argument("--manifest", default="reports/v18_real_archive/materialise_manifest.json")
    args = ap.parse_args()
    b = Path(args.bundle_dir); o = Path(args.out_dir); o.mkdir(parents=True, exist_ok=True)
    result = {
        "version": "0.18.0",
        "legacy": materialise_forecast(b / "neso_embedded_archive_2026_jan_jun.csv", o / "forecast_legacy.parquet", "legacy", args.chunksize),
        "current": materialise_forecast(b / "neso_embedded_archive_2026_jun_dec.csv", o / "forecast_current.parquet", "current", args.chunksize),
        "outturn_historic": materialise_outturn(b / "neso_historic_demand_2026.csv", o / "outturn_historic_2026.parquet", args.chunksize),
        "outturn_update": materialise_outturn(b / "neso_demand_data_update.csv", o / "outturn_update.parquet", args.chunksize),
    }
    mp = Path(args.manifest); mp.parent.mkdir(parents=True, exist_ok=True); mp.write_text(json.dumps(result, indent=2))
    print(mp)

if __name__ == "__main__":
    main()
