#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from gb_power_market.v27_forward_governance import deterministic_forward_start

CANDIDATE = "2H_FROZEN_PLUS_CAUSAL_6H_48H_CONSENSUS_WITH_FROZEN_DIRECTION_VETO"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--implementation-lock", default="reports/locked/V0_27_IMPLEMENTATION_LOCK.json")
    ap.add_argument("--previous-recovery-lock", default="reports/forward/v27/V0_27_PRETARGET_RECOVERY_LOCK.json")
    ap.add_argument("--miss-out", default="reports/forward/v27/V0_27_PRETARGET_RECOVERY_1_MISSED.json")
    ap.add_argument("--next-lock-out", default="reports/forward/v27/V0_27_PRETARGET_RECOVERY_LOCK_2.json")
    args = ap.parse_args()

    implementation_path = Path(args.implementation_lock)
    previous_path = Path(args.previous_recovery_lock)
    miss_path = Path(args.miss_out)
    next_path = Path(args.next_lock_out)
    prediction_path = Path("reports/forward/v27/V0_27_PRETARGET_RECOVERY_PREDICTION.json")

    if miss_path.exists() or next_path.exists():
        raise FileExistsError("recovery advancement already recorded; refusing rewrite")
    if prediction_path.exists():
        raise RuntimeError("previous recovery prediction exists; cannot classify it as missed")

    implementation = json.loads(implementation_path.read_text(encoding="utf-8"))
    previous = json.loads(previous_path.read_text(encoding="utf-8"))
    if implementation.get("version") != "0.27.0" or implementation.get("candidate") != CANDIDATE:
        raise ValueError("unexpected v0.27 implementation identity")
    if previous.get("candidate") != CANDIDATE or previous.get("status") != "PRETARGET_EVIDENCE_RECOVERY_LOCKED_NOT_YET_PREDICTED":
        raise ValueError("unexpected previous recovery lock")
    if previous.get("model_or_rule_changed_for_recovery") is not False:
        raise ValueError("previous recovery changed model/rule")

    now = pd.Timestamp(datetime.now(timezone.utc))
    previous_target = pd.Timestamp(previous["recovery_target_start_utc"])
    if now < previous_target:
        raise RuntimeError("previous recovery target has not started; cannot record miss")

    miss = {
        "schema": "gb-power-market-v27-pretarget-recovery-miss-v1",
        "status": "PRETARGET_RECOVERY_1_WINDOW_MISSED",
        "version": "0.27.0",
        "candidate": CANDIDATE,
        "previous_recovery_lock_path": previous_path.as_posix(),
        "previous_recovery_lock_sha256": sha256(previous_path),
        "recovery_decision_time_utc": previous["recovery_decision_time_utc"],
        "recovery_target_start_utc": previous["recovery_target_start_utc"],
        "miss_recorded_utc": now.isoformat(),
        "prediction_file_present": False,
        "retrospective_prediction_reconstruction_allowed": False,
        "original_forward_start_utc": implementation["forward_start_utc"],
        "original_forward_boundary_changed": False,
        "predictive_source_git_blob_sha1": implementation["candidate_source"]["git_blob_sha1"],
        "model_or_rule_changed_after_miss": False,
        "failed_live_run_id": 32833780952,
        "failure_class": "DATETIME_REPRESENTATION_ADAPTER_BUG_AFTER_CAUSAL_INPUT_GATES",
        "claim_boundary": "The 12:00 UTC recovery target is not reconstructed retrospectively. This miss record contains no performance claim and does not move the original v0.27 forward start."
    }

    next_target = deterministic_forward_start(now)
    next_decision = next_target - pd.Timedelta(minutes=120)
    next_lock = {
        "schema": "gb-power-market-v27-pretarget-recovery-lock-v1",
        "status": "PRETARGET_EVIDENCE_RECOVERY_LOCKED_NOT_YET_PREDICTED",
        "sequence": 2,
        "version": "0.27.0",
        "candidate": CANDIDATE,
        "original_forward_start_utc": implementation["forward_start_utc"],
        "original_forward_boundary_changed": False,
        "previous_recovery_miss_path": miss_path.as_posix(),
        "previous_recovery_target_start_utc": previous["recovery_target_start_utc"],
        "recovery_lock_timestamp_utc": now.isoformat(),
        "recovery_decision_time_utc": next_decision.isoformat(),
        "recovery_target_start_utc": next_target.isoformat(),
        "horizon_minutes": 120,
        "selection_rule": "next 30-minute decision grid strictly after recovery lock, then +120 minutes",
        "predictive_source_git_blob_sha1": implementation["candidate_source"]["git_blob_sha1"],
        "model_or_rule_changed_for_recovery": False,
        "target_outcome_accessed_to_select_recovery_boundary": False,
        "automatic_prediction_launch": False,
        "evidence_class": "PRETARGET_PREDICTION_RECOVERY_BOUNDARY_NOT_PERFORMANCE_EVIDENCE"
    }

    miss_path.parent.mkdir(parents=True, exist_ok=True)
    miss_path.write_text(json.dumps(miss, indent=2) + "\n", encoding="utf-8")
    next_path.write_text(json.dumps(next_lock, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"miss": miss, "next_lock": next_lock}, indent=2))


if __name__ == "__main__":
    main()
