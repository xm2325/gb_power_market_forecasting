import hashlib
import json
from pathlib import Path

import pytest


SCORE = Path('reports/forward/v27/V0_27_PRETARGET_RECOVERY_2_SCORE.json')
PROVENANCE = Path('reports/forward/v27/V0_27_PRETARGET_RECOVERY_2_SCORE_PROVENANCE.json')
PREDICTION = Path('reports/forward/v27/V0_27_PRETARGET_RECOVERY_2_PREDICTION.json')
EXPECTED_PREDICTION_SHA256 = 'a94aa1c3f410c196bee4ab8276dd3f166b78a921ee7ada0cee0ba8c6633a6822'
EXPECTED_SCORE_SHA256 = '6f1a8e0e75734c7bbb78715b35c91fd94544eb2a55e4a6b63e5cdaa00a39dff8'


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_first_precommitted_forward_score_is_immutable_and_descriptive_only() -> None:
    score = json.loads(SCORE.read_text(encoding='utf-8'))
    prov = json.loads(PROVENANCE.read_text(encoding='utf-8'))

    assert _sha256(PREDICTION) == EXPECTED_PREDICTION_SHA256
    assert _sha256(SCORE) == EXPECTED_SCORE_SHA256
    assert score['prediction_sha256'] == EXPECTED_PREDICTION_SHA256
    assert prov['prediction_sha256'] == EXPECTED_PREDICTION_SHA256
    assert prov['score_sha256'] == EXPECTED_SCORE_SHA256

    assert score['target_start_utc'] == '2026-08-25T15:00:00+00:00'
    assert score['decision_time_utc'] == '2026-08-25T13:00:00+00:00'
    assert score['prediction_freeze_completed_utc'] == '2026-08-25T13:01:19.290770+00:00'
    assert score['maturity_preflight']['safe_scoring_boundary_utc'] == '2026-08-25T16:30:00+00:00'
    assert score['scoring_completed_utc'] > '2026-08-25T16:30:00+00:00'

    assert score['realised_price_gbp_mwh'] == pytest.approx(133.73)
    assert score['v27_prediction_gbp_mwh'] == pytest.approx(97.5134306446891)
    assert score['frozen_prediction_gbp_mwh'] == pytest.approx(92.9233301428951)
    assert score['previous_settlement_day_reference_gbp_mwh'] == pytest.approx(118.32)
    assert score['v27_absolute_error_gbp_mwh'] == pytest.approx(36.216569355310895)
    assert score['frozen_absolute_error_gbp_mwh'] == pytest.approx(40.80666985710489)
    assert score['reference_absolute_error_gbp_mwh'] == pytest.approx(15.41)
    assert score['v27_minus_frozen_absolute_error_gbp_mwh'] == pytest.approx(-4.590100501793998)
    assert score['v27_minus_reference_absolute_error_gbp_mwh'] == pytest.approx(20.8065693553109)

    assert score['evidence_class'] == 'SINGLE_PRECOMMITTED_FORWARD_OUTCOME_DESCRIPTIVE_ONLY'
    assert score['promotion_eligible'] is False
    assert score['automatic_model_change'] is False
    assert prov['target_outcome_accessed_only_after_maturity_gate'] is True
    assert prov['prediction_recomputed_during_scoring'] is False
    assert prov['promotion_eligible'] is False
