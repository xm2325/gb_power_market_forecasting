#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

import pandas as pd


EXPECTED_CANDIDATE = "2H_FROZEN_PLUS_CAUSAL_6H_48H_CONSENSUS_WITH_FROZEN_DIRECTION_VETO"
EXPECTED_SCHEMA = "gb-power-market-v27-development-validation-v1"
EXPECTED_PROVENANCE_SCHEMA = "gb-power-market-v27-development-validation-provenance-v1"
EXPECTED_EVIDENCE_CLASS = "INDEPENDENT_DEVELOPMENT_VALIDATION_NOT_FORWARD_EVIDENCE"
EXPECTED_START = pd.Timestamp("2026-08-23T22:00:00Z")
EXPECTED_END = pd.Timestamp("2026-08-24T22:00:00Z")
EXPECTED_ROWS = 48
CANDIDATE_LOCK = Path("reports/locked/V0_27_CANDIDATE_LOCK.json")
RESULT_PATH = Path("reports/monitoring/V0_27_DEVELOPMENT_VALIDATION_RESULT.json")
PROVENANCE_PATH = Path("reports/monitoring/V0_27_DEVELOPMENT_VALIDATION_PROVENANCE.json")
ROWS_PATH = Path("reports/monitoring/V0_27_DEVELOPMENT_VALIDATION_ROWS.csv")
ELIGIBILITY_PATH = Path("reports/monitoring/V0_27_FORWARD_ELIGIBILITY.json")
DOC_PATH = Path("docs/V0_27_DEVELOPMENT_VALIDATION_RESULT.md")


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git_blob_sha1(path: Path) -> str:
    data = path.read_bytes()
    return hashlib.sha1(f"blob {len(data)}\0".encode() + data).hexdigest()


def _utc(value: str) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    if ts.tzinfo is None:
        raise ValueError("validation boundary must be timezone-aware")
    return ts.tz_convert("UTC")


def _copy_exact(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)
    if source.read_bytes() != destination.read_bytes():
        raise RuntimeError(f"byte-exact copy failed for {destination}")


def _verify_candidate_lock() -> dict[str, Any]:
    lock = json.loads(CANDIDATE_LOCK.read_text(encoding="utf-8"))
    if lock.get("status") != "DEVELOPMENT_CANDIDATE_FROZEN_NOT_FORWARD_LAUNCHED":
        raise ValueError("v0.27 candidate lock status changed")
    if lock.get("candidate") != EXPECTED_CANDIDATE:
        raise ValueError("v0.27 candidate identity changed")

    candidate = lock["candidate_source"]
    if git_blob_sha1(Path(candidate["path"])) != candidate["git_blob_sha1"]:
        raise ValueError("v0.27 candidate source changed after lock")
    base = lock["base_v26_dependency"]
    if git_blob_sha1(Path(base["path"])) != base["git_blob_sha1"]:
        raise ValueError("v0.26 dependency changed after v0.27 lock")
    frozen = lock["frozen_model_state"]
    if sha256_file(Path(frozen["path"])) != frozen["sha256"]:
        raise ValueError("frozen model state changed after v0.27 lock")
    protocol = lock["governing_protocol"]
    if git_blob_sha1(Path(protocol["path"])) != protocol["git_blob_sha1"]:
        raise ValueError("v0.27 governing protocol changed after candidate lock")

    block = lock["independent_validation_block"]
    if _utc(block["start_utc"]) != EXPECTED_START or _utc(block["end_exclusive_utc"]) != EXPECTED_END:
        raise ValueError("v0.27 sealed validation boundary changed")
    if int(block["rows"]) != EXPECTED_ROWS:
        raise ValueError("v0.27 sealed validation row count changed")
    return lock


def _verify_summary(summary: dict[str, Any], lock: dict[str, Any]) -> dict[str, Any]:
    if summary.get("schema") != EXPECTED_SCHEMA:
        raise ValueError("unsupported v0.27 validation summary schema")
    if summary.get("evidence_class") != EXPECTED_EVIDENCE_CLASS:
        raise ValueError("v0.27 validation evidence class changed")

    embedded_lock = summary.get("candidate_lock")
    if embedded_lock != lock:
        raise ValueError("validation artifact candidate lock differs from repository lock")

    validation = summary.get("validation", {})
    if validation.get("status") != "VALIDATION_BLOCK_EVALUATED":
        raise ValueError("v0.27 validation block was not fully evaluated")
    if int(validation.get("rows", -1)) != EXPECTED_ROWS:
        raise ValueError("v0.27 validation result does not contain exactly 48 rows")
    if int(validation.get("required_rows", -1)) != EXPECTED_ROWS:
        raise ValueError("v0.27 validation required row count changed")
    if _utc(validation["validation_start_utc"]) != EXPECTED_START:
        raise ValueError("v0.27 validation result start changed")
    if _utc(validation["validation_end_exclusive_utc"]) != EXPECTED_END:
        raise ValueError("v0.27 validation result end changed")
    if validation.get("gate_evaluated") is not True:
        raise ValueError("v0.27 validation gates were not evaluated")
    if validation.get("automatic_forward_launch") is not False:
        raise ValueError("v0.27 validation must not auto-launch forward evidence")

    gates = validation.get("gates", {})
    expected_gate_names = {
        "candidate_mae_strictly_better_than_frozen",
        "candidate_p95_abs_error_non_worse_than_frozen",
        "candidate_absolute_signed_bias_non_worse_than_frozen",
        "candidate_mae_strictly_better_than_previous_day_reference",
    }
    if set(gates) != expected_gate_names:
        raise ValueError("v0.27 validation gate set changed")
    recomputed_pass = all(bool(gates[name]) for name in sorted(expected_gate_names))
    if bool(validation.get("all_validation_gates_passed")) != recomputed_pass:
        raise ValueError("v0.27 all-gates result is inconsistent")
    if bool(validation.get("forward_launch_allowed")) != recomputed_pass:
        raise ValueError("v0.27 metric eligibility is inconsistent with gates")
    return validation


def _verify_rows(rows_path: Path) -> pd.DataFrame:
    rows = pd.read_csv(rows_path)
    if len(rows) != EXPECTED_ROWS:
        raise ValueError("v0.27 validation rows file must contain exactly 48 rows")
    target = pd.to_datetime(rows["target_start_utc"], utc=True, errors="raise")
    expected = pd.date_range(EXPECTED_START, EXPECTED_END, freq="30min", inclusive="left")
    if list(target) != list(expected):
        raise ValueError("v0.27 validation rows are not the exact sealed 48-row block")
    if target.max() >= EXPECTED_END:
        raise ValueError("v0.27 validation rows leaked beyond the sealed end")
    return rows


def _verify_provenance(provenance: dict[str, Any], *, run_id: int) -> None:
    if provenance.get("schema") != EXPECTED_PROVENANCE_SCHEMA:
        raise ValueError("unsupported v0.27 validation provenance schema")
    if int(provenance.get("workflow_run_id", -1)) != int(run_id):
        raise ValueError("v0.27 provenance run ID differs from requested artifact run")
    if int(provenance.get("rows", -1)) != EXPECTED_ROWS:
        raise ValueError("v0.27 provenance row count changed")
    if _utc(provenance["validation_start_utc"]) != EXPECTED_START:
        raise ValueError("v0.27 provenance validation start changed")
    if _utc(provenance["validation_end_exclusive_utc"]) != EXPECTED_END:
        raise ValueError("v0.27 provenance validation end changed")
    if provenance.get("automatic_forward_launch") is not False:
        raise ValueError("v0.27 provenance claims automatic forward launch")
    if len(str(provenance.get("execution_commit_sha", ""))) != 40:
        raise ValueError("v0.27 provenance execution commit SHA is invalid")
    if provenance.get("candidate_lock_path") != CANDIDATE_LOCK.as_posix():
        raise ValueError("v0.27 provenance candidate lock path changed")
    if provenance.get("candidate_lock_sha256") != sha256_file(CANDIDATE_LOCK):
        raise ValueError("v0.27 provenance candidate lock digest changed")


def _build_eligibility(*, validation: dict[str, Any], run_id: int, artifact_id: int, artifact_sha256: str) -> dict[str, Any]:
    passed = bool(validation["all_validation_gates_passed"])
    if passed:
        status = "ELIGIBLE_TO_CREATE_FRESH_V27_FORWARD_LOCK"
        action = (
            "Create a separately versioned 0.27.0 implementation lock and choose a forward boundary strictly "
            "after 2026-08-24T22:00:00Z. Do not reuse validation labels as forward evidence."
        )
    else:
        status = "CANDIDATE_REJECTED_ON_SEALED_BLOCK"
        action = (
            "Do not retune or re-evaluate this candidate on the same 48 validation rows. Any new structure "
            "requires a new later development-validation block."
        )
    return {
        "schema": "gb-power-market-v27-forward-eligibility-v1",
        "candidate": EXPECTED_CANDIDATE,
        "status": status,
        "validation_passed": passed,
        "automatic_forward_launch": False,
        "validation_start_utc": EXPECTED_START.isoformat(),
        "validation_end_exclusive_utc": EXPECTED_END.isoformat(),
        "validation_rows": EXPECTED_ROWS,
        "source_run_id": int(run_id),
        "artifact_id": int(artifact_id),
        "artifact_sha256": artifact_sha256,
        "required_action": action,
        "claim_boundary": (
            "This is independent development validation, not fresh v0.27 forward evidence and not a production/PnL claim."
        ),
    }


def _build_doc(validation: dict[str, Any], eligibility: dict[str, Any]) -> str:
    gates = validation["gates"]
    lines = [
        "# v0.27 sealed development-validation result",
        "",
        f"Candidate: `{EXPECTED_CANDIDATE}`.",
        "",
        f"Validation block: `{EXPECTED_START.isoformat()}` to `{EXPECTED_END.isoformat()}` end-exclusive "
        f"(**{EXPECTED_ROWS} half-hours**).",
        "",
        "| Metric | Candidate | Frozen |",
        "|---|---:|---:|",
        f"| MAE (£/MWh) | {validation['candidate_mae_gbp_mwh']:.3f} | {validation['frozen_mae_gbp_mwh']:.3f} |",
        f"| P95 abs error (£/MWh) | {validation['candidate_p95_abs_error_gbp_mwh']:.3f} | {validation['frozen_p95_abs_error_gbp_mwh']:.3f} |",
        f"| Signed bias (£/MWh) | {validation['candidate_signed_bias_gbp_mwh']:.3f} | {validation['frozen_signed_bias_gbp_mwh']:.3f} |",
        "",
        f"Previous-day reference MAE: **{validation['reference_mae_gbp_mwh']:.3f} £/MWh**.",
        "",
        "Gates:",
        "",
        *[f"- `{name}`: **{'PASS' if bool(value) else 'FAIL'}**;" for name, value in gates.items()],
        "",
        f"Overall validation: **{'PASS' if validation['all_validation_gates_passed'] else 'FAIL'}**.",
        f"Forward eligibility state: `{eligibility['status']}`.",
        "",
        "This result is development validation only. It never auto-launches forward evidence. A failed candidate "
        "cannot be retuned on these labels; a passing candidate still requires a new implementation lock and a "
        "strictly later unseen forward boundary.",
        "",
    ]
    return "\n".join(lines)


def lock_validation_result(
    *, artifact_dir: Path, run_id: int, artifact_id: int, artifact_sha256: str
) -> dict[str, Any]:
    for path in [RESULT_PATH, PROVENANCE_PATH, ROWS_PATH, ELIGIBILITY_PATH, DOC_PATH]:
        if path.exists():
            raise FileExistsError("v0.27 sealed validation result is already locked; refusing rewrite")

    summary_source = artifact_dir / "v27_validation_summary.json"
    provenance_source = artifact_dir / "v27_validation_provenance.json"
    rows_source = artifact_dir / "v27_validation_rows.csv"
    if not summary_source.is_file() or not provenance_source.is_file() or not rows_source.is_file():
        raise FileNotFoundError("v0.27 validation artifact is missing summary, provenance or rows")

    lock = _verify_candidate_lock()
    summary = json.loads(summary_source.read_text(encoding="utf-8"))
    validation = _verify_summary(summary, lock)
    _verify_rows(rows_source)
    provenance = json.loads(provenance_source.read_text(encoding="utf-8"))
    _verify_provenance(provenance, run_id=run_id)

    if bool(provenance.get("all_validation_gates_passed")) != bool(validation["all_validation_gates_passed"]):
        raise ValueError("v0.27 provenance gate outcome differs from summary")
    if bool(provenance.get("forward_launch_allowed_by_metrics")) != bool(validation["forward_launch_allowed"]):
        raise ValueError("v0.27 provenance metric eligibility differs from summary")

    _copy_exact(summary_source, RESULT_PATH)
    _copy_exact(provenance_source, PROVENANCE_PATH)
    _copy_exact(rows_source, ROWS_PATH)

    eligibility = _build_eligibility(
        validation=validation,
        run_id=run_id,
        artifact_id=artifact_id,
        artifact_sha256=artifact_sha256,
    )
    ELIGIBILITY_PATH.write_text(json.dumps(eligibility, indent=2) + "\n", encoding="utf-8")
    DOC_PATH.parent.mkdir(parents=True, exist_ok=True)
    DOC_PATH.write_text(_build_doc(validation, eligibility), encoding="utf-8")

    digests = {
        "result_sha256": sha256_file(RESULT_PATH),
        "provenance_sha256": sha256_file(PROVENANCE_PATH),
        "rows_sha256": sha256_file(ROWS_PATH),
        "eligibility_sha256": sha256_file(ELIGIBILITY_PATH),
        "doc_sha256": sha256_file(DOC_PATH),
    }
    manifest = {
        "schema": "gb-power-market-v27-development-validation-lock-manifest-v1",
        "status": "SEALED_VALIDATION_RESULT_LOCKED",
        "candidate": EXPECTED_CANDIDATE,
        "run_id": int(run_id),
        "artifact_id": int(artifact_id),
        "artifact_sha256": artifact_sha256,
        "validation_passed": bool(validation["all_validation_gates_passed"]),
        "forward_eligibility_status": eligibility["status"],
        **digests,
    }
    manifest_path = Path("reports/monitoring/V0_27_DEVELOPMENT_VALIDATION_LOCK_MANIFEST.json")
    if manifest_path.exists():
        raise FileExistsError("v0.27 validation lock manifest already exists")
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--artifact-dir", required=True)
    ap.add_argument("--run-id", required=True, type=int)
    ap.add_argument("--artifact-id", required=True, type=int)
    ap.add_argument("--artifact-sha256", required=True)
    args = ap.parse_args()
    result = lock_validation_result(
        artifact_dir=Path(args.artifact_dir),
        run_id=args.run_id,
        artifact_id=args.artifact_id,
        artifact_sha256=args.artifact_sha256,
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
