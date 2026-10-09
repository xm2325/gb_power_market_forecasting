import json
from pathlib import Path

import pandas as pd


PROTOCOL = Path("reports/locked/V0_27_DEVELOPMENT_PROTOCOL.json")
REGISTRY = Path("reports/monitoring/V0_26_FORWARD_SNAPSHOT_REGISTRY.json")


def test_v27_protocol_separates_discovery_validation_and_forward_evidence() -> None:
    protocol = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    discovery = protocol["v26_discovery_evidence"]
    latest = registry["snapshots"][-1]
    validation = protocol["independent_development_validation"]
    gate = protocol["validation_gate"]
    forward = protocol["v27_forward_contract"]

    assert protocol["schema"] == "gb-power-market-v27-development-protocol-v1"
    assert protocol["status"] == "PROTOCOL_LOCKED_NO_V27_CANDIDATE_YET"
    assert protocol["created_after_v26_snapshot_sequence"] == 3
    assert latest["sequence"] >= 3

    assert discovery["rows"] == 51
    assert discovery["end_exclusive_utc"] == "2026-08-23T22:00:00Z"
    assert discovery["source_run_id"] == 32675196453
    assert discovery["artifact_id"] == 9502476322
    assert discovery["artifact_sha256"] == (
        "a162270d94528429c0d3dcca89152f57fba9ed12654b0a2b70fbb0386fa8af1a"
    )
    assert discovery["ledger_chain_tip_sha256"] == (
        "dca4ef5173dcf18a81814a2bcfadaea72c4ed5fa5abc1b1c78555e55129e4a8b"
    )
    assert discovery["role"] == "FAILURE_DISCOVERY_ONLY_NEVER_V27_VALIDATION_OR_FORWARD_EVIDENCE"

    assert protocol["candidate_policy"]["maximum_candidates_per_validation_block"] == 1
    assert protocol["candidate_policy"]["candidate_must_be_fully_specified_before_validation_labels_are_read"] is True
    assert protocol["candidate_policy"]["no_parameter_sweep_on_validation_block"] is True
    assert protocol["candidate_policy"]["no_retuning_failed_candidate_on_same_validation_block"] is True

    discovery_end = pd.Timestamp(discovery["end_exclusive_utc"])
    validation_start = pd.Timestamp(validation["start_utc_not_before"])
    assert validation_start >= discovery_end
    assert validation["minimum_rows"] == 48
    assert validation["minimum_duration_hours"] == 24
    assert validation["validation_rows_can_never_be_relabelled_as_fresh_v27_forward_evidence"] is True

    assert gate["all_required"] is True
    assert gate["candidate_mae_strictly_better_than_frozen"] is True
    assert gate["candidate_p95_abs_error_non_worse_than_frozen"] is True
    assert gate["candidate_absolute_signed_bias_non_worse_than_frozen"] is True
    assert gate["candidate_mae_strictly_better_than_previous_day_reference"] is True
    assert gate["automatic_forward_launch"] is False

    assert forward["allowed_only_after_validation_gate_passes"] is True
    assert forward["new_version_required"] == "0.27.0"
    assert forward["new_candidate_id_required"] is True
    assert forward["new_implementation_lock_required"] is True
    assert forward["forward_start_must_be_strictly_after_validation_end"] is True
    assert forward["fresh_forward_rows_must_be_unseen_when_candidate_is_locked"] is True
    assert forward["automatic_promotion"] is False
