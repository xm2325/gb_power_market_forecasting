#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from gb_power_market.elexon_v19 import build_volume_weighted_market_reference, normalise_mid


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bundle-dir", default="data/external/v22/elexon_mid")
    ap.add_argument("--out", default="data/processed/v22/reference_market.parquet")
    ap.add_argument("--manifest", default="reports/v22_confirmatory/elexon_mid_materialise_manifest.json")
    args = ap.parse_args()

    frames = []
    for path in sorted(Path(args.bundle_dir).glob("mid_*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        rows = payload.get("data", payload if isinstance(payload, list) else [])
        if rows:
            frames.append(normalise_mid(payload))
    if not frames:
        raise RuntimeError("no Elexon MID rows available")

    mid = pd.concat(frames, ignore_index=True)
    if mid.duplicated(["settlement_date", "settlement_period", "data_provider"]).any():
        raise RuntimeError("duplicate MID settlement/provider rows")
    reference = build_volume_weighted_market_reference(mid)
    if reference.empty:
        raise RuntimeError("empty Elexon market reference")
    reference = reference.sort_values("target_start_utc").reset_index(drop=True)
    gaps = pd.to_datetime(reference["target_start_utc"], utc=True).diff().dropna()
    if len(gaps) and not (gaps == pd.Timedelta(minutes=30)).all():
        raise RuntimeError("Elexon MID reference contains a settlement-grid gap")

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    reference.to_parquet(out, index=False, compression="zstd")
    manifest = {
        "version": "0.22.0",
        "rows": int(len(reference)),
        "first_target_start_utc": str(reference["target_start_utc"].min()),
        "last_target_start_utc": str(reference["target_start_utc"].max()),
        "has_apx_rows": int(reference["has_apx"].sum()),
        "has_n2ex_rows": int(reference["has_n2ex"].sum()),
        "grid": "contiguous 30-minute UTC over available MID reference rows",
        "output": str(out),
    }
    mp = Path(args.manifest)
    mp.parent.mkdir(parents=True, exist_ok=True)
    mp.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
