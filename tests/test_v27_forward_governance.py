import json
from pathlib import Path

import pandas as pd
import pytest

from gb_power_market.v27_forward_governance import (
    EXPECTED_CANDIDATE,
    deterministic_forward_start,
    verify_forward_launch_preconditions,
)


def _eligibility(path: Path, *, passed: bool) -> Path:
    path.write_text(
        json.dumps(
            {
                "candidate": EXPECTED_CANDIDATE,
                "status": (
                    "ELIGIBLE_TO_CREATE_FRESH_V27_FORWARD_LOCK"
                    if passed
                    else "CANDIDATE_REJECTED_ON_SEALED_BLOCK"
                ),
                "validation_passed": passed,
                "automatic_forward_launch": False,
                "validation_end_exclusive_utc": "2026-08-24T22:00:00+00:00",
            }
        ),
        encoding="utf-8",
    )
    return path


def test_forward_start_uses_next_decision_grid_strictly_after_lock() -> None:
    assert deterministic_forward_start("2026-08-24T23:42:10Z") == pd.Timestamp("2026-08-25T02:00:00Z")
    assert deterministic_forward_start("2026-08-24T23:30:00Z") == pd.Timestamp("2026-08-25T02:00:00Z")
    assert deterministic_forward_start("2026-08-24T23:29:59Z") == pd.Timestamp("2026-08-25T01:30:00Z")


def test_passed_validation_allows_only_the_deterministic_boundary(tmp_path: Path) -> None:
    eligibility = _eligibility(tmp_path / "eligibility.json", passed=True)
    result = verify_forward_launch_preconditions(
        eligibility_path=eligibility,
        implementation_lock_timestamp_utc="2026-08-24T23:42:10Z",
        proposed_forward_start_utc="2026-08-25T02:00:00Z",
    )
    assert result["status"] == "FRESH_V27_FORWARD_BOUNDARY_ALLOWED"
    assert result["first_forward_decision_time_utc"] == "2026-08-25T00:00:00+00:00"
    assert result["automatic_forward_launch"] is False

    with pytest.raises(ValueError, match="not deterministic"):
        verify_forward_launch_preconditions(
            eligibility_path=eligibility,
            implementation_lock_timestamp_utc="2026-08-24T23:42:10Z",
            proposed_forward_start_utc="2026-08-25T02:30:00Z",
        )


def test_failed_validation_can_never_create_forward_lock(tmp_path: Path) -> None:
    eligibility = _eligibility(tmp_path / "eligibility.json", passed=False)
    with pytest.raises(ValueError, match="not eligible"):
        verify_forward_launch_preconditions(
            eligibility_path=eligibility,
            implementation_lock_timestamp_utc="2026-08-24T23:42:10Z",
            proposed_forward_start_utc="2026-08-25T02:00:00Z",
        )


def test_missing_locked_validation_result_blocks_forward(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        verify_forward_launch_preconditions(
            eligibility_path=tmp_path / "missing.json",
            implementation_lock_timestamp_utc="2026-08-24T23:42:10Z",
            proposed_forward_start_utc="2026-08-25T02:00:00Z",
        )
