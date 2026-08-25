from __future__ import annotations

from typing import Any

import pandas as pd

from .v27_forward_governance import deterministic_forward_start


EXPECTED_CANDIDATE = "2H_FROZEN_PLUS_CAUSAL_6H_48H_CONSENSUS_WITH_FROZEN_DIRECTION_VETO"
MISS_STATUS = "FIRST_PRETARGET_PREDICTION_WINDOW_MISSED"
IMPLEMENTATION_STATUS = "FRESH_FORWARD_CANDIDATE_LOCKED_NOT_YET_EVALUATED"


def _utc(value: str | pd.Timestamp) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    if ts.tzinfo is None:
        raise ValueError("v0.27 pre-target recovery timestamps must be timezone-aware")
    return ts.tz_convert("UTC")


def build_pretarget_recovery_lock(
    *,
    implementation_lock: dict[str, Any],
    miss_record: dict[str, Any],
    recovery_lock_timestamp_utc: str | pd.Timestamp,
) -> dict[str, Any]:
    if implementation_lock.get("status") != IMPLEMENTATION_STATUS:
        raise ValueError("unexpected v0.27 implementation-lock state")
    if implementation_lock.get("version") != "0.27.0":
        raise ValueError("pre-target recovery requires unchanged v0.27.0 implementation")
    if implementation_lock.get("candidate") != EXPECTED_CANDIDATE:
        raise ValueError("v0.27 candidate identity changed")
    if implementation_lock.get("forward_evidence_rows_at_lock") != 0:
        raise ValueError("implementation lock must remain a zero-outcome launch record")

    if miss_record.get("status") != MISS_STATUS:
        raise ValueError("first pre-target miss is not immutably recorded")
    if miss_record.get("candidate") != EXPECTED_CANDIDATE:
        raise ValueError("miss record candidate identity changed")
    if miss_record.get("retrospective_prediction_reconstruction_allowed") is not False:
        raise ValueError("miss record unexpectedly permits retrospective substitution")
    if miss_record.get("original_forward_boundary_changed") is not False:
        raise ValueError("miss record moved the original v0.27 forward boundary")

    original_start = _utc(implementation_lock["forward_start_utc"])
    if _utc(miss_record["locked_first_target_start_utc"]) != original_start:
        raise ValueError("miss record no longer matches original forward start")

    locked_at = _utc(recovery_lock_timestamp_utc)
    if locked_at <= original_start:
        raise ValueError("recovery lock must be created after the missed target began")

    recovery_target = deterministic_forward_start(locked_at)
    recovery_decision = recovery_target - pd.Timedelta(minutes=120)
    if recovery_decision <= locked_at:
        raise AssertionError("recovery decision is not strictly after recovery lock")
    if recovery_target <= original_start:
        raise AssertionError("recovery target did not remain after original v0.27 start")

    return {
        "schema": "gb-power-market-v27-pretarget-recovery-lock-v1",
        "status": "PRETARGET_EVIDENCE_RECOVERY_LOCKED_NOT_YET_PREDICTED",
        "version": "0.27.0",
        "candidate": EXPECTED_CANDIDATE,
        "original_forward_start_utc": original_start.isoformat(),
        "original_forward_boundary_changed": False,
        "missed_first_target_start_utc": _utc(miss_record["locked_first_target_start_utc"]).isoformat(),
        "recovery_lock_timestamp_utc": locked_at.isoformat(),
        "recovery_decision_time_utc": recovery_decision.isoformat(),
        "recovery_target_start_utc": recovery_target.isoformat(),
        "horizon_minutes": 120,
        "selection_rule": "next 30-minute decision grid strictly after recovery lock, then +120 minutes",
        "predictive_source_git_blob_sha1": implementation_lock["candidate_source"]["git_blob_sha1"],
        "model_or_rule_changed_for_recovery": False,
        "target_outcome_accessed_to_select_recovery_boundary": False,
        "automatic_prediction_launch": False,
        "evidence_class": "PRETARGET_PREDICTION_RECOVERY_BOUNDARY_NOT_PERFORMANCE_EVIDENCE",
        "claim_boundary": (
            "This lock does not move the original v0.27 forward start and contains no performance outcome. "
            "It only selects the first future target eligible for stronger Git-committed pre-target prediction evidence after the missed 02:30 target."
        ),
    }
