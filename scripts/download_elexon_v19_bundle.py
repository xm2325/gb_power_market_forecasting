#!/usr/bin/env python3
"""Download Elexon Market Index Data and settlement system prices by settlement date.

The downloader deliberately uses small date-addressable checkpoints. A 429 or
transient server error therefore never forces the full Jan-Aug history to restart.
"""
from __future__ import annotations

import argparse
from datetime import timedelta
from pathlib import Path
import json
import time

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from gb_power_market.elexon_v19 import ELEXON_BASE, MID_PATH, SYSTEM_PRICE_PATH, sha256


def make_session() -> requests.Session:
    retry = Retry(
        total=8, connect=8, read=8, status=8,
        backoff_factor=1.5,
        status_forcelist=(408, 425, 429, 500, 502, 503, 504),
        allowed_methods=frozenset(["GET"]),
        respect_retry_after_header=True,
    )
    adapter = HTTPAdapter(max_retries=retry, pool_connections=4, pool_maxsize=4)
    s = requests.Session()
    s.mount("https://", adapter)
    s.headers.update({"User-Agent": "gb-power-market-forecasting/0.20"})
    return s


def fetch_json(s: requests.Session, url: str, *, params: dict | None, timeout: int) -> dict | list:
    r = s.get(url, params=params, timeout=(20, timeout))
    r.raise_for_status()
    return r.json()


def atomic_write_json(path: Path, payload: dict | list) -> None:
    tmp = path.with_suffix(path.suffix + ".part")
    tmp.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
    tmp.replace(path)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start-date", default="2026-01-01")
    ap.add_argument("--end-date-exclusive", default="2026-08-16")
    ap.add_argument("--out-dir", default="data/external/elexon_v19")
    ap.add_argument("--manifest", default="reports/v19_real_market/download_manifest.json")
    ap.add_argument("--timeout", type=int, default=120)
    ap.add_argument("--sleep-seconds", type=float, default=0.15)
    args = ap.parse_args()

    start = __import__("pandas").Timestamp(args.start_date).date()
    end = __import__("pandas").Timestamp(args.end_date_exclusive).date()
    if end <= start:
        raise ValueError("end-date-exclusive must be after start-date")

    out = Path(args.out_dir)
    mid_dir = out / "mid_daily"
    sys_dir = out / "system_price_daily"
    mid_dir.mkdir(parents=True, exist_ok=True)
    sys_dir.mkdir(parents=True, exist_ok=True)
    s = make_session()
    manifest = {
        "version": "0.20.0",
        "source": "Elexon Insights API",
        "base": ELEXON_BASE,
        "start_settlement_date": start.isoformat(),
        "end_settlement_date_exclusive": end.isoformat(),
        "days": {},
    }

    d = start
    while d < end:
        ds = d.isoformat()
        mid_path = mid_dir / f"mid_{ds}.json"
        sys_path = sys_dir / f"system_prices_{ds}.json"
        day = {"settlement_date": ds, "mid": {}, "system_prices": {}}

        if not mid_path.exists():
            payload = fetch_json(
                s,
                ELEXON_BASE + MID_PATH,
                params={
                    "from": f"{ds}T00:00:00Z",
                    "to": f"{ds}T00:00:00Z",
                    "settlementPeriodFrom": 1,
                    "settlementPeriodTo": 50,
                    "format": "json",
                },
                timeout=args.timeout,
            )
            atomic_write_json(mid_path, payload)
        mid_payload = json.loads(mid_path.read_text(encoding="utf-8"))
        mid_rows = len(mid_payload.get("data", mid_payload if isinstance(mid_payload, list) else []))
        day["mid"] = {"path": str(mid_path), "rows": int(mid_rows), "sha256": sha256(mid_path)}

        if not sys_path.exists():
            payload = fetch_json(
                s,
                ELEXON_BASE + SYSTEM_PRICE_PATH.format(settlement_date=ds),
                params={"format": "json"},
                timeout=args.timeout,
            )
            atomic_write_json(sys_path, payload)
        sys_payload = json.loads(sys_path.read_text(encoding="utf-8"))
        sys_rows = len(sys_payload.get("data", sys_payload if isinstance(sys_payload, list) else []))
        day["system_prices"] = {"path": str(sys_path), "rows": int(sys_rows), "sha256": sha256(sys_path)}
        manifest["days"][ds] = day
        print(f"{ds}: MID={mid_rows:,}, system={sys_rows:,}", flush=True)
        d += timedelta(days=1)
        if d < end:
            time.sleep(args.sleep_seconds)

    mp = Path(args.manifest)
    mp.parent.mkdir(parents=True, exist_ok=True)
    mp.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(mp)


if __name__ == "__main__":
    main()
