from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd


PREDICTION = Path("reports/forward/v27/V0_27_PRETARGET_RECOVERY_2_PREDICTION.json")
PROVENANCE = Path("reports/forward/v27/V0_27_PRETARGET_RECOVERY_2_PREDICTION_PROVENANCE.json")
RECOVERY_LOCK = Path("reports/forward/v27/V0_27_PRETARGET_RECOVERY_LOCK_2.json")
IMPLEMENTATION_LOCK = Path("reports/locked/V0_27_IMPLEMENTATION_LOCK.json")
EXPECTED_PREDICTION_SHA256 = "a94aa1c3f410c196bee4ab8276dd3f166b78a921ee7ada0cee0ba8c6633a6822"
EXPECTED_SOURCE_BLOB = "3c361dbb0e1665bbbad2e1097b8580ce062a203f"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_recovery2_prediction_is_immutable_and_pre_target() -> None:
    prediction = json.loads(PREDICTION.read_text())
    provenance = json.loads(PROVENANCE.read_text())
    recovery = json.loads(RECOVERY_LOCK.read_text())
    implementation = json.loads(IMPLEMENTATION_LOCK.read_text())

    assert _sha(PREDICTION) == EXPECTED_PREDICTION_SHA256
    assert provenance["prediction_sha256"] == EXPECTED_PREDICTION_SHA256
    assert provenance["recovery_lock_sha256"] == _sha(RECOVERY_LOCK)
    assert prediction["recovery_lock_sha256"] == _sha(RECOVERY_LOCK)

    assert prediction["status"] == "RECOVERY_PREDICTION_FROZEN_BEFORE_TARGET_OUTCOME"
    assert prediction["evidence_class"] == "PRE_TARGET_GIT_COMMITTED_PREDICTION_NOT_YET_SCORED"
    assert prediction["target_label_status"] == "UNOBSERVED_NOT_ACCESSED"
    assert prediction["realised_price_in_prediction_record"] is False
    assert provenance["target_label_accessed"] is False

    decision = pd.Timestamp(prediction["decision_time_utc"])
    target = pd.Timestamp(prediction["target_start_utc"])
    frozen_at = pd.Timestamp(prediction["freeze_completed_utc"])
    assert decision == pd.Timestamp("2026-08-25T13:00:00Z")
    assert target == pd.Timestamp("2026-08-25T15:00:00Z")
    assert decision <= frozen_at < target
    assert target - decision == pd.Timedelta(minutes=120)

    assert prediction["original_forward_start_utc"] == implementation["forward_start_utc"]
    assert prediction["original_forward_boundary_changed"] is False
    assert recovery["original_forward_boundary_changed"] is False
    assert prediction["predictive_source_git_blob_sha1"] == EXPECTED_SOURCE_BLOB
    assert implementation["candidate_source"]["git_blob_sha1"] == EXPECTED_SOURCE_BLOB


def test_recovery2_prediction_arithmetic_and_causal_vintage_are_locked() -> None:
    prediction = json.loads(PREDICTION.read_text())
    frozen = float(prediction["frozen_prediction_gbp_mwh"])
    correction = float(prediction["v27_correction_gbp_mwh"])
    candidate = float(prediction["v27_prediction_gbp_mwh"])
    assert abs(candidate - (frozen + correction)) < 1e-12
    assert prediction["v27_gate_reason"] == "CONSENSUS_DIRECTION_ALIGNED_CORRECTION"
    assert pd.Timestamp(prediction["neso_publish_time_utc"]) <= pd.Timestamp(prediction["decision_time_utc"])
    assert prediction["v26_history_latest_target_utc"] == "2026-08-25T12:30:00+00:00"
