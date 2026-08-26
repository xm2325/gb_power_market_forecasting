#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import pandas as pd

from gb_power_market.adaptive_direction_v27_candidate import (
    V27_CANDIDATE_ID,
    V27_VALIDATION_END_UTC,
    V27_VALIDATION_START_UTC,
    apply_causal_direction_veto_candidate,
    candidate_spec,
    summarise_validation_block,
)


DEFAULT_LOCK = Path("reports/locked/V0_27_CANDIDATE_LOCK.json")


def _git_blob_sha1(path: Path) -> str:
    content = path.read_bytes()
    return hashlib.sha1(f"blob {len(content)}\0".encode() + content).hexdigest()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_lock(lock_path: Path) -> dict:
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    if lock["status"] != "DEVELOPMENT_CANDIDATE_FROZEN_NOT_FORWARD_LAUNCHED":
        raise RuntimeError("v0.27 candidate lock status changed")
    if lock["candidate"] != V27_CANDIDATE_ID:
        raise RuntimeError("v0.27 candidate identity changed")

    candidate = lock["candidate_source"]
    if _git_blob_sha1(Path(candidate["path"])) != candidate["git_blob_sha1"]:
        raise RuntimeError("v0.27 candidate source changed after lock")
    base = lock["base_v26_dependency"]
    if _git_blob_sha1(Path(base["path"])) != base["git_blob_sha1"]:
        raise RuntimeError("v0.26 predictive dependency changed after v0.27 lock")
    frozen = lock["frozen_model_state"]
    if _sha256(Path(frozen["path"])) != frozen["sha256"]:
        raise RuntimeError("frozen v0.20 model state changed after v0.27 lock")
    protocol = lock["governing_protocol"]
    if _git_blob_sha1(Path(protocol["path"])) != protocol["git_blob_sha1"]:
        raise RuntimeError("v0.27 governing protocol changed after candidate lock")

    block = lock["independent_validation_block"]
    if pd.Timestamp(block["start_utc"]) != V27_VALIDATION_START_UTC:
        raise RuntimeError("v0.27 validation start changed")
    if pd.Timestamp(block["end_exclusive_utc"]) != V27_VALIDATION_END_UTC:
        raise RuntimeError("v0.27 validation end changed")
    if int(block["rows"]) != 48:
        raise RuntimeError("v0.27 validation row gate changed")
    return lock


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--v24-rows", required=True)
    ap.add_argument("--candidate-lock", default=str(DEFAULT_LOCK))
    ap.add_argument("--out-dir", default="reports/v27_validation")
    args = ap.parse_args()

    lock = verify_lock(Path(args.candidate_lock))
    rows = pd.read_csv(args.v24_rows)
    candidate_rows = apply_causal_direction_veto_candidate(rows)
    summary = summarise_validation_block(candidate_rows)
    if not summary.get("gate_evaluated", False):
        raise RuntimeError(
            "sealed v0.27 validation block is incomplete or non-contiguous; no gate may be evaluated"
        )

    segment = candidate_rows[
        (candidate_rows["target_start_utc"] >= V27_VALIDATION_START_UTC)
        & (candidate_rows["target_start_utc"] < V27_VALIDATION_END_UTC)
    ].copy()
    if len(segment) != 48:
        raise RuntimeError("v0.27 validation output does not contain exactly 48 rows")

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    segment.to_csv(out / "v27_validation_rows.csv", index=False, float_format="%.9f")
    (out / "v27_validation_summary.json").write_text(
        json.dumps(
            {
                "schema": "gb-power-market-v27-development-validation-v1",
                "candidate_lock": lock,
                "candidate_spec": candidate_spec(),
                "validation": summary,
                "evidence_class": "INDEPENDENT_DEVELOPMENT_VALIDATION_NOT_FORWARD_EVIDENCE",
                "post_evaluation_contract": (
                    "These 48 labels become development data immediately after this evaluation. A failed gate "
                    "rejects this candidate on this block. A passed gate only permits a new versioned forward "
                    "experiment beginning strictly after the validation end; it is not itself a performance claim."
                ),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    (out / "v27_candidate_spec.json").write_text(
        json.dumps(candidate_spec(), indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
