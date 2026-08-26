#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import timedelta
import json
from pathlib import Path
import time

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from gb_power_market.elexon_v19 import ELEXON_BASE, MID_PATH, sha256


def session() -> requests.Session:
    retry = Retry(
        total=8, connect=8, read=8, status=8, backoff_factor=1.5,
        status_forcelist=(408, 425, 429, 500, 502, 503, 504),
        allowed_methods=frozenset(["GET"]), respect_retry_after_header=True,
    )
    s = requests.Session()
    s.mount("https://", HTTPAdapter(max_retries=retry, pool_connections=4, pool_maxsize=4))
    s.headers.update({"User-Agent": "gb-power-market-forecasting/0.22"})
    return s


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start-date", required=True)
    ap.add_argument("--end-date-exclusive", required=True)
    ap.add_argument("--out-dir", default="data/external/v22/elexon_mid")
    ap.add_argument("--manifest", default="reports/v22_confirmatory/elexon_mid_manifest.json")
    ap.add_argument("--timeout", type=int, default=120)
    ap.add_argument("--sleep-seconds", type=float, default=0.05)
    args = ap.parse_args()

    import pandas as pd
    start = pd.Timestamp(args.start_date).date()
    end = pd.Timestamp(args.end_date_exclusive).date()
    if end <= start:
        raise ValueError("end-date-exclusive must be after start-date")

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    s = session()
    days = {}
    d = start
    while d < end:
        ds = d.isoformat()
        path = out / f"mid_{ds}.json"
        r = s.get(
            ELEXON_BASE + MID_PATH,
            params={
                "from": f"{ds}T00:00:00Z",
                "to": f"{ds}T00:00:00Z",
                "settlementPeriodFrom": 1,
                "settlementPeriodTo": 50,
                "format": "json",
            },
            timeout=(20, args.timeout),
        )
        r.raise_for_status()
        payload = r.json()
        tmp = path.with_suffix(".json.part")
        tmp.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
        tmp.replace(path)
        rows = payload.get("data", payload if isinstance(payload, list) else [])
        days[ds] = {"rows": int(len(rows)), "sha256": sha256(path), "path": str(path)}
        print(f"{ds}: MID rows={len(rows):,}", flush=True)
        d += timedelta(days=1)
        if d < end:
            time.sleep(args.sleep_seconds)

    manifest = {
        "version": "0.22.0",
        "source": "Elexon Insights API Market Index Data",
        "start_settlement_date": start.isoformat(),
        "end_settlement_date_exclusive": end.isoformat(),
        "days": days,
        "boundary": "MID only; system prices are not required for blinded confirmatory point-forecast replay",
    }
    mp = Path(args.manifest)
    mp.parent.mkdir(parents=True, exist_ok=True)
    mp.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(mp)


if __name__ == "__main__":
    main()
