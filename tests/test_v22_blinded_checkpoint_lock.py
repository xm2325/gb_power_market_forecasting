from __future__ import annotations

import json
from pathlib import Path


CHECKPOINT = Path("reports/prospective/V0_22_BLINDED_CHECKPOINT_2026-08-21.json")


def test_v22_blinded_checkpoint_contains_no_performance_metrics():
    payload = json.loads(CHECKPOINT.read_text(encoding="utf-8"))
    assert payload["status"] == "LOCKED_BLINDED_CONFIRMATORY_CHECKPOINT"
    assert payload["confirmatory_window"]["complete_rows_so_far"] == 21
    assert payload["confirmatory_window"]["rows_remaining_to_reveal"] == 651
    assert payload["blinding_assertion"]["performance_metrics_computed_or_serialized"] is False
    text = CHECKPOINT.read_text(encoding="utf-8")
    forbidden = [
        "reference_mae_gbp_mwh",
        "frozen_model_mae_gbp_mwh",
        "improvement_vs_reference_pct",
        "interval_coverage",
        "daily_block_bootstrap",
    ]
    for token in forbidden:
        assert token not in text


def test_v22_blinded_checkpoint_keeps_fixed_reveal_window():
    payload = json.loads(CHECKPOINT.read_text(encoding="utf-8"))
    window = payload["confirmatory_window"]
    assert window["start_utc"] == "2026-08-20T23:00:00+00:00"
    assert window["fixed_end_exclusive_utc"] == "2026-09-03T23:00:00+00:00"
    assert window["rows_required_for_reveal"] == 672
    assert window["coverage_so_far"] == 1.0
    assert window["future_neso_publications"] == 0
