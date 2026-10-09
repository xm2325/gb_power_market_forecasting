"""Same-target descriptive comparison of independent v0.28 and v0.29 streams.

No model selection or retroactive prediction is allowed. Comparisons require
two genuinely precommitted scored targets with close actual issue timestamps.
"""
from __future__ import annotations

from typing import Any
import numpy as np
import pandas as pd

from gb_power_market.prospective_v28 import utc

METHODS = (
    "previous_day",
    "v28_consensus", "v28_direction_veto",
    "v29_ridge_delay_safe", "v29_ridge_consensus", "v29_ridge_direction_veto",
)


def compare_streams(
    v28_scores: dict[str, dict[str, Any]],
    v29_scores: dict[str, dict[str, Any]],
    v28_predictions: dict[str, dict[str, Any]],
    v29_predictions: dict[str, dict[str, Any]],
    *,
    max_issue_gap_minutes: float = 15.0,
) -> dict[str, Any]:
    if max_issue_gap_minutes <= 0:
        raise ValueError("maximum issue gap must be positive")
    intersection = sorted(set(v28_scores) & set(v29_scores))
    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, str]] = []
    for key in intersection:
        s28, s29 = v28_scores[key], v29_scores[key]
        p28, p29 = v28_predictions.get(key), v29_predictions.get(key)
        if not p28 or not p29:
            rejected.append({"target": key, "reason": "MISSING_PRETARGET_RECORD"})
            continue
        try:
            t28, t29 = utc(p28["target_start_utc"]), utc(p29["target_start_utc"])
            target = utc(key)
            issue28, issue29 = utc(p28["decision_time_utc"]), utc(p29["decision_time_utc"])
            if t28 != target or t29 != target or issue28 >= target or issue29 >= target:
                raise ValueError("INVALID_TARGET_OR_ISSUE_TIMING")
            if s28.get("evidence_class") != "SCORED_GENUINE_PRETARGET_SHADOW":
                raise ValueError("V28_NOT_PRETARGET_SCORED")
            if s29.get("evidence_class") != "SCORED_LIVE_FORWARD_WITH_DELAY_SAFE_FEATURES":
                raise ValueError("V29_NOT_PRETARGET_SCORED")
            if not s29.get("prediction_verified_pretarget"):
                raise ValueError("V29_COMMIT_NOT_VERIFIED")
            if not s28.get("prediction_sha256") or not s29.get("prediction_sha256"):
                raise ValueError("MISSING_PREDICTION_FINGERPRINT")
            if abs(float(s28["realised_price_gbp_mwh"]) - float(s29["realised_price_gbp_mwh"])) > 1e-8:
                raise ValueError("REVISED_REALIZED_PRICE_DISAGREEMENT")
            if abs(float(p28["forecast_gbp_mwh"]["previous_day"]) -
                   float(p29["forecast_gbp_mwh"]["previous_day"])) > 1e-8:
                raise ValueError("DIFFERENT_PREVIOUS_DAY_REFERENCE")
            gap = abs(float((issue29 - issue28).total_seconds() / 60))
            if gap > max_issue_gap_minutes:
                raise ValueError("ISSUE_TIMES_TOO_FAR_APART")
            forecasts = {
                "previous_day": float(p28["forecast_gbp_mwh"]["previous_day"]),
                "v28_consensus": float(p28["forecast_gbp_mwh"]["consensus"]),
                "v28_direction_veto": float(p28["forecast_gbp_mwh"]["direction_veto"]),
                "v29_ridge_delay_safe": float(p29["forecast_gbp_mwh"]["ridge_delay_safe"]),
                "v29_ridge_consensus": float(p29["forecast_gbp_mwh"]["ridge_consensus"]),
                "v29_ridge_direction_veto": float(p29["forecast_gbp_mwh"]["ridge_direction_veto"]),
            }
            realized = float(s28["realised_price_gbp_mwh"])
            if not np.isfinite(list(forecasts.values())).all():
                raise ValueError("NONFINITE_FORECAST")
            accepted.append({
                "target_start_utc": target.isoformat(),
                "issue_gap_minutes": gap,
                "observed_price_gbp_mwh": realized,
                "absolute_error": {name: abs(value - realized) for name, value in forecasts.items()},
                "signed_error": {name: value - realized for name, value in forecasts.items()},
            })
        except (ValueError, KeyError, TypeError) as exc:
            rejected.append({"target": key, "reason": str(exc)})

    def mae(model: str) -> float | None:
        return float(np.mean([x["absolute_error"][model] for x in accepted])) if accepted else None
    def p95(model: str) -> float | None:
        return float(np.quantile([x["absolute_error"][model] for x in accepted], 0.95)) if accepted else None
    def bias(model: str) -> float | None:
        return float(np.mean([x["signed_error"][model] for x in accepted])) if accepted else None

    baseline = mae("previous_day")
    return {
        "schema": "gb-power-v29-paired-stream-comparison-v1",
        "status": "MATCHED_SCORES_AVAILABLE" if accepted else "WAIT_FOR_MATCHED_SCORES",
        "v28_scored_targets": len(v28_scores),
        "v29_scored_targets": len(v29_scores),
        "common_target_candidates": len(intersection),
        "matched_rows": len(accepted),
        "rejected_pairs": rejected,
        "max_issue_gap_minutes": max_issue_gap_minutes,
        "first_matched_target_utc": accepted[0]["target_start_utc"] if accepted else None,
        "last_matched_target_utc": accepted[-1]["target_start_utc"] if accepted else None,
        "mae_gbp_mwh": {name: mae(name) for name in METHODS},
        "p95_abs_error_gbp_mwh": {name: p95(name) for name in METHODS},
        "signed_bias_gbp_mwh": {name: bias(name) for name in METHODS},
        "mae_gain_vs_previous_day_gbp_mwh": {
            name: float(baseline - mae(name)) if accepted else None
            for name in METHODS if name != "previous_day"
        },
        "mean_issue_gap_minutes": (
            float(np.mean([x["issue_gap_minutes"] for x in accepted])) if accepted else None
        ),
        "review_mature": len(accepted) >= 336,
        "automatic_promotion": False,
        "evidence_class": "GITHUB_LIVE_MATCHED_TARGETS_WITH_NONIDENTICAL_ISSUE_TIMES",
        "claim_boundary": (
            "Descriptive matched-target forecasting evidence only. Forecast issue instants differ and "
            "inputs may differ even when previous-day baselines match; not an identical-information-set "
            "causal model comparison, trading return, or automatic deployment claim."
        ),
    }
