#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import timedelta
import json
from pathlib import Path
import time

import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from gb_power_market.elexon_v19 import ELEXON_BASE, MID_PATH, sha256


GRID = pd.Timedelta(minutes=30)


def session() -> requests.Session:
    retry = Retry(
        total=8,
        connect=8,
        read=8,
        status=8,
        backoff_factor=1.5,
        status_forcelist=(408, 425, 429, 500, 502, 503, 504),
        allowed_methods=frozenset(["GET"]),
        respect_retry_after_header=True,
    )
    s = requests.Session()
    s.mount("https://", HTTPAdapter(max_retries=retry, pool_connections=4, pool_maxsize=4))
    s.headers.update({"User-Agent": "gb-power-market-forecasting/0.26-v27-validation"})
    return s


def _utc(value: str) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    if ts.tzinfo is None:
        raise ValueError("exact Elexon boundary must be timezone-aware")
    return ts.tz_convert("UTC")


def chunk_windows(start: pd.Timestamp, end_exclusive: pd.Timestamp) -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    if end_exclusive <= start:
        raise ValueError("end-exclusive must be after start")
    if start.floor("30min") != start or end_exclusive.floor("30min") != end_exclusive:
        raise ValueError("exact Elexon boundaries must align to the 30-minute UTC grid")

    chunks: list[tuple[pd.Timestamp, pd.Timestamp]] = []
    cursor = start
    while cursor < end_exclusive:
        next_midnight = cursor.normalize() + pd.Timedelta(days=1)
        chunk_end = min(next_midnight, end_exclusive)
        chunks.append((cursor, chunk_end))
        cursor = chunk_end
    return chunks


def query_params(start: pd.Timestamp, end_exclusive: pd.Timestamp) -> dict[str, str]:
    if end_exclusive - start < GRID:
        raise ValueError("exact Elexon chunk must contain at least one half-hour")
    inclusive_to = end_exclusive - GRID
    return {
        "from": start.isoformat().replace("+00:00", "Z"),
        "to": inclusive_to.isoformat().replace("+00:00", "Z"),
        "format": "json",
    }


def validate_payload_window(payload: dict | list, *, start: pd.Timestamp, end_exclusive: pd.Timestamp) -> int:
    rows = payload.get("data", payload if isinstance(payload, list) else [])
    for row in rows:
        if "startTime" not in row:
            raise ValueError("Elexon MID exact-window row is missing startTime")
        ts = pd.Timestamp(row["startTime"])
        if ts.tzinfo is None:
            raise ValueError("Elexon MID startTime is not timezone-aware")
        ts = ts.tz_convert("UTC")
        if ts < start or ts >= end_exclusive:
            raise ValueError(
                f"Elexon MID response escaped sealed window: {ts.isoformat()} not in "
                f"[{start.isoformat()}, {end_exclusive.isoformat()})"
            )
    return int(len(rows))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start-utc", required=True)
    ap.add_argument("--end-exclusive-utc", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--timeout", type=int, default=120)
    ap.add_argument("--sleep-seconds", type=float, default=0.05)
    args = ap.parse_args()

    start = _utc(args.start_utc)
    end_exclusive = _utc(args.end_exclusive_utc)
    chunks = chunk_windows(start, end_exclusive)
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    s = session()
    manifest_chunks = []

    for i, (chunk_start, chunk_end) in enumerate(chunks):
        params = query_params(chunk_start, chunk_end)
        response = s.get(ELEXON_BASE + MID_PATH, params=params, timeout=(20, args.timeout))
        response.raise_for_status()
        payload = response.json()
        row_count = validate_payload_window(payload, start=chunk_start, end_exclusive=chunk_end)

        stamp = chunk_start.strftime("%Y%m%dT%H%MZ")
        path = out / f"mid_exact_{stamp}.json"
        tmp = path.with_suffix(".json.part")
        tmp.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
        tmp.replace(path)
        manifest_chunks.append(
            {
                "request_from_utc": params["from"],
                "request_to_inclusive_utc": params["to"],
                "sealed_end_exclusive_utc": chunk_end.isoformat().replace("+00:00", "Z"),
                "rows": row_count,
                "sha256": sha256(path),
                "path": str(path),
            }
        )
        print(f"{params['from']} -> {params['to']}: MID rows={row_count:,}", flush=True)
        if i + 1 < len(chunks):
            time.sleep(args.sleep_seconds)

    manifest = {
        "version": "0.27-development-validation",
        "source": "Elexon Insights API Market Index Data",
        "request_mode": "EXACT_START_TIME_NO_SETTLEMENT_PERIOD_FILTERS",
        "start_utc": start.isoformat().replace("+00:00", "Z"),
        "end_exclusive_utc": end_exclusive.isoformat().replace("+00:00", "Z"),
        "chunks": manifest_chunks,
        "boundary_contract": (
            "No settlementPeriodFrom/To parameters are sent, so Elexon from/to are start-time filters. "
            "The API 'to' parameter is inclusive; each request therefore stops one 30-minute grid step before "
            "the sealed end-exclusive boundary, and every returned startTime is checked before bytes are persisted."
        ),
    }
    mp = Path(args.manifest)
    mp.parent.mkdir(parents=True, exist_ok=True)
    mp.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(mp)


if __name__ == "__main__":
    main()
