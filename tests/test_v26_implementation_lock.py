import hashlib
import json
from pathlib import Path


LOCK_PATH = Path("reports/locked/V0_26_IMPLEMENTATION_LOCK.json")
EXPECTED_SCHEMA = "gb-power-market-v26-implementation-lock-v1"
EXPECTED_CANDIDATE = "2H_FROZEN_PLUS_CAUSAL_6H_48H_CONSENSUS_CLIPPED_RESIDUAL"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git_blob_sha1(path: Path) -> str:
    data = path.read_bytes()
    header = f"blob {len(data)}\0".encode("utf-8")
    return hashlib.sha1(header + data).hexdigest()


def test_v26_predictive_implementation_remains_byte_identical_to_first_forward_run() -> None:
    lock = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    assert lock["schema"] == EXPECTED_SCHEMA
    assert lock["version"] == "0.26.0"
    assert lock["candidate"] == EXPECTED_CANDIDATE
    assert lock["forward_start_utc"] == "2026-08-22T20:30:00Z"
    assert lock["first_forward_run_id"] == 32604734019
    assert lock["first_forward_execution_commit_sha"] == "85ed0a196e31bdb56e335a1d7c2578704c1a7374"

    source = lock["candidate_source"]
    source_path = Path(source["path"])
    assert source_path.is_file()
    assert _git_blob_sha1(source_path) == source["git_blob_sha1"]
    assert source["git_blob_sha1"] == "399915c6cdd0d3b016bde73cb0ef92eb2697adf8"

    model = lock["frozen_model_state"]
    model_path = Path(model["path"])
    assert model_path.is_file()
    assert _sha256(model_path) == model["sha256"]
    assert model["sha256"] == "e9952aa88ca56b85f4d595bfe918cdc589ac0048d717d3fb3d9210361eb18918"
