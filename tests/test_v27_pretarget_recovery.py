from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from gb_power_market.v27_pretarget_recovery import build_pretarget_recovery_lock


IMPLEMENTATION = json.loads(Path("reports/locked/V0_27_IMPLEMENTATION_LOCK.json").read_text(encoding="utf-8"))
MISS = json.loads(Path("reports/forward/v27/V0_27_FIRST_PRETARGET_FREEZE_MISSED.json").read_text(encoding="utf-8"))


def test_recovery_boundary_is_strictly_post_lock_and_does_not_move_original_start() -> None:
    recovery = build_pretarget_recovery_lock(
        implementation_lock=IMPLEMENTATION,
        miss_record=MISS,
        recovery_lock_timestamp_utc="2026-08-25T09:38:01Z",
    )
    assert recovery["original_forward_start_utc"] == IMPLEMENTATION["forward_start_utc"]
    assert recovery["original_forward_boundary_changed"] is False
    assert recovery["recovery_decision_time_utc"] == "2026-08-25T10:00:00+00:00"
    assert recovery["recovery_target_start_utc"] == "2026-08-25T12:00:00+00:00"
    assert recovery["model_or_rule_changed_for_recovery"] is False
    assert recovery["target_outcome_accessed_to_select_recovery_boundary"] is False
    assert recovery["automatic_prediction_launch"] is False


def test_exact_grid_lock_still_moves_to_next_grid() -> None:
    recovery = build_pretarget_recovery_lock(
        implementation_lock=IMPLEMENTATION,
        miss_record=MISS,
        recovery_lock_timestamp_utc="2026-08-25T10:00:00Z",
    )
    assert recovery["recovery_decision_time_utc"] == "2026-08-25T10:30:00+00:00"
    assert recovery["recovery_target_start_utc"] == "2026-08-25T12:30:00+00:00"


def test_recovery_cannot_be_backdated_before_missed_target() -> None:
    with pytest.raises(ValueError, match="after the missed target"):
        build_pretarget_recovery_lock(
            implementation_lock=IMPLEMENTATION,
            miss_record=MISS,
            recovery_lock_timestamp_utc=pd.Timestamp("2026-08-25T02:00:00Z"),
        )
