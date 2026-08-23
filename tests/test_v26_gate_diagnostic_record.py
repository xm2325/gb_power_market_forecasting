import json
from pathlib import Path


REPORT = Path("reports/monitoring/V0_26_GATE_DIAGNOSTIC_2026-08-23_0800Z.json")
REGISTRY = Path("reports/monitoring/V0_26_FORWARD_SNAPSHOT_REGISTRY.json")


def test_gate_diagnostic_is_tied_to_locked_sequence_two() -> None:
    report = json.loads(REPORT.read_text(encoding="utf-8"))
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    snap = registry["snapshots"][1]

    assert report["schema"] == "gb-power-market-v26-gate-diagnostic-v1"
    assert report["status"] == "POST_LOCK_DESCRIPTIVE_DIAGNOSTIC"
    assert report["monitoring_only"] is True
    assert report["locked_snapshot_sequence"] == 2
    assert report["rows"] == snap["rows"] == 23
    assert report["end_exclusive_utc"] == snap["end_exclusive_utc"]
    assert report["source"]["workflow_run_id"] == snap["run_id"]
    assert report["source"]["artifact_id"] == snap["artifact_id"]
    assert report["source"]["artifact_sha256"] == snap["artifact_sha256"]


def test_gate_diagnostic_counts_are_internally_consistent() -> None:
    report = json.loads(REPORT.read_text(encoding="utf-8"))
    gate = report["gate"]
    effect = report["fallback_effect_vs_v25"]

    assert gate["correction_applied_rows"] + gate["fallback_rows"] == report["rows"]
    assert sum(gate["gate_reason_counts"].values()) == report["rows"]
    assert (
        effect["fallback_rows_v25_worse_than_frozen"]
        + effect["fallback_rows_v25_better_than_frozen"]
        + effect["fallback_rows_v25_tied_with_frozen"]
        == gate["fallback_rows"]
    )
    assert report["integrity"]["prediction_reconstruction_max_abs_diff_gbp_mwh"] == 0.0
    assert report["integrity"]["predictive_source_changed"] is False
    assert report["integrity"]["frozen_model_state_changed"] is False
