from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from gb_power_market.v27_forward_governance import deterministic_forward_start


def test_second_recovery_boundary_is_deterministic_and_model_unchanged() -> None:
    implementation = json.loads(Path("reports/locked/V0_27_IMPLEMENTATION_LOCK.json").read_text())
    previous = json.loads(Path("reports/forward/v27/V0_27_PRETARGET_RECOVERY_LOCK.json").read_text())
    lock_time = pd.Timestamp("2026-08-25T12:43:17Z")
    target = deterministic_forward_start(lock_time)
    assert target == pd.Timestamp("2026-08-25T15:00:00Z")
    assert target - pd.Timedelta(minutes=120) == pd.Timestamp("2026-08-25T13:00:00Z")
    assert implementation["candidate_source"]["git_blob_sha1"] == previous["predictive_source_git_blob_sha1"]
    assert previous["original_forward_boundary_changed"] is False
    assert previous["model_or_rule_changed_for_recovery"] is False


def test_original_forward_start_remains_0230() -> None:
    implementation = json.loads(Path("reports/locked/V0_27_IMPLEMENTATION_LOCK.json").read_text())
    assert implementation["forward_start_utc"] == "2026-08-25T02:30:00+00:00"
