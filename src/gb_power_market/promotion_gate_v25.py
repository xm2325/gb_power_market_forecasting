from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class PromotionReadinessPolicy:
    """Predeclared evidence gate for reviewing the unchanged v0.25 candidate."""

    minimum_forward_rows: int = 336
    require_locked_prefix_reproduced: bool = True
    require_no_degradation_alerts: bool = True


def assess_promotion_readiness(
    monitor_state: dict,
    *,
    policy: PromotionReadinessPolicy = PromotionReadinessPolicy(),
) -> dict:
    cumulative = monitor_state.get("cumulative", {})
    rows = int(cumulative.get("rows", 0))
    result = {
        "policy": asdict(policy),
        "rows_observed": rows,
        "decision_contract": (
            "This gate never promotes a model automatically. It only marks the unchanged v0.25 candidate "
            "eligible for human review after at least seven days of half-hourly forward observations. "
            "MAE must be strictly lower than both baselines; P95 error and absolute signed bias must be "
            "non-worse than the stated comparator. No post-hoc percentage margin is used."
        ),
    }

    if rows < policy.minimum_forward_rows:
        result.update({
            "status": "NOT_ELIGIBLE_INSUFFICIENT_ROWS",
            "rows_needed": int(policy.minimum_forward_rows - rows),
            "criteria": "NOT_EVALUATED_BEFORE_MINIMUM_SAMPLE",
        })
        return result

    last7 = monitor_state.get("rolling", {}).get("last_7d", {})
    ledger = monitor_state.get("ledger_integrity", {})
    criteria = {
        "cumulative_mae_beats_reference": (
            cumulative["adaptive_mae_gbp_mwh"] < cumulative["reference_mae_gbp_mwh"]
        ),
        "cumulative_mae_beats_frozen": (
            cumulative["adaptive_mae_gbp_mwh"] < cumulative["frozen_mae_gbp_mwh"]
        ),
        "last_7d_mae_beats_reference": (
            last7["adaptive_mae_gbp_mwh"] < last7["reference_mae_gbp_mwh"]
        ),
        "last_7d_mae_beats_frozen": (
            last7["adaptive_mae_gbp_mwh"] < last7["frozen_mae_gbp_mwh"]
        ),
        "last_7d_p95_non_worse_than_reference": (
            last7["adaptive_p95_abs_error_gbp_mwh"] <= last7["reference_p95_abs_error_gbp_mwh"]
        ),
        "last_7d_bias_non_worse_than_frozen": (
            abs(last7["adaptive_signed_bias_gbp_mwh"]) <= abs(last7["frozen_signed_bias_gbp_mwh"])
        ),
        "no_degradation_alerts": (
            monitor_state.get("alert_status") == "NO_DEGRADATION_ALERTS"
            if policy.require_no_degradation_alerts
            else True
        ),
        "locked_prefix_reproduced": (
            ledger.get("status") == "LOCKED_PREFIX_REPRODUCED"
            if policy.require_locked_prefix_reproduced
            else True
        ),
    }
    failed = [name for name, passed in criteria.items() if not passed]
    result.update({
        "status": "ELIGIBLE_FOR_REVIEW" if not failed else "NOT_ELIGIBLE_PERFORMANCE_GATES",
        "criteria": criteria,
        "failed_criteria": failed,
        "automatic_promotion": False,
    })
    return result
