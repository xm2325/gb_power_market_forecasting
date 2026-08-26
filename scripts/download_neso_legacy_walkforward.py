#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from download_neso_v18_bundle import RESOURCES, download_resource, session


RESOURCE_NAME = "forecast_legacy_2026_jan_jun"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data/external/v27_historical/neso_embedded_archive_2026_jan_jun.csv")
    ap.add_argument("--manifest", default="reports/v27_historical_walkforward/neso_legacy_download_manifest.json")
    ap.add_argument("--mode", choices=("auto", "dump", "paged"), default="auto")
    ap.add_argument("--page-size", type=int, default=32000)
    ap.add_argument("--sleep-seconds", type=float, default=0.05)
    ap.add_argument("--timeout", type=int, default=180)
    args = ap.parse_args()

    resource = next(r for r in RESOURCES if r.name == RESOURCE_NAME)
    if resource.live:
        raise RuntimeError("legacy walk-forward archive unexpectedly marked live")
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    entry = download_resource(
        session(),
        resource,
        out,
        mode=args.mode,
        page_size=args.page_size,
        sleep_s=args.sleep_seconds,
        timeout=args.timeout,
    )
    if not entry["snapshot_consistent"] or entry["rows_before"] != entry["rows_after"]:
        raise RuntimeError("immutable legacy NESO snapshot failed consistency gate")
    manifest = {
        "version": "0.27.0-historical-walkforward-1",
        "purpose": "legacy NESO vintages for leakage-safe rolling-origin historical evaluation",
        **entry,
    }
    path = Path(args.manifest)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
