from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LOCK = ROOT / "reports" / "locked" / "V0_20_REAL_BENCHMARK_LOCK.json"
DIGEST = ROOT / "reports" / "locked" / "V0_20_REAL_BENCHMARK_LOCK.sha256"


def test_locked_real_benchmark_identity_and_claims() -> None:
    payload = json.loads(LOCK.read_text(encoding="utf-8"))

    assert payload["status"] == "LOCKED_REAL_BENCHMARK"
    assert payload["workflow_run"]["run_id"] == 32469293682
    assert payload["workflow_run"]["claim_integrity_gate"] == "PASS"
    assert payload["workflow_run"]["evidence_id_sha256"] == (
        "7c5f78b98c8ed877ab4c5cefa8a40b3068abb74cb2062ecf677f319d74a14661"
    )

    final = payload["frozen_final_window"]
    assert final["expected_rows"] == 1623
    assert final["coverage_each_horizon"] == 1.0
    assert final["future_neso_publications_each_horizon"] == 0

    price = payload["price_benchmark_final"]
    assert price["30m"]["claim_class"] == "REAL_CLAIMABLE_POSITIVE"
    assert price["2h"]["claim_class"] == "REAL_CLAIMABLE_POSITIVE"
    assert price["6h"]["claim_class"] == "REAL_NEGATIVE_RESULT"
    assert price["12h"]["claim_class"] == "REAL_NEGATIVE_RESULT"
    assert price["30m"]["selected_family"] == "PRICE_HISTORY_ONLY"
    assert price["2h"]["selected_family"] == "PRICE_PLUS_NESO_LEVELS"

    assert payload["interpretation"]["revisions"] == (
        "Forecast revision features were not selected at any horizon."
    )


def test_locked_real_benchmark_sidecar_digest() -> None:
    expected = DIGEST.read_text(encoding="utf-8").split()[0]
    observed = hashlib.sha256(LOCK.read_bytes()).hexdigest()
    assert observed == expected


def test_locked_window_cannot_be_reclaimed_after_tuning() -> None:
    payload = json.loads(LOCK.read_text(encoding="utf-8"))
    policy = payload["prospective_policy"]

    assert policy["locked_window_may_be_reused_for_diagnostics"] is True
    assert (
        policy[
            "locked_window_may_be_used_to_select_or_tune_a_model_and_then_reclaim_independent_performance_on_same_window"
        ]
        is False
    )
    assert policy["next_prospective_target_start_not_before_utc"] == (
        "2026-08-15T07:30:00+00:00"
    )
