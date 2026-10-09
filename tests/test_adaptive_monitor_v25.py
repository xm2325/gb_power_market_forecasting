import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from gb_power_market.adaptive_monitor_v25 import (
    AdaptiveMonitoringPolicy,
    build_adaptive_monitor_state,
    maturity_stage,
)


def _rows(n: int, *, adaptive_offset: float = 0.0, frozen_offset: float = 10.0, reference_offset: float = 5.0):
    target = pd.date_range("2026-08-21T11:30:00Z", periods=n, freq="30min")
    realised = np.linspace(100.0, 130.0, n)
    return pd.DataFrame({
        "target_start_utc": target,
        "realised_price_gbp_mwh": realised,
        "frozen_prediction_gbp_mwh": realised + frozen_offset,
        "adaptive_prediction_gbp_mwh": realised + adaptive_offset,
        "previous_settlement_day_reference_gbp_mwh": realised + reference_offset,
        "bias_correction_gbp_mwh": np.full(n, adaptive_offset - frozen_offset),
    })


def test_maturity_stages_are_sample_size_only():
    assert maturity_stage(0) == "EARLY_ONLY"
    assert maturity_stage(23) == "EARLY_ONLY"
    assert maturity_stage(24) == "INTRADAY_TO_2DAY_MONITORING"
    assert maturity_stage(95) == "INTRADAY_TO_2DAY_MONITORING"
    assert maturity_stage(96) == "MULTIDAY_MONITORING"
    assert maturity_stage(335) == "MULTIDAY_MONITORING"
    assert maturity_stage(336) == "ONE_WEEK_PLUS_FORWARD"


def test_six_rows_never_emit_performance_alerts():
    state = build_adaptive_monitor_state(
        _rows(6, adaptive_offset=100.0),
        forward_start_utc="2026-08-21T11:30:00Z",
        candidate_id="candidate",
    )
    assert state["maturity_stage"] == "EARLY_ONLY"
    assert state["alert_status"] == "INSUFFICIENT_SAMPLE_FOR_ALERTS"
    assert state["alerts"] == []
    assert state["rolling"]["last_24h"]["status"] == "INSUFFICIENT_ROWS_NEED_48"


def test_48_rows_emit_predeclared_degradation_alerts():
    state = build_adaptive_monitor_state(
        _rows(48, adaptive_offset=20.0, frozen_offset=10.0, reference_offset=5.0),
        forward_start_utc="2026-08-21T11:30:00Z",
        candidate_id="candidate",
    )
    assert state["alert_status"] == "ALERTS_PRESENT"
    assert set(state["alerts"]) == {
        "ADAPTIVE_TRAILS_REFERENCE_24H",
        "ADAPTIVE_TRAILS_FROZEN_24H",
        "BIAS_CORRECTION_WORSENED_24H",
    }


def test_good_48_row_candidate_has_no_degradation_alerts():
    state = build_adaptive_monitor_state(
        _rows(48, adaptive_offset=1.0, frozen_offset=10.0, reference_offset=5.0),
        forward_start_utc="2026-08-21T11:30:00Z",
        candidate_id="candidate",
    )
    assert state["alert_status"] == "NO_DEGRADATION_ALERTS"
    assert state["alerts"] == []
    assert state["rolling"]["last_24h"]["adaptive_mae_gbp_mwh"] == 1.0


def test_monitor_reports_tail_metrics_and_lineage():
    state = build_adaptive_monitor_state(
        _rows(144, adaptive_offset=2.0),
        forward_start_utc="2026-08-21T11:30:00Z",
        candidate_id="candidate",
        previous_snapshot_sha256="abc123",
        policy=AdaptiveMonitoringPolicy(),
    )
    assert state["maturity_stage"] == "MULTIDAY_MONITORING"
    assert state["cumulative"]["rows"] == 144
    assert state["rolling"]["last_6h"]["rows"] == 12
    assert state["rolling"]["last_24h"]["rows"] == 48
    assert state["rolling"]["last_3d"]["rows"] == 144
    assert state["rolling"]["last_7d"]["status"] == "INSUFFICIENT_ROWS_NEED_336"
    assert state["cumulative"]["adaptive_p95_abs_error_gbp_mwh"] == 2.0
    assert state["lineage"]["previous_snapshot_sha256"] == "abc123"


def test_monitor_reports_translated_interval_coverage_without_changing_width():
    x = _rows(48, adaptive_offset=1.0)
    x["adaptive_interval_covered"] = True
    x["adaptive_interval_width_gbp_mwh"] = 40.0
    x["interval_covered"] = np.arange(48) % 2 == 0
    x["interval_lower_gbp_mwh"] = x["frozen_prediction_gbp_mwh"] - 20.0
    x["interval_upper_gbp_mwh"] = x["frozen_prediction_gbp_mwh"] + 20.0
    state = build_adaptive_monitor_state(
        x,
        forward_start_utc="2026-08-21T11:30:00Z",
        candidate_id="candidate",
    )
    m = state["cumulative"]
    assert m["adaptive_interval_coverage"] == 1.0
    assert m["frozen_interval_coverage"] == 0.5
    assert m["adaptive_minus_frozen_interval_coverage"] == 0.5
    assert m["adaptive_interval_mean_width_gbp_mwh"] == 40.0
    assert m["frozen_interval_mean_width_gbp_mwh"] == 40.0


def test_duplicate_targets_fail_closed():
    x = _rows(50)
    x.loc[1, "target_start_utc"] = x.loc[0, "target_start_utc"]
    try:
        build_adaptive_monitor_state(
            x,
            forward_start_utc="2026-08-21T11:30:00Z",
            candidate_id="candidate",
        )
    except ValueError as exc:
        assert "duplicate" in str(exc)
    else:
        raise AssertionError("expected duplicate-target validation to fail")


def test_first_monitor_snapshot_is_locked_and_still_early_only():
    path = Path("reports/monitoring/V0_25_MONITOR_STATE_2026-08-21_1430Z.json")
    sidecar = Path(str(path) + ".sha256")
    expected = sidecar.read_text(encoding="utf-8").split()[0]
    assert hashlib.sha256(path.read_bytes()).hexdigest() == expected

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["cumulative"]["rows"] == 6
    assert payload["maturity_stage"] == "EARLY_ONLY"
    assert payload["alert_status"] == "INSUFFICIENT_SAMPLE_FOR_ALERTS"
    assert payload["alerts"] == []
    assert payload["lineage"]["source_workflow_run_id"] == 32500771812
