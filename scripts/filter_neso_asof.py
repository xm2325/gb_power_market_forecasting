#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--cutoff-utc", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--manifest", required=True)
    args = ap.parse_args()

    cutoff = pd.Timestamp(args.cutoff_utc)
    if cutoff.tzinfo is None:
        raise ValueError("NESO as-of cutoff must be timezone-aware")
    cutoff = cutoff.tz_convert("UTC")

    src = Path(args.input)
    out = Path(args.out)
    df = pd.read_parquet(src)
    publish = pd.to_datetime(df["publish_time_utc"], utc=True, errors="raise")
    keep = publish <= cutoff
    filtered = df.loc[keep].copy()
    if filtered.empty:
        raise RuntimeError("NESO as-of filter removed every row")
    filtered["publish_time_utc"] = pd.to_datetime(filtered["publish_time_utc"], utc=True)
    if (filtered["publish_time_utc"] > cutoff).any():
        raise AssertionError("post-cutoff NESO publication survived as-of filter")

    out.parent.mkdir(parents=True, exist_ok=True)
    filtered.to_parquet(out, index=False)
    manifest = {
        "schema": "gb-power-market-neso-asof-filter-v1",
        "source": str(src),
        "output": str(out),
        "cutoff_utc": cutoff.isoformat(),
        "source_rows": int(len(df)),
        "kept_rows": int(len(filtered)),
        "removed_post_cutoff_rows": int((~keep).sum()),
        "max_kept_publish_time_utc": pd.Timestamp(filtered["publish_time_utc"].max()).isoformat(),
        "contract": "Prediction input contains only NESO vintages published at or before the locked decision time.",
    }
    mp = Path(args.manifest)
    mp.parent.mkdir(parents=True, exist_ok=True)
    mp.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
