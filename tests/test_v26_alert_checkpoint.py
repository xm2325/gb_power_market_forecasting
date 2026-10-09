import json
from pathlib import Path

import pandas as pd
import pytest

from gb_power_market.v26_alert_root_cause import summarise_v26_alert_root_cause


REPORT = Path("reports/monitoring/V0_26_ALERT_ROOT_CAUSE_2026-08-23_2200Z.json")
LEDGER = Path("reports/monitoring/V0_26_FORWARD_LEDGER_2026-08-23_2200Z.csv")


def test_v26_alert_checkpoint_reproduces_locked_sequence_three() -> None:
    report = json.loads(REPORT.read_text(encoding="utf-8"))
    ledger = pd.read_csv(LEDGER)
    result = summarise_v26_alert_root_cause(ledger)

    assert report["schema"] == "gb-power-market-v26-alert-root-cause-v1"
    assert report["locked_snapshot_sequence"] == 3
    assert report["rows"] == 51 == result["rows"]
    assert report["alerts"] == [
        "V26_TRAILS_FROZEN_24H",
        "V26_BIAS_WORSE_THAN_FROZEN_24H",
    ]

    root = report["root_cause"]
    assert root["correction_applied_rows"] == result["correction_applied_rows"] == 17
    assert root["fallback_rows"] == result["fallback_rows"] == 34
    assert root["applied_rows_candidate_better_than_frozen"] == result[
        "applied_rows_candidate_better_than_frozen"
    ] == 4
    assert root["applied_rows_candidate_worse_than_frozen"] == result[
        "applied_rows_candidate_worse_than_frozen"
    ] == 13
    assert root["candidate_excess_abs_error_vs_frozen_gbp_mwh"] == pytest.approx(
        result["candidate_excess_abs_error_vs_frozen_gbp_mwh"]
    )
    assert root["harmful_applied_excess_abs_error_gbp_mwh"] == pytest.approx(
        result["harmful_applied_excess_abs_error_gbp_mwh"]
    )
    assert root["helpful_applied_abs_error_saved_gbp_mwh"] == pytest.approx(
        result["helpful_applied_abs_error_saved_gbp_mwh"]
    )

    expected_run = root["longest_applied_run"]
    reproduced_run = result["longest_applied_run"]
    assert reproduced_run is not None
    for key in (
        "rows",
        "start_utc",
        "end_utc",
        "candidate_better_rows",
        "candidate_worse_rows",
        "negative_correction_rows",
        "positive_correction_rows",
    ):
        assert expected_run[key] == reproduced_run[key]
    for key in (
        "candidate_excess_abs_error_vs_frozen_gbp_mwh",
        "mean_abs_correction_gbp_mwh",
        "realised_start_gbp_mwh",
        "realised_end_gbp_mwh",
        "frozen_start_gbp_mwh",
        "frozen_end_gbp_mwh",
        "short_residual_mean_start_gbp_mwh",
        "short_residual_mean_end_gbp_mwh",
        "long_residual_mean_start_gbp_mwh",
        "long_residual_mean_end_gbp_mwh",
    ):
        assert expected_run[key] == pytest.approx(reproduced_run[key])

    assert report["monitoring_decision"]["champion"] == "UNCHANGED_FROZEN_V0_20_2H"
    assert report["monitoring_decision"]["action"] == "KEEP_FROZEN_CHAMPION_AND_DO_NOT_RETUNE_V0_26"
