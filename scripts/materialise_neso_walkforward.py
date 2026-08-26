#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from scripts.materialise_v18_parquet import materialise_forecast


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--legacy", required=True)
    ap.add_argument("--current", required=True)
    ap.add_argument("--out-dir", default="data/processed/v27_historical_neso")
    ap.add_argument("--manifest", default="reports/v27_historical_walkforward/neso_materialise_manifest.json")
    ap.add_argument("--chunksize", type=int, default=150000)
    args = ap.parse_args()

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    result = {
        "version": "0.27.0-historical-walkforward-1",
        "legacy": materialise_forecast(Path(args.legacy), out / "forecast_legacy.parquet", "legacy", args.chunksize),
        "current": materialise_forecast(Path(args.current), out / "forecast_current.parquet", "current", args.chunksize),
    }
    manifest = Path(args.manifest)
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
