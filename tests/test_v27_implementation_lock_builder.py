import json
from pathlib import Path

import pytest

import scripts.create_v27_forward_implementation_lock as builder


def test_build_implementation_lock_reuses_validated_source_and_deterministic_boundary(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(builder, "OUTPUT_PATH", tmp_path / "V0_27_IMPLEMENTATION_LOCK.json")
    payload = builder.build_implementation_lock("2026-08-25T00:07:12Z")

    assert payload["version"] == "0.27.0"
    assert payload["status"] == "FRESH_FORWARD_CANDIDATE_LOCKED_NOT_YET_EVALUATED"
    assert payload["candidate_source"]["git_blob_sha1"] == "3c361dbb0e1665bbbad2e1097b8580ce062a203f"
    assert payload["base_v26_dependency"]["git_blob_sha1"] == "399915c6cdd0d3b016bde73cb0ef92eb2697adf8"
    assert payload["first_forward_decision_time_utc"] == "2026-08-25T00:30:00+00:00"
    assert payload["forward_start_utc"] == "2026-08-25T02:30:00+00:00"
    assert payload["automatic_forward_launch"] is False
    assert payload["forward_evidence_rows_at_lock"] == 0
    assert payload["validation_evidence"]["eligibility_status"] == "ELIGIBLE_TO_CREATE_FRESH_V27_FORWARD_LOCK"


def test_builder_refuses_rewrite(monkeypatch, tmp_path: Path) -> None:
    output = tmp_path / "V0_27_IMPLEMENTATION_LOCK.json"
    output.write_text(json.dumps({"already": "locked"}), encoding="utf-8")
    monkeypatch.setattr(builder, "OUTPUT_PATH", output)
    with pytest.raises(FileExistsError, match="already exists"):
        builder.build_implementation_lock("2026-08-25T00:07:12Z")


def test_builder_requires_pre_registered_governance_blob(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(builder, "OUTPUT_PATH", tmp_path / "V0_27_IMPLEMENTATION_LOCK.json")
    monkeypatch.setattr(builder, "EXPECTED_GOVERNANCE_BLOB", "0" * 40)
    with pytest.raises(ValueError, match="forward-governance code changed"):
        builder.build_implementation_lock("2026-08-25T00:07:12Z")
