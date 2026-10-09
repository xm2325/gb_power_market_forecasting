from __future__ import annotations

import hashlib
import json
from pathlib import Path

LOCK = Path("reports/locked/V0_21_FROZEN_MODEL_STATE.json")
SIDECAR = Path("reports/locked/V0_21_FROZEN_MODEL_STATE.json.sha256")
EXPECTED_SHA = "e9952aa88ca56b85f4d595bfe918cdc589ac0048d717d3fb3d9210361eb18918"
EXPECTED_EVIDENCE = "7c5f78b98c8ed877ab4c5cefa8a40b3068abb74cb2062ecf677f319d74a14661"


def test_v21_model_state_digest_is_locked():
    digest = hashlib.sha256(LOCK.read_bytes()).hexdigest()
    assert digest == EXPECTED_SHA
    assert SIDECAR.read_text().strip() == f"{EXPECTED_SHA}  {LOCK.name}"


def test_v21_model_state_replays_locked_predictions_exactly():
    payload = json.loads(LOCK.read_text())
    assert payload["status"] == "FROZEN_MODEL_STATE_EXPORTED"
    assert payload["source_evidence_id_sha256"] == EXPECTED_EVIDENCE
    for horizon in ["30m", "2h", "6h", "12h"]:
        check = payload["locked_prediction_replay_checks"][horizon]
        assert check["status"] == "PASS"
        assert check["locked_prediction_rows"] == 1623
        assert check["maximum_absolute_prediction_difference_gbp_mwh"] <= 1e-8


def test_v21_frozen_families_and_alphas_cannot_silently_change():
    payload = json.loads(LOCK.read_text())
    expected = {
        "30m": ("PRICE_HISTORY_ONLY", 10.0),
        "2h": ("PRICE_PLUS_NESO_LEVELS", 1.0),
        "6h": ("PRICE_PLUS_NESO_LEVELS", 100.0),
        "12h": ("PRICE_PLUS_NESO_LEVELS", 100.0),
    }
    for horizon, (family, alpha) in expected.items():
        state = payload["states"][horizon]
        assert state["selected_family"] == family
        assert state["alpha"] == alpha
        assert state["source_evidence_id_sha256"] == EXPECTED_EVIDENCE
        assert len(state["coef"]) == len(state["features"]) + 1
