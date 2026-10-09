from __future__ import annotations

import json
from pathlib import Path

import pandas as pd


RECOVERY = Path("reports/forward/v27/V0_27_PRETARGET_RECOVERY_LOCK.json")
IMPLEMENTATION = Path("reports/locked/V0_27_IMPLEMENTATION_LOCK.json")
MISS = Path("reports/forward/v27/V0_27_FIRST_PRETARGET_FREEZE_MISSED.json")


def test_locked_recovery_record_preserves_original_boundary_and_future_target() -> None:
    recovery = json.loads(RECOVERY.read_text(encoding="utf-8"))
    implementation = json.loads(IMPLEMENTATION.read_text(encoding="utf-8"))
    miss = json.loads(MISS.read_text(encoding="utf-8"))

    assert recovery["schema"] == "gb-power-market-v27-pretarget-recovery-lock-v1"
    assert recovery["status"] == "PRETARGET_EVIDENCE_RECOVERY_LOCKED_NOT_YET_PREDICTED"
    assert recovery["version"] == "0.27.0"
    assert recovery["original_forward_start_utc"] == implementation["forward_start_utc"]
    assert recovery["missed_first_target_start_utc"] == miss["locked_first_target_start_utc"]
    assert recovery["original_forward_boundary_changed"] is False
    assert recovery["model_or_rule_changed_for_recovery"] is False
    assert recovery["target_outcome_accessed_to_select_recovery_boundary"] is False
    assert recovery["automatic_prediction_launch"] is False
    assert recovery["predictive_source_git_blob_sha1"] == implementation["candidate_source"]["git_blob_sha1"]

    locked_at = pd.Timestamp(recovery["recovery_lock_timestamp_utc"])
    decision = pd.Timestamp(recovery["recovery_decision_time_utc"])
    target = pd.Timestamp(recovery["recovery_target_start_utc"])
    assert locked_at == pd.Timestamp("2026-08-25T09:44:34.562278Z")
    assert decision == pd.Timestamp("2026-08-25T10:00:00Z")
    assert target == pd.Timestamp("2026-08-25T12:00:00Z")
    assert decision > locked_at
    assert target - decision == pd.Timedelta(minutes=120)
