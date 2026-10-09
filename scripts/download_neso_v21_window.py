#!/usr/bin/env python3
"""Download only the current NESO forecast rows needed for v0.21 shadow replay.

Unlike the v0.20 archive benchmark, prospective inference does not need the
legacy Jan--Jun archive. This downloader uses NESO's supported SQL DataStore API
to retrieve a bounded settlement-date window from the current forecast regime.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
from pathlib import Path

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

BASE = "https://api.neso.energy/api/3/action/datastore_search_sql"
RESOURCE_ID = "31861619-0b86-47ba-bac2-d008a760af54"
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def session() -> requests.Session:
    retry = Retry(
        total=6,
        connect=6,
        read=6,
        backoff_factor=1.5,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset(["GET"]),
        respect_retry_after_header=True,
    )
    s = requests.Session()
    s.mount("https://", HTTPAdapter(max_retries=retry, pool_connections=2, pool_maxsize=2))
    s.headers.update({"User-Agent": "gb-power-market-forecasting/0.21"})
    return s


def api(s: requests.Session, sql: str, timeout: int) -> dict:
    r = s.get(BASE, params={"sql": sql}, timeout=(20, timeout))
    r.raise_for_status()
    payload = r.json()
    if not payload.get("success"):
        raise RuntimeError("NESO datastore_search_sql request failed")
    return payload["result"]


def where_clause(start_date: str, end_date_exclusive: str) -> str:
    if not DATE_RE.fullmatch(start_date) or not DATE_RE.fullmatch(end_date_exclusive):
        raise ValueError("dates must use YYYY-MM-DD")
    if end_date_exclusive <= start_date:
        raise ValueError("end date must be after start date")
    return (
        f'"SETTLEMENT_DATE" >= \'{start_date}\' '
        f'AND "SETTLEMENT_DATE" < \'{end_date_exclusive}\''
    )


def count_rows(s: requests.Session, where: str, timeout: int) -> int:
    result = api(s, f'SELECT count(*) AS "n" FROM "{RESOURCE_ID}" WHERE {where}', timeout)
    rows = result.get("records", [])
    if len(rows) != 1:
        raise RuntimeError("unexpected NESO SQL count response")
    return int(rows[0]["n"])


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start-date", default="2026-08-14")
    ap.add_argument("--end-date-exclusive", required=True)
    ap.add_argument("--out", default="data/external/v21/neso_current_window.csv")
    ap.add_argument("--manifest", default="reports/v21_shadow/neso_window_manifest.json")
    ap.add_argument("--page-size", type=int, default=32000)
    ap.add_argument("--timeout", type=int, default=180)
    args = ap.parse_args()
    if args.page_size <= 0 or args.page_size > 100000:
        raise ValueError("page-size must be in 1..100000")

    where = where_clause(args.start_date, args.end_date_exclusive)
    s = session()
    before = count_rows(s, where, args.timeout)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    part = out.with_suffix(out.suffix + ".part")
    part.unlink(missing_ok=True)

    fields: list[str] | None = None
    written = 0
    with part.open("w", newline="", encoding="utf-8") as f:
        writer = None
        offset = 0
        while True:
            sql = (
                f'SELECT * FROM "{RESOURCE_ID}" WHERE {where} '
                f'ORDER BY "_id" LIMIT {int(args.page_size)} OFFSET {offset}'
            )
            result = api(s, sql, args.timeout)
            rows = result.get("records", [])
            if not rows:
                break
            if fields is None:
                fields = [str(x["id"]) for x in result.get("fields", [])]
                if not fields:
                    fields = list(rows[0].keys())
                writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
                writer.writeheader()
            assert writer is not None
            writer.writerows(rows)
            written += len(rows)
            offset += len(rows)
            print(f"NESO current window: {written:,} rows", flush=True)
            if len(rows) < args.page_size:
                break

    if fields is None:
        raise RuntimeError("NESO current-window query returned zero rows")
    os.replace(part, out)
    after = count_rows(s, where, args.timeout)
    if after < before or not (before <= written <= after):
        raise RuntimeError(
            f"live SQL snapshot gate failed: before={before}, written={written}, after={after}"
        )

    manifest = {
        "version": "0.21.0",
        "source": "NESO current embedded wind/solar forecast resource",
        "resource_id": RESOURCE_ID,
        "start_settlement_date": args.start_date,
        "end_settlement_date_exclusive": args.end_date_exclusive,
        "rows_before": before,
        "rows_downloaded": written,
        "rows_after": after,
        "snapshot_consistent": True,
        "sha256": sha256(out),
        "path": str(out),
        "query_boundary": "bounded current-regime settlement-date window; no legacy archive downloaded",
    }
    mp = Path(args.manifest)
    mp.parent.mkdir(parents=True, exist_ok=True)
    mp.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(mp)


if __name__ == "__main__":
    main()
