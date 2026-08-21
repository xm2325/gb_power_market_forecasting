#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from materialise_v18_parquet import _writer, normalise_forecast_chunk


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", default="data/external/v21/neso_current_window.csv")
    ap.add_argument("--out", default="data/processed/v21/forecast_current.parquet")
    ap.add_argument("--manifest", default="reports/v21_shadow/neso_materialise_manifest.json")
    ap.add_argument("--chunksize", type=int, default=150000)
    args = ap.parse_args()

    src = Path(args.input)
    dst = Path(args.out)
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.unlink(missing_ok=True)
    writer = None
    rows = 0
    max_clock = 0.0
    mismatches = 0
    for chunk in pd.read_csv(src, chunksize=args.chunksize, low_memory=False):
        norm, clock = normalise_forecast_chunk(chunk, "current")
        writer = _writer(dst, norm, writer)
        rows += len(norm)
        max_clock = max(max_clock, float(clock))
        mismatches += int((norm["raw_clock_offset_seconds"].abs() > 1.0).sum())
        print(f"current prospective window: materialised {rows:,} rows", flush=True)
    if writer is not None:
        writer.close()
    if rows == 0:
        raise RuntimeError("no NESO current-window rows materialised")

    manifest = {
        "version": "0.21.0",
        "source": str(src),
        "parquet": str(dst),
        "rows": int(rows),
        "max_raw_clock_offset_seconds": float(max_clock),
        "raw_clock_mismatch_rows": int(mismatches),
        "target_key": "GB settlement date + settlement period",
    }
    mp = Path(args.manifest)
    mp.parent.mkdir(parents=True, exist_ok=True)
    mp.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(mp)


if __name__ == "__main__":
    main()
