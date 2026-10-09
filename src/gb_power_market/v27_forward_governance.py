from __future__ import annotations

import json
from pathlib import Path

import pandas as pd


EXPECTED_CANDIDATE = "2H_FROZEN_PLUS_CAUSAL_6H_48H_CONSENSUS_WITH_FROZEN_DIRECTION_VETO"
VALIDATION_END_UTC = pd.Timestamp("2026-08-24T22:00:00Z")
HORIZON_MINUTES = 120
GRID_MINUTES = 30
PASS_STATUS = "ELIGIBLE_TO_CREATE_FRESH_V27_FORWARD_LOCK"


def _utc(value: str | pd.Timestamp) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    if ts.tzinfo is None:
        raise ValueError("v0.27 governance timestamps must be timezone-aware")
    return ts.tz_convert("UTC")


def deterministic_forward_start(lock_timestamp_utc: str | pd.Timestamp) -> pd.Timestamp:
    """Return the unique first target whose decision grid is after the implementation lock.

    The 2h model makes a prediction at target_start - 120 minutes. To prevent a
    post-validation forward boundary from being cherry-picked, the first
    decision time is the next 30-minute grid point *strictly after* the
    implementation-lock timestamp. The first target is exactly two hours later.
    """
    locked = _utc(lock_timestamp_utc)
    next_decision = locked.floor(f"{GRID_MINUTES}min") + pd.Timedelta(minutes=GRID_MINUTES)
    forward_start = next_decision + pd.Timedelta(minutes=HORIZON_MINUTES)
    if next_decision <= locked:
        raise AssertionError("computed v0.27 first decision is not strictly post-lock")
    return forward_start


def verify_forward_launch_preconditions(
    *,
    eligibility_path: Path,
    implementation_lock_timestamp_utc: str | pd.Timestamp,
    proposed_forward_start_utc: str | pd.Timestamp,
) -> dict:
    if not eligibility_path.is_file():
        raise FileNotFoundError("locked v0.27 validation eligibility does not exist")
    eligibility = json.loads(eligibility_path.read_text(encoding="utf-8"))
    if eligibility.get("candidate") != EXPECTED_CANDIDATE:
        raise ValueError("v0.27 eligibility candidate identity changed")
    if eligibility.get("status") != PASS_STATUS or eligibility.get("validation_passed") is not True:
        raise ValueError("v0.27 candidate is not eligible for a fresh forward lock")
    if eligibility.get("automatic_forward_launch") is not False:
        raise ValueError("v0.27 eligibility unexpectedly permits automatic forward launch")
    if _utc(eligibility["validation_end_exclusive_utc"]) != VALIDATION_END_UTC:
        raise ValueError("v0.27 validation end changed in eligibility record")

    lock_time = _utc(implementation_lock_timestamp_utc)
    proposed = _utc(proposed_forward_start_utc)
    expected = deterministic_forward_start(lock_time)
    if proposed != expected:
        raise ValueError(
            f"v0.27 forward start is not deterministic from implementation lock: proposed={proposed.isoformat()}, "
            f"expected={expected.isoformat()}"
        )
    first_decision = proposed - pd.Timedelta(minutes=HORIZON_MINUTES)
    if first_decision <= lock_time:
        raise ValueError("v0.27 first forward decision is not strictly after implementation lock")
    if proposed <= VALIDATION_END_UTC:
        raise ValueError("v0.27 forward start must be strictly after development validation")

    return {
        "status": "FRESH_V27_FORWARD_BOUNDARY_ALLOWED",
        "candidate": EXPECTED_CANDIDATE,
        "implementation_lock_timestamp_utc": lock_time.isoformat(),
        "first_forward_decision_time_utc": first_decision.isoformat(),
        "forward_start_utc": proposed.isoformat(),
        "selection_rule": "next 30-minute decision grid strictly after implementation lock, then +120 minutes",
        "automatic_forward_launch": False,
    }
