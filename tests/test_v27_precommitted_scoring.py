from __future__ import annotations

import pytest

from gb_power_market.v27_precommitted_scoring import (
    score_precommitted_prediction,
    verify_scoring_maturity,
)


def _prediction() -> dict:
    return {
        "status": "RECOVERY_PREDICTION_FROZEN_BEFORE_TARGET_OUTCOME",
        "version": "0.27.0",
        "candidate": "2H_FROZEN_PLUS_CAUSAL_6H_48H_CONSENSUS_WITH_FROZEN_DIRECTION_VETO",
        "target_start_utc": "2026-08-25T15:00:00+00:00",
        "decision_time_utc": "2026-08-25T13:00:00+00:00",
        "freeze_completed_utc": "2026-08-25T13:02:15+00:00",
        "v27_prediction_gbp_mwh": 80.0,
        "frozen_prediction_gbp_mwh": 85.0,
        "previous_settlement_day_reference_gbp_mwh": 70.0,
        "target_label_status": "UNOBSERVED_NOT_ACCESSED",
        "realised_price_in_prediction_record": False,
        "evidence_class": "PRE_TARGET_GIT_COMMITTED_PREDICTION_NOT_YET_SCORED",
    }


def test_scoring_gate_opens_exactly_90_minutes_after_target() -> None:
    p = _prediction()
    with pytest.raises(RuntimeError, match="NOT_MATURE"):
        verify_scoring_maturity(prediction=p, now_utc="2026-08-25T16:29:59Z")
    state = verify_scoring_maturity(prediction=p, now_utc="2026-08-25T16:30:00Z")
    assert state["safe_scoring_boundary_utc"] == "2026-08-25T16:30:00+00:00"


def test_scoring_refuses_non_precommitted_prediction() -> None:
    p = _prediction()
    p["freeze_completed_utc"] = "2026-08-25T15:00:00+00:00"
    with pytest.raises(ValueError, match="not frozen before"):
        verify_scoring_maturity(prediction=p, now_utc="2026-08-25T16:30:00Z")


def test_single_outcome_is_descriptive_only() -> None:
    score = score_precommitted_prediction(prediction=_prediction(), realised_price_gbp_mwh=90.0)
    assert score["v27_absolute_error_gbp_mwh"] == 10.0
    assert score["frozen_absolute_error_gbp_mwh"] == 5.0
    assert score["reference_absolute_error_gbp_mwh"] == 20.0
    assert score["v27_minus_frozen_absolute_error_gbp_mwh"] == 5.0
    assert score["promotion_eligible"] is False
    assert score["automatic_model_change"] is False
    assert score["evidence_class"] == "SINGLE_PRECOMMITTED_FORWARD_OUTCOME_DESCRIPTIVE_ONLY"
