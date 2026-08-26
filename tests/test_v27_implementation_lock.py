import hashlib
import json
from pathlib import Path

from gb_power_market.v27_forward_governance import verify_forward_launch_preconditions


LOCK = Path("reports/locked/V0_27_IMPLEMENTATION_LOCK.json")


def _git_blob_sha1(path: Path) -> str:
    data = path.read_bytes()
    return hashlib.sha1(f"blob {len(data)}\0".encode() + data).hexdigest()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_v27_implementation_lock_reproduces_validated_source_and_boundary() -> None:
    lock = json.loads(LOCK.read_text(encoding="utf-8"))
    assert lock["schema"] == "gb-power-market-v27-forward-implementation-lock-v1"
    assert lock["status"] == "FRESH_FORWARD_CANDIDATE_LOCKED_NOT_YET_EVALUATED"
    assert lock["version"] == "0.27.0"
    assert lock["forward_evidence_rows_at_lock"] == 0
    assert lock["automatic_forward_launch"] is False

    source = lock["candidate_source"]
    assert _git_blob_sha1(Path(source["path"])) == source["git_blob_sha1"] == "3c361dbb0e1665bbbad2e1097b8580ce062a203f"
    dependency = lock["base_v26_dependency"]
    assert _git_blob_sha1(Path(dependency["path"])) == dependency["git_blob_sha1"] == "399915c6cdd0d3b016bde73cb0ef92eb2697adf8"
    frozen = lock["frozen_model_state"]
    assert _sha256(Path(frozen["path"])) == frozen["sha256"] == "e9952aa88ca56b85f4d595bfe918cdc589ac0048d717d3fb3d9210361eb18918"

    evidence = lock["validation_evidence"]
    manifest = json.loads(Path("reports/monitoring/V0_27_DEVELOPMENT_VALIDATION_LOCK_MANIFEST.json").read_text())
    assert evidence["result_sha256"] == manifest["result_sha256"] == _sha256(Path("reports/monitoring/V0_27_DEVELOPMENT_VALIDATION_RESULT.json"))
    assert evidence["provenance_sha256"] == manifest["provenance_sha256"] == _sha256(Path("reports/monitoring/V0_27_DEVELOPMENT_VALIDATION_PROVENANCE.json"))
    assert evidence["rows_sha256"] == manifest["rows_sha256"] == _sha256(Path("reports/monitoring/V0_27_DEVELOPMENT_VALIDATION_ROWS.csv"))
    assert evidence["eligibility_sha256"] == manifest["eligibility_sha256"] == _sha256(Path("reports/monitoring/V0_27_FORWARD_ELIGIBILITY.json"))

    governance = lock["pre_registered_forward_governance"]
    assert _git_blob_sha1(Path(governance["path"])) == governance["git_blob_sha1"] == "7741a8e3128bbd48ea4c4d005b825331f532dc52"

    checked = verify_forward_launch_preconditions(
        eligibility_path=Path("reports/monitoring/V0_27_FORWARD_ELIGIBILITY.json"),
        implementation_lock_timestamp_utc=lock["implementation_lock_timestamp_utc"],
        proposed_forward_start_utc=lock["forward_start_utc"],
    )
    assert checked["first_forward_decision_time_utc"] == lock["first_forward_decision_time_utc"]
    assert lock["first_forward_decision_time_utc"] == "2026-08-25T00:30:00+00:00"
    assert lock["forward_start_utc"] == "2026-08-25T02:30:00+00:00"
