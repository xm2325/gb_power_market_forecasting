#!/usr/bin/env python3
"""Download a reproducible NESO 2026 archive + outturn bundle.

The live Jun-Dec forecast archive and Historic Demand Data 2026 may grow while a
run is in flight. The manifest therefore records row totals immediately before
and after each download and blocks impossible snapshots rather than pretending
that a moving dataset is immutable.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import os
import shutil
import time
from dataclasses import dataclass
from pathlib import Path

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

BASE = "https://api.neso.energy"


@dataclass(frozen=True)
class Resource:
    name: str
    resource_id: str
    filename: str
    live: bool


RESOURCES = (
    Resource("forecast_legacy_2026_jan_jun", "d6375700-69c2-4c25-8bde-883a205d742e", "neso_embedded_archive_2026_jan_jun.csv", False),
    Resource("forecast_current_2026_jun_dec", "31861619-0b86-47ba-bac2-d008a760af54", "neso_embedded_archive_2026_jun_dec.csv", True),
    Resource("historic_demand_outturn_2026", "8a4a771c-3929-4e56-93ad-cdf13219dea5", "neso_historic_demand_2026.csv", True),
    Resource("demand_data_update", "177f6fa4-ae49-4182-81ea-0c6b35f26ca6", "neso_demand_data_update.csv", True),
)


def session() -> requests.Session:
    retry = Retry(total=6, connect=6, read=6, backoff_factor=1.5, status_forcelist=(429, 500, 502, 503, 504), allowed_methods=frozenset(["GET"]))
    adapter = HTTPAdapter(max_retries=retry, pool_connections=4, pool_maxsize=4)
    s = requests.Session()
    s.mount("https://", adapter)
    s.headers.update({"User-Agent": "gb-power-market-forecasting/0.20"})
    return s


def metadata_total(s: requests.Session, rid: str, timeout: int) -> int:
    r = s.get(f"{BASE}/api/3/action/datastore_search", params={"resource_id": rid, "limit": 0}, timeout=(20, timeout))
    r.raise_for_status()
    p = r.json()
    if not p.get("success"):
        raise RuntimeError("NESO CKAN metadata request failed")
    return int(p["result"]["total"])


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def count_rows(path: Path) -> int:
    with path.open("rb") as f:
        return max(0, sum(1 for _ in f) - 1)


def download_dump(s: requests.Session, rsrc: Resource, out: Path, timeout: int) -> dict:
    url = f"{BASE}/datastore/dump/{rsrc.resource_id}"
    part = out.with_suffix(out.suffix + ".part")
    part.unlink(missing_ok=True)
    with s.get(url, stream=True, timeout=(20, timeout), allow_redirects=True) as r:
        r.raise_for_status()
        with part.open("wb") as f:
            for block in r.iter_content(4 * 1024 * 1024):
                if block:
                    f.write(block)
    if part.stat().st_size == 0:
        raise RuntimeError("empty datastore dump")
    os.replace(part, out)
    return {"method": "datastore_dump", "url": url}


def paged_resume(s: requests.Session, rsrc: Resource, out: Path, page_size: int, sleep_s: float, timeout: int) -> dict:
    checkpoint = out.parent / ".checkpoints" / rsrc.name
    checkpoint.mkdir(parents=True, exist_ok=True)
    meta_path = checkpoint / "checkpoint.json"
    state = {"page_size": page_size, "completed": {}}
    if meta_path.exists():
        state = json.loads(meta_path.read_text())
        if int(state.get("page_size", page_size)) != page_size:
            raise RuntimeError("checkpoint page_size mismatch; remove checkpoint or keep same page size")

    url = f"{BASE}/api/3/action/datastore_search"
    total = metadata_total(s, rsrc.resource_id, timeout)
    fields: list[str] | None = None
    offset = 0
    while offset < total:
        key = str(offset)
        chunk = checkpoint / f"part_{offset:09d}.csv.gz"
        known = state["completed"].get(key)
        if known and chunk.exists() and int(known["rows"]) > 0:
            offset += int(known["rows"])
            continue
        resp = s.get(url, params={"resource_id": rsrc.resource_id, "limit": page_size, "offset": offset}, timeout=(20, timeout))
        resp.raise_for_status()
        payload = resp.json()
        if not payload.get("success"):
            raise RuntimeError(f"CKAN page failed at offset {offset}")
        result = payload["result"]
        rows = result.get("records", [])
        if fields is None:
            fields = [f["id"] for f in result.get("fields", [])]
        if not rows:
            raise RuntimeError(f"empty CKAN page before total at offset {offset}/{total}")
        with gzip.open(chunk, "wt", newline="", encoding="utf-8") as gz:
            writer = csv.DictWriter(gz, fieldnames=fields, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
        state["completed"][key] = {"rows": len(rows), "sha256": sha256(chunk)}
        meta_path.write_text(json.dumps(state, indent=2), encoding="utf-8")
        offset += len(rows)
        if sleep_s:
            time.sleep(sleep_s)

    tmp = out.with_suffix(out.suffix + ".part")
    tmp.unlink(missing_ok=True)
    ordered = sorted(checkpoint.glob("part_*.csv.gz"))
    if not ordered:
        raise RuntimeError("no checkpoint chunks to assemble")
    first = True
    with tmp.open("wt", newline="", encoding="utf-8") as dst:
        for chunk in ordered:
            with gzip.open(chunk, "rt", newline="", encoding="utf-8") as src:
                for line_no, line in enumerate(src):
                    if not first and line_no == 0:
                        continue
                    dst.write(line)
            first = False
    os.replace(tmp, out)
    return {"method": "ckan_paged_resume", "url": url, "checkpoint": str(checkpoint), "page_size": page_size}


def download_resource(s: requests.Session, rsrc: Resource, out: Path, *, mode: str, page_size: int, sleep_s: float, timeout: int) -> dict:
    before = metadata_total(s, rsrc.resource_id, timeout)
    method: dict
    if mode in {"auto", "dump"}:
        try:
            method = download_dump(s, rsrc, out, timeout)
        except Exception:
            if mode == "dump":
                raise
            method = paged_resume(s, rsrc, out, page_size, sleep_s, timeout)
    else:
        method = paged_resume(s, rsrc, out, page_size, sleep_s, timeout)
    rows = count_rows(out)
    after = metadata_total(s, rsrc.resource_id, timeout)
    if rsrc.live:
        snapshot_ok = before <= rows <= after
    else:
        snapshot_ok = before == rows == after
    if not snapshot_ok:
        raise RuntimeError(f"row-count snapshot gate failed for {rsrc.name}: before={before}, rows={rows}, after={after}, live={rsrc.live}")
    return {
        "resource": rsrc.name,
        "resource_id": rsrc.resource_id,
        "live": rsrc.live,
        "rows_before": before,
        "rows_downloaded": rows,
        "rows_after": after,
        "sha256": sha256(out),
        "bytes": out.stat().st_size,
        "path": str(out),
        **method,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=("auto", "dump", "paged"), default="auto")
    ap.add_argument("--out-dir", default="data/external/neso_2026_bundle")
    ap.add_argument("--manifest", default="reports/v19_real_market/neso_download_manifest.json")
    ap.add_argument("--page-size", type=int, default=32000)
    ap.add_argument("--sleep-seconds", type=float, default=0.05)
    ap.add_argument("--timeout", type=int, default=180)
    args = ap.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = Path(args.manifest)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    s = session()
    entries = []
    for rsrc in RESOURCES:
        out = out_dir / rsrc.filename
        print(f"Downloading {rsrc.name} -> {out}", flush=True)
        entry = download_resource(
            s,
            rsrc,
            out,
            mode=args.mode,
            page_size=args.page_size,
            sleep_s=args.sleep_seconds,
            timeout=args.timeout,
        )
        entries.append(entry)
        manifest_path.write_text(json.dumps({"version": "0.20.0", "source": "NESO", "resources": entries}, indent=2), encoding="utf-8")
        print(f"{rsrc.name}: {entry['rows_downloaded']:,} rows, {entry['bytes'] / (1024*1024):.1f} MiB", flush=True)

    manifest_path.write_text(json.dumps({"version": "0.20.0", "source": "NESO", "resources": entries}, indent=2), encoding="utf-8")
    print(manifest_path)


if __name__ == "__main__":
    main()
