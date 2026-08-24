import hashlib
import json
from pathlib import Path


LOCK = Path("reports/locked/V0_27_CANDIDATE_LOCK.json")


def _git_blob_sha1(path: Path) -> str:
    content = path.read_bytes()
    header = f"blob {len(content)}\0".encode()
    return hashlib.sha1(header + content).hexdigest()


def test_v27_candidate_lock_matches_predictive_dependencies_and_protocol() -> None:
    lock = json.loads(LOCK.read_text(encoding="utf-8"))

    assert lock["status"] == "DEVELOPMENT_CANDIDATE_FROZEN_NOT_FORWARD_LAUNCHED"
    assert lock["candidate"] == (
        "2H_FROZEN_PLUS_CAUSAL_6H_48H_CONSENSUS_WITH_FROZEN_DIRECTION_VETO"
    )
    assert lock["independent_validation_block"] == {
        "start_utc": "2026-08-23T22:00:00Z",
        "end_exclusive_utc": "2026-08-24T22:00:00Z",
        "rows": 48,
        "duration_hours": 24,
        "status": "SEALED_NOT_YET_READ_BY_VALIDATION_WORKFLOW",
    }
    assert lock["new_structure"]["parameter_search"] is False

    candidate = lock["candidate_source"]
    assert _git_blob_sha1(Path(candidate["path"])) == candidate["git_blob_sha1"]

    base = lock["base_v26_dependency"]
    assert _git_blob_sha1(Path(base["path"])) == base["git_blob_sha1"]

    protocol = lock["governing_protocol"]
    assert _git_blob_sha1(Path(protocol["path"])) == protocol["git_blob_sha1"]

    frozen = lock["frozen_model_state"]
    frozen_sha256 = hashlib.sha256(Path(frozen["path"]).read_bytes()).hexdigest()
    assert frozen_sha256 == frozen["sha256"]
