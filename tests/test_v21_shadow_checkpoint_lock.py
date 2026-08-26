from __future__ import annotations

import hashlib
import json
from pathlib import Path

CHECKPOINT = Path("reports/prospective/V0_21_SHADOW_CHECKPOINT_2026-08-21.json")
SIDECAR = Path("reports/prospective/V0_21_SHADOW_CHECKPOINT_2026-08-21.json.sha256")
EXPECTED_SHA = "e16c4cbee28ae716d5aff385f26acf5f343a9b38b0e8de961a37d1958d568378"


def test_shadow_checkpoint_digest_is_locked():
    digest = hashlib.sha256(CHECKPOINT.read_bytes()).hexdigest()
    assert digest == EXPECTED_SHA
    assert SIDECAR.read_text().strip() == f"{EXPECTED_SHA}  {CHECKPOINT.name}"


def test_shadow_checkpoint_is_real_but_not_claimable():
    p = json.loads(CHECKPOINT.read_text())
    assert p["status"] == "LOCKED_SHADOW_CHECKPOINT_NOT_CLAIMABLE"
    assert p["workflow_run"]["run_id"] == 32473442425
    assert p["prospective_window"]["expected_half_hours"] == 271
    assert p["prospective_window"]["minimum_rows_for_new_evidence"] == 672
    assert p["prospective_window"]["claim_gate_met"] is False
    assert p["frozen_model_state"]["model_changed_since_v020"] is False
    for horizon in ["30m", "2h", "6h", "12h"]:
        result = p["horizons"][horizon]
        assert result["status"] == "SHADOW_ONLY"
        assert result["coverage"] == 1.0
        assert result["future_neso_publications"] == 0


def test_changed_model_cannot_reuse_inspected_checkpoint_as_independent_evidence():
    p = json.loads(CHECKPOINT.read_text())
    boundary = p["development_boundary"]
    assert boundary["unchanged_frozen_model_may_continue_accumulating_this_window"] is True
    assert boundary["if_any_model_rule_is_changed_after_inspecting_this_checkpoint_new_candidate_start_not_before_utc"] == "2026-08-20T23:00:00+00:00"
