from __future__ import annotations

import json
from pathlib import Path


MISS = Path("reports/forward/v27/V0_27_FIRST_PRETARGET_FREEZE_MISSED.json")
FORBIDDEN_RETRO = Path("reports/forward/v27/V0_27_FIRST_FORWARD_PREDICTION_2026-08-25_0230Z.json")
LOCK = Path("reports/locked/V0_27_IMPLEMENTATION_LOCK.json")


def test_first_pretarget_miss_is_permanent_and_does_not_move_forward_boundary() -> None:
    miss = json.loads(MISS.read_text(encoding="utf-8"))
    lock = json.loads(LOCK.read_text(encoding="utf-8"))

    assert miss["schema"] == "gb-power-market-v27-pretarget-freeze-miss-v1"
    assert miss["status"] == "FIRST_PRETARGET_PREDICTION_WINDOW_MISSED"
    assert miss["evidence_class"] == "PRETARGET_PREDICTION_EVIDENCE_MISSED_NO_RETROSPECTIVE_SUBSTITUTION"
    assert miss["prediction_committed_before_target"] is False
    assert miss["target_outcome_accessed_to_create_this_record"] is False
    assert miss["retrospective_prediction_reconstruction_allowed"] is False
    assert miss["original_forward_boundary_changed"] is False
    assert miss["locked_first_decision_time_utc"] == lock["first_forward_decision_time_utc"]
    assert miss["locked_first_target_start_utc"] == lock["forward_start_utc"]
    assert lock["forward_evidence_rows_at_lock"] == 0

    # Once the miss is recorded, the original 02:30 target can never later acquire
    # a file claiming that its prediction existed before the target period.
    assert not FORBIDDEN_RETRO.exists()
