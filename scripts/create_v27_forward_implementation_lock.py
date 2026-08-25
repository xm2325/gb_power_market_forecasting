#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from gb_power_market.v27_forward_governance import (
    EXPECTED_CANDIDATE,
    deterministic_forward_start,
    verify_forward_launch_preconditions,
)

VERSION = "0.27.0"
LOCK_SCHEMA = "gb-power-market-v27-forward-implementation-lock-v1"
LOCK_STATUS = "FRESH_FORWARD_CANDIDATE_LOCKED_NOT_YET_EVALUATED"
EXPECTED_GOVERNANCE_BLOB = "7741a8e3128bbd48ea4c4d005b825331f532dc52"

CANDIDATE_LOCK_PATH = Path("reports/locked/V0_27_CANDIDATE_LOCK.json")
ELIGIBILITY_PATH = Path("reports/monitoring/V0_27_FORWARD_ELIGIBILITY.json")
VALIDATION_RESULT_PATH = Path("reports/monitoring/V0_27_DEVELOPMENT_VALIDATION_RESULT.json")
VALIDATION_PROVENANCE_PATH = Path("reports/monitoring/V0_27_DEVELOPMENT_VALIDATION_PROVENANCE.json")
VALIDATION_ROWS_PATH = Path("reports/monitoring/V0_27_DEVELOPMENT_VALIDATION_ROWS.csv")
VALIDATION_MANIFEST_PATH = Path("reports/monitoring/V0_27_DEVELOPMENT_VALIDATION_LOCK_MANIFEST.json")
GOVERNANCE_PATH = Path("src/gb_power_market/v27_forward_governance.py")
OUTPUT_PATH = Path("reports/locked/V0_27_IMPLEMENTATION_LOCK.json")


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git_blob_sha1(path: Path) -> str:
    data = path.read_bytes()
    return hashlib.sha1(f"blob {len(data)}\0".encode() + data).hexdigest()


def _load(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(path)
    return json.loads(path.read_text(encoding="utf-8"))


def _verify_validation_evidence() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    candidate_lock = _load(CANDIDATE_LOCK_PATH)
    eligibility = _load(ELIGIBILITY_PATH)
    result = _load(VALIDATION_RESULT_PATH)
    provenance = _load(VALIDATION_PROVENANCE_PATH)
    manifest = _load(VALIDATION_MANIFEST_PATH)

    if manifest.get("status") != "SEALED_VALIDATION_RESULT_LOCKED":
        raise ValueError("v0.27 validation result is not immutably locked")
    if manifest.get("validation_passed") is not True:
        raise ValueError("v0.27 sealed validation did not pass")
    if manifest.get("forward_eligibility_status") != "ELIGIBLE_TO_CREATE_FRESH_V27_FORWARD_LOCK":
        raise ValueError("v0.27 validation manifest does not grant forward-lock eligibility")
    if eligibility.get("status") != "ELIGIBLE_TO_CREATE_FRESH_V27_FORWARD_LOCK":
        raise ValueError("v0.27 eligibility does not permit a fresh forward lock")
    if eligibility.get("validation_passed") is not True or eligibility.get("automatic_forward_launch") is not False:
        raise ValueError("v0.27 eligibility contract changed")
    if result.get("evidence_class") != "INDEPENDENT_DEVELOPMENT_VALIDATION_NOT_FORWARD_EVIDENCE":
        raise ValueError("v0.27 validation evidence class changed")
    validation = result.get("validation", {})
    if validation.get("all_validation_gates_passed") is not True:
        raise ValueError("v0.27 result does not pass every validation gate")
    if validation.get("automatic_forward_launch") is not False:
        raise ValueError("v0.27 validation unexpectedly auto-launches forward evidence")

    expected_digests = {
        "result_sha256": sha256_file(VALIDATION_RESULT_PATH),
        "provenance_sha256": sha256_file(VALIDATION_PROVENANCE_PATH),
        "rows_sha256": sha256_file(VALIDATION_ROWS_PATH),
        "eligibility_sha256": sha256_file(ELIGIBILITY_PATH),
    }
    for key, actual in expected_digests.items():
        if manifest.get(key) != actual:
            raise ValueError(f"v0.27 validation {key} differs from immutable manifest")

    if eligibility.get("candidate") != EXPECTED_CANDIDATE or candidate_lock.get("candidate") != EXPECTED_CANDIDATE:
        raise ValueError("v0.27 candidate identity changed")
    if result.get("candidate_lock") != candidate_lock:
        raise ValueError("v0.27 validation result embeds a different candidate lock")
    if int(eligibility.get("source_run_id", -1)) != int(manifest.get("run_id", -2)):
        raise ValueError("v0.27 validation run identity changed")
    if int(eligibility.get("artifact_id", -1)) != int(manifest.get("artifact_id", -2)):
        raise ValueError("v0.27 validation artifact identity changed")
    if eligibility.get("artifact_sha256") != manifest.get("artifact_sha256"):
        raise ValueError("v0.27 validation artifact digest changed")

    source = candidate_lock["candidate_source"]
    if git_blob_sha1(Path(source["path"])) != source["git_blob_sha1"]:
        raise ValueError("validated v0.27 predictive source changed after candidate lock")
    dependency = candidate_lock["base_v26_dependency"]
    if git_blob_sha1(Path(dependency["path"])) != dependency["git_blob_sha1"]:
        raise ValueError("v0.26 predictive dependency changed after validation")
    frozen = candidate_lock["frozen_model_state"]
    if sha256_file(Path(frozen["path"])) != frozen["sha256"]:
        raise ValueError("frozen v0.20 model state changed after validation")
    if git_blob_sha1(GOVERNANCE_PATH) != EXPECTED_GOVERNANCE_BLOB:
        raise ValueError("pre-registered v0.27 forward-governance code changed after validation")

    return candidate_lock, eligibility, manifest


def build_implementation_lock(lock_timestamp_utc: str | None = None) -> dict[str, Any]:
    if OUTPUT_PATH.exists():
        raise FileExistsError("v0.27 implementation lock already exists; refusing rewrite")

    candidate_lock, eligibility, manifest = _verify_validation_evidence()
    lock_time = lock_timestamp_utc or datetime.now(timezone.utc).isoformat()
    forward_start = deterministic_forward_start(lock_time)
    boundary = verify_forward_launch_preconditions(
        eligibility_path=ELIGIBILITY_PATH,
        implementation_lock_timestamp_utc=lock_time,
        proposed_forward_start_utc=forward_start,
    )

    payload = {
        "schema": LOCK_SCHEMA,
        "status": LOCK_STATUS,
        "version": VERSION,
        "candidate": EXPECTED_CANDIDATE,
        "candidate_source": candidate_lock["candidate_source"],
        "base_v26_dependency": candidate_lock["base_v26_dependency"],
        "frozen_model_state": candidate_lock["frozen_model_state"],
        "validation_evidence": {
            "classification": "INDEPENDENT_DEVELOPMENT_VALIDATION_NOT_FORWARD_EVIDENCE",
            "source_run_id": manifest["run_id"],
            "artifact_id": manifest["artifact_id"],
            "artifact_sha256": manifest["artifact_sha256"],
            "result_sha256": manifest["result_sha256"],
            "provenance_sha256": manifest["provenance_sha256"],
            "rows_sha256": manifest["rows_sha256"],
            "eligibility_sha256": manifest["eligibility_sha256"],
            "eligibility_status": eligibility["status"],
        },
        "pre_registered_forward_governance": {
            "path": GOVERNANCE_PATH.as_posix(),
            "git_blob_sha1": EXPECTED_GOVERNANCE_BLOB,
            "selection_rule": boundary["selection_rule"],
        },
        "implementation_lock_timestamp_utc": boundary["implementation_lock_timestamp_utc"],
        "first_forward_decision_time_utc": boundary["first_forward_decision_time_utc"],
        "forward_start_utc": boundary["forward_start_utc"],
        "horizon_minutes": 120,
        "automatic_forward_launch": False,
        "forward_evidence_rows_at_lock": 0,
        "claim_boundary": (
            "The sealed 48-row result is independent development validation only. This lock creates a fresh "
            "0.27.0 forward candidate and deterministic future boundary; it contains zero v0.27 forward outcomes."
        ),
    }
    return payload


def main() -> None:
    payload = build_implementation_lock()
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
