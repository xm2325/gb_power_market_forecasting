import json
from pathlib import Path

import pytest

from scripts.write_v26_implementation_provenance import build_provenance


LOCK = Path("reports/locked/V0_26_IMPLEMENTATION_LOCK.json")


def test_build_v26_provenance_records_current_locked_implementation() -> None:
    payload = build_provenance(
        lock_path=LOCK,
        execution_commit_sha="1" * 40,
        source_run_id=123,
    )
    assert payload["schema"] == "gb-power-market-v26-execution-provenance-v1"
    assert payload["version"] == "0.26.0"
    assert payload["source_run_id"] == 123
    assert payload["candidate_source"]["git_blob_sha1"] == "399915c6cdd0d3b016bde73cb0ef92eb2697adf8"
    assert payload["frozen_model_state"]["sha256"] == "e9952aa88ca56b85f4d595bfe918cdc589ac0048d717d3fb3d9210361eb18918"


def test_build_v26_provenance_rejects_changed_predictive_source_identity(tmp_path: Path) -> None:
    lock = json.loads(LOCK.read_text(encoding="utf-8"))
    lock["candidate_source"]["git_blob_sha1"] = "0" * 40
    changed = tmp_path / "changed_lock.json"
    changed.write_text(json.dumps(lock), encoding="utf-8")
    with pytest.raises(ValueError, match="predictive implementation changed"):
        build_provenance(
            lock_path=changed,
            execution_commit_sha="1" * 40,
            source_run_id=123,
        )


def test_build_v26_provenance_rejects_invalid_execution_commit() -> None:
    with pytest.raises(ValueError, match="40-character hexadecimal"):
        build_provenance(
            lock_path=LOCK,
            execution_commit_sha="not-a-git-sha",
            source_run_id=123,
        )
