#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


DEFAULT_LOCK = Path("reports/locked/V0_26_IMPLEMENTATION_LOCK.json")
PROVENANCE_SCHEMA = "gb-power-market-v26-execution-provenance-v1"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git_blob_sha1(path: Path) -> str:
    data = path.read_bytes()
    header = f"blob {len(data)}\0".encode("utf-8")
    return hashlib.sha1(header + data).hexdigest()


def build_provenance(*, lock_path: Path, execution_commit_sha: str, source_run_id: int) -> dict:
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    if lock.get("schema") != "gb-power-market-v26-implementation-lock-v1":
        raise ValueError("unsupported v0.26 implementation lock")
    if len(execution_commit_sha) != 40 or any(c not in "0123456789abcdef" for c in execution_commit_sha.lower()):
        raise ValueError("execution commit SHA must be a 40-character hexadecimal Git SHA")
    if int(source_run_id) <= 0:
        raise ValueError("source run ID must be positive")

    source = lock["candidate_source"]
    source_path = Path(source["path"])
    current_blob = _git_blob_sha1(source_path)
    if current_blob != source["git_blob_sha1"]:
        raise ValueError("v0.26 predictive implementation changed after the first forward run")

    model = lock["frozen_model_state"]
    model_path = Path(model["path"])
    current_model_sha = _sha256(model_path)
    if current_model_sha != model["sha256"]:
        raise ValueError("v0.26 frozen model state changed after the first forward run")

    return {
        "schema": PROVENANCE_SCHEMA,
        "version": lock["version"],
        "candidate": lock["candidate"],
        "forward_start_utc": lock["forward_start_utc"],
        "execution_commit_sha": execution_commit_sha.lower(),
        "candidate_source": source,
        "frozen_model_state": model,
        "source_run_id": int(source_run_id),
        "implementation_lock_path": lock_path.as_posix(),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--implementation-lock", default=str(DEFAULT_LOCK))
    ap.add_argument("--execution-commit-sha", required=True)
    ap.add_argument("--source-run-id", required=True, type=int)
    ap.add_argument("--out", default="reports/v26_2h/v26_implementation_provenance.json")
    args = ap.parse_args()

    payload = build_provenance(
        lock_path=Path(args.implementation_lock),
        execution_commit_sha=args.execution_commit_sha,
        source_run_id=args.source_run_id,
    )
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
