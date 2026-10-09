#!/usr/bin/env python3
from __future__ import annotations

import argparse
import shutil
import zipfile
from pathlib import Path

from gb_power_market.evidence_v20 import build_evidence_bundle


def safe_extract(zip_path: Path, dest: Path) -> None:
    dest = dest.resolve()
    dest.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as z:
        for member in z.infolist():
            target = (dest / member.filename).resolve()
            if target != dest and dest not in target.parents:
                raise ValueError(f"unsafe artifact member: {member.filename}")
        z.extractall(dest)


def locate_report_dir(root: Path) -> Path:
    candidates = [p for p in root.rglob("v19_real_market") if p.is_dir() and p.parent.name == "reports"]
    if len(candidates) != 1:
        raise RuntimeError(f"expected exactly one reports/v19_real_market directory, found {len(candidates)}")
    return candidates[0]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("artifact_zip")
    ap.add_argument("--work-dir", default="_v20_artifact_ingest")
    ap.add_argument("--out-dir", default="reports/v20_ingested_evidence")
    args = ap.parse_args()
    z = Path(args.artifact_zip).resolve()
    work = Path(args.work_dir).resolve()
    if work.exists():
        shutil.rmtree(work)
    safe_extract(z, work)
    report = locate_report_dir(work)
    # The extracted artifact is treated as the evidence root so hashes refer to
    # exactly what was downloaded from GitHub Actions.
    out = Path(args.out_dir).resolve()
    build_evidence_bundle(work, report, out)
    print(f"evidence written to {out}")


if __name__ == "__main__":
    main()
