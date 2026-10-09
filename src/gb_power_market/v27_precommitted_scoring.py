from __future__ import annotations

from typing import Any

import pandas as pd

SAFE_LAG_MINUTES = 90
EXPECTED_STATUS = "RECOVERY_PREDICTION_FROZEN_BEFORE_TARGET_OUTCOME"
EXPECTED_LABEL_STATUS = "UNOBSERVED_NOT_ACCESSED"
EXPECTED_EVIDENCE_CLASS = "PRE_TARGET_GIT_COMMITTED_PREDICTION_NOT_YET_SCORED"


def _utc(value: str | pd.Timestamp) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    if ts.tzinfo is None:
        raise ValueError("v0.27 scoring timestamp must be timezone-aware")
    return ts.tz_convert("UTC")


def scoring_safe_boundary(target_start_utc: str | pd.Timestamp) -> pd.Timestamp:
    return _utc(target_start_utc) + pd.Timedelta(minutes=SAFE_LAG_MINUTES)


def verify_scoring_maturity(*, prediction: dict[str, Any], now_utc: str | pd.Timestamp) -> dict[str, str]:
    if prediction.get("status") != EXPECTED_STATUS:
        raise ValueError("prediction is not an immutable pre-target recovery prediction")
    if prediction.get("target_label_status") != EXPECTED_LABEL_STATUS:
        raise ValueError("prediction target-label state is not the original unobserved state")
    if prediction.get("realised_price_in_prediction_record") is not False:
        raise ValueError("prediction record already contains realised outcome")
    if prediction.get("evidence_class") != EXPECTED_EVIDENCE_CLASS:
        raise ValueError("prediction evidence class changed before scoring")

    target = _utc(prediction["target_start_utc"])
    decision = _utc(prediction["decision_time_utc"])
    frozen_at = _utc(prediction["freeze_completed_utc"])
    if target - decision != pd.Timedelta(minutes=120):
        raise ValueError("prediction is not a 2h decision-to-target record")
    if frozen_at >= target:
        raise ValueError("prediction was not frozen before its target began")

    safe = scoring_safe_boundary(target)
    now = _utc(now_utc)
    if now < safe:
        raise RuntimeError(
            f"V27_PRECOMMITTED_OUTCOME_NOT_MATURE: now={now.isoformat()} safe_boundary={safe.isoformat()}"
        )
    return {
        "now_utc": now.isoformat(),
        "target_start_utc": target.isoformat(),
        "safe_scoring_boundary_utc": safe.isoformat(),
    }


def score_precommitted_prediction(*, prediction: dict[str, Any], realised_price_gbp_mwh: float) -> dict[str, Any]:
    realised = float(realised_price_gbp_mwh)
    v27 = float(prediction["v27_prediction_gbp_mwh"])
    frozen = float(prediction["frozen_prediction_gbp_mwh"])
    reference = float(prediction["previous_settlement_day_reference_gbp_mwh"])

    return {
        "schema": "gb-power-market-v27-precommitted-outcome-score-v1",
        "status": "ONE_PRECOMMITTED_FORWARD_OUTCOME_SCORED",
        "version": "0.27.0",
        "candidate": prediction["candidate"],
        "target_start_utc": prediction["target_start_utc"],
        "decision_time_utc": prediction["decision_time_utc"],
        "prediction_freeze_completed_utc": prediction["freeze_completed_utc"],
        "realised_price_gbp_mwh": realised,
        "v27_prediction_gbp_mwh": v27,
        "frozen_prediction_gbp_mwh": frozen,
        "previous_settlement_day_reference_gbp_mwh": reference,
        "v27_absolute_error_gbp_mwh": abs(realised - v27),
        "frozen_absolute_error_gbp_mwh": abs(realised - frozen),
        "reference_absolute_error_gbp_mwh": abs(realised - reference),
        "v27_minus_frozen_absolute_error_gbp_mwh": abs(realised - v27) - abs(realised - frozen),
        "v27_minus_reference_absolute_error_gbp_mwh": abs(realised - v27) - abs(realised - reference),
        "evidence_class": "SINGLE_PRECOMMITTED_FORWARD_OUTCOME_DESCRIPTIVE_ONLY",
        "promotion_eligible": False,
        "automatic_model_change": False,
        "claim_boundary": (
            "This is one genuinely precommitted forward outcome. It is descriptive evidence only: one row cannot "
            "establish superiority, trigger promotion, tune v0.27 or change the frozen comparison model."
        ),
    }
