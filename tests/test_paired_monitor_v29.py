"""Synthetic-only checks for matched-target reporting; no synthetic market claim."""
from __future__ import annotations

import copy
import pytest
import pandas as pd

from gb_power_market.paired_monitor_v29 import compare_streams


def _sample():
    target = pd.Timestamp("2026-10-10T02:00:00Z").isoformat()
    pred28 = {
        "target_start_utc": target, "decision_time_utc": "2026-10-09T23:32:00Z",
        "forecast_gbp_mwh": {"previous_day": 40.0, "consensus": 48.0, "direction_veto": 50.0},
    }
    pred29 = {
        "target_start_utc": target, "decision_time_utc": "2026-10-09T23:38:00Z",
        "forecast_gbp_mwh": {
            "previous_day": 40.0, "ridge_delay_safe": 46.0,
            "ridge_consensus": 47.0, "ridge_direction_veto": 47.0,
        },
    }
    score28 = {
        "target_start_utc": target,
        "evidence_class": "SCORED_GENUINE_PRETARGET_SHADOW",
        "prediction_sha256": "aa",
        "realised_price_gbp_mwh": 55.0,
    }
    score29 = {
        "target_start_utc": target,
        "evidence_class": "SCORED_LIVE_FORWARD_WITH_DELAY_SAFE_FEATURES",
        "prediction_sha256": "bb",
        "prediction_verified_pretarget": True,
        "realised_price_gbp_mwh": 55.0,
    }
    return target, score28, score29, pred28, pred29


def _compare(target, s28, s29, p28, p29):
    return compare_streams(
        {target: s28}, {target: s29}, {target: p28}, {target: p29},
    )


def test_paired_comparison_is_descriptive_and_uses_same_target():
    target, s28, s29, p28, p29 = _sample()
    report = _compare(target, s28, s29, p28, p29)
    assert report["matched_rows"] == 1
    assert report["status"] == "MATCHED_SCORES_AVAILABLE"
    assert report["mae_gbp_mwh"]["previous_day"] == pytest.approx(15.)
    assert report["mae_gbp_mwh"]["v29_ridge_delay_safe"] == pytest.approx(9.)
    assert report["mae_gain_vs_previous_day_gbp_mwh"]["v29_ridge_delay_safe"] == pytest.approx(6.)
    assert report["mean_issue_gap_minutes"] == pytest.approx(6.)
    assert not report["review_mature"]
    assert report["automatic_promotion"] is False


def test_revised_realised_price_is_rejected():
    target, s28, s29, p28, p29 = _sample()
    s29["realised_price_gbp_mwh"] = 60.
    report = _compare(target, s28, s29, p28, p29)
    assert report["matched_rows"] == 0
    assert report["rejected_pairs"][0]["reason"] == "REVISED_REALIZED_PRICE_DISAGREEMENT"


def test_large_issue_gap_is_excluded():
    target, s28, s29, p28, p29 = _sample()
    p29["decision_time_utc"] = "2026-10-09T23:59:00Z"
    report = _compare(target, s28, s29, p28, p29)
    assert report["matched_rows"] == 0
    assert report["rejected_pairs"][0]["reason"] == "ISSUE_TIMES_TOO_FAR_APART"


def test_different_snapshot_baseline_is_excluded():
    target, s28, s29, p28, p29 = _sample()
    p29["forecast_gbp_mwh"]["previous_day"] = 41
    report = _compare(target, s28, s29, p28, p29)
    assert report["matched_rows"] == 0
    assert report["rejected_pairs"][0]["reason"] == "DIFFERENT_PREVIOUS_DAY_REFERENCE"


def test_missing_commit_evidence_excludes_record():
    target, s28, s29, p28, p29 = _sample()
    s29["prediction_verified_pretarget"] = False
    report = _compare(target, s28, s29, p28, p29)
    assert report["matched_rows"] == 0
    assert report["rejected_pairs"][0]["reason"] == "V29_COMMIT_NOT_VERIFIED"


def test_no_scores_does_not_invent_performance():
    report = compare_streams({}, {}, {}, {})
    assert report["status"] == "WAIT_FOR_MATCHED_SCORES"
    assert report["matched_rows"] == 0
    assert report["mae_gbp_mwh"]["previous_day"] is None
