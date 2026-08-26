import hashlib
import json
from pathlib import Path

import pandas as pd
import pytest

import scripts.lock_v27_development_validation as locker


def _configure_outputs(monkeypatch, tmp_path: Path) -> None:
    repo_lock = Path("reports/locked/V0_27_CANDIDATE_LOCK.json").resolve()
    lock_payload = json.loads(repo_lock.read_text(encoding="utf-8"))
    monkeypatch.setattr(locker, "CANDIDATE_LOCK", repo_lock)
    monkeypatch.setattr(locker, "_verify_candidate_lock", lambda: lock_payload)
    monkeypatch.setattr(locker, "RESULT_PATH", tmp_path / "result.json")
    monkeypatch.setattr(locker, "PROVENANCE_PATH", tmp_path / "provenance.json")
    monkeypatch.setattr(locker, "ROWS_PATH", tmp_path / "rows.csv")
    monkeypatch.setattr(locker, "ELIGIBILITY_PATH", tmp_path / "eligibility.json")
    monkeypatch.setattr(locker, "DOC_PATH", tmp_path / "result.md")
    (tmp_path / "reports/monitoring").mkdir(parents=True)
    monkeypatch.chdir(tmp_path)


def _artifact(tmp_path: Path, *, passed: bool, run_id: int = 12345) -> Path:
    artifact = tmp_path / "artifact"
    artifact.mkdir()
    lock_path = locker.CANDIDATE_LOCK
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    gates = {
        "candidate_mae_strictly_better_than_frozen": passed,
        "candidate_p95_abs_error_non_worse_than_frozen": True,
        "candidate_absolute_signed_bias_non_worse_than_frozen": True,
        "candidate_mae_strictly_better_than_previous_day_reference": True,
    }
    overall = all(gates.values())
    validation = {
        "status": "VALIDATION_BLOCK_EVALUATED",
        "rows": 48,
        "required_rows": 48,
        "validation_start_utc": "2026-08-23T22:00:00+00:00",
        "validation_end_exclusive_utc": "2026-08-24T22:00:00+00:00",
        "candidate_mae_gbp_mwh": 9.0 if passed else 11.0,
        "frozen_mae_gbp_mwh": 10.0,
        "reference_mae_gbp_mwh": 12.0,
        "candidate_p95_abs_error_gbp_mwh": 20.0,
        "frozen_p95_abs_error_gbp_mwh": 20.0,
        "candidate_signed_bias_gbp_mwh": 1.0,
        "frozen_signed_bias_gbp_mwh": 1.5,
        "candidate_win_rate_vs_frozen": 0.6,
        "direction_veto_rate": 0.5,
        "gates": gates,
        "all_validation_gates_passed": overall,
        "gate_evaluated": True,
        "forward_launch_allowed": overall,
        "automatic_forward_launch": False,
    }
    summary = {
        "schema": "gb-power-market-v27-development-validation-v1",
        "candidate_lock": lock,
        "candidate_spec": {"candidate": locker.EXPECTED_CANDIDATE},
        "validation": validation,
        "evidence_class": "INDEPENDENT_DEVELOPMENT_VALIDATION_NOT_FORWARD_EVIDENCE",
        "post_evaluation_contract": "test",
    }
    (artifact / "v27_validation_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

    targets = pd.date_range("2026-08-23T22:00:00Z", "2026-08-24T22:00:00Z", freq="30min", inclusive="left")
    pd.DataFrame({"target_start_utc": targets}).to_csv(artifact / "v27_validation_rows.csv", index=False)

    provenance = {
        "schema": "gb-power-market-v27-development-validation-provenance-v1",
        "workflow_run_id": run_id,
        "execution_commit_sha": "a" * 40,
        "candidate_lock_path": lock_path.as_posix(),
        "candidate_lock_sha256": hashlib.sha256(lock_path.read_bytes()).hexdigest(),
        "validation_start_utc": "2026-08-23T22:00:00+00:00",
        "validation_end_exclusive_utc": "2026-08-24T22:00:00+00:00",
        "rows": 48,
        "all_validation_gates_passed": overall,
        "forward_launch_allowed_by_metrics": overall,
        "automatic_forward_launch": False,
    }
    (artifact / "v27_validation_provenance.json").write_text(json.dumps(provenance, indent=2), encoding="utf-8")
    return artifact


def test_lock_pass_only_grants_forward_lock_eligibility(monkeypatch, tmp_path: Path) -> None:
    _configure_outputs(monkeypatch, tmp_path)
    artifact = _artifact(tmp_path, passed=True)
    manifest = locker.lock_validation_result(
        artifact_dir=artifact,
        run_id=12345,
        artifact_id=77,
        artifact_sha256="b" * 64,
    )
    eligibility = json.loads(locker.ELIGIBILITY_PATH.read_text(encoding="utf-8"))
    assert manifest["validation_passed"] is True
    assert eligibility["status"] == "ELIGIBLE_TO_CREATE_FRESH_V27_FORWARD_LOCK"
    assert eligibility["automatic_forward_launch"] is False
    assert "strictly after 2026-08-24T22:00:00Z" in eligibility["required_action"]

    with pytest.raises(FileExistsError):
        locker.lock_validation_result(
            artifact_dir=artifact,
            run_id=12345,
            artifact_id=77,
            artifact_sha256="b" * 64,
        )


def test_lock_failure_rejects_candidate_on_same_block(monkeypatch, tmp_path: Path) -> None:
    _configure_outputs(monkeypatch, tmp_path)
    artifact = _artifact(tmp_path, passed=False)
    manifest = locker.lock_validation_result(
        artifact_dir=artifact,
        run_id=12345,
        artifact_id=77,
        artifact_sha256="c" * 64,
    )
    eligibility = json.loads(locker.ELIGIBILITY_PATH.read_text(encoding="utf-8"))
    assert manifest["validation_passed"] is False
    assert eligibility["status"] == "CANDIDATE_REJECTED_ON_SEALED_BLOCK"
    assert eligibility["automatic_forward_launch"] is False
    assert "Do not retune or re-evaluate" in eligibility["required_action"]


def test_lock_rejects_row_leak_beyond_sealed_boundary(monkeypatch, tmp_path: Path) -> None:
    _configure_outputs(monkeypatch, tmp_path)
    artifact = _artifact(tmp_path, passed=True)
    rows_path = artifact / "v27_validation_rows.csv"
    rows = pd.read_csv(rows_path)
    rows.loc[47, "target_start_utc"] = "2026-08-24 22:00:00+00:00"
    rows.to_csv(rows_path, index=False)
    with pytest.raises(ValueError, match="exact sealed 48-row block"):
        locker.lock_validation_result(
            artifact_dir=artifact,
            run_id=12345,
            artifact_id=77,
            artifact_sha256="d" * 64,
        )
