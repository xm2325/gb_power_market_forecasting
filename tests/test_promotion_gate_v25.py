from gb_power_market.promotion_gate_v25 import assess_promotion_readiness


def _monitor(rows: int, *, good: bool = True) -> dict:
    adaptive = 5.0 if good else 15.0
    return {
        "cumulative": {
            "rows": rows,
            "adaptive_mae_gbp_mwh": adaptive,
            "reference_mae_gbp_mwh": 10.0,
            "frozen_mae_gbp_mwh": 12.0,
        },
        "rolling": {
            "last_7d": {
                "adaptive_mae_gbp_mwh": adaptive,
                "reference_mae_gbp_mwh": 10.0,
                "frozen_mae_gbp_mwh": 12.0,
                "adaptive_p95_abs_error_gbp_mwh": 15.0 if good else 30.0,
                "reference_p95_abs_error_gbp_mwh": 20.0,
                "adaptive_signed_bias_gbp_mwh": 2.0 if good else 20.0,
                "frozen_signed_bias_gbp_mwh": 8.0,
            }
        },
        "alert_status": "NO_DEGRADATION_ALERTS" if good else "ALERTS_PRESENT",
        "ledger_integrity": {"status": "LOCKED_PREFIX_REPRODUCED"},
    }


def test_promotion_gate_is_never_evaluated_before_seven_days():
    result = assess_promotion_readiness(_monitor(335))
    assert result["status"] == "NOT_ELIGIBLE_INSUFFICIENT_ROWS"
    assert result["rows_needed"] == 1
    assert result["criteria"] == "NOT_EVALUATED_BEFORE_MINIMUM_SAMPLE"


def test_good_seven_day_candidate_is_only_eligible_for_review():
    result = assess_promotion_readiness(_monitor(336, good=True))
    assert result["status"] == "ELIGIBLE_FOR_REVIEW"
    assert result["failed_criteria"] == []
    assert result["automatic_promotion"] is False


def test_bad_seven_day_candidate_fails_performance_gate():
    result = assess_promotion_readiness(_monitor(336, good=False))
    assert result["status"] == "NOT_ELIGIBLE_PERFORMANCE_GATES"
    assert "cumulative_mae_beats_reference" in result["failed_criteria"]
    assert "last_7d_p95_non_worse_than_reference" in result["failed_criteria"]
    assert "last_7d_bias_non_worse_than_frozen" in result["failed_criteria"]
    assert "no_degradation_alerts" in result["failed_criteria"]


def test_missing_ledger_integrity_blocks_review_eligibility():
    monitor = _monitor(336, good=True)
    monitor["ledger_integrity"] = {"status": "FAILED"}
    result = assess_promotion_readiness(monitor)
    assert result["status"] == "NOT_ELIGIBLE_PERFORMANCE_GATES"
    assert result["failed_criteria"] == ["locked_prefix_reproduced"]
