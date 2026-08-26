from pathlib import Path


WORKFLOW = Path('.github/workflows/score-v27-precommitted-recovery2.yml')


def _text() -> str:
    return WORKFLOW.read_text(encoding='utf-8')


def test_scoring_workflow_is_manual_only() -> None:
    text = _text()
    assert 'workflow_dispatch:' in text
    assert 'pull_request:' not in text
    assert 'schedule:' not in text


def test_maturity_barrier_precedes_any_outcome_download() -> None:
    text = _text()
    barrier = text.index('Wait without outcome access until scoring maturity, then verify contract')
    download = text.index('Download only the committed target outcome after maturity gate')
    materialise = text.index('Materialise one realised market target')
    score = text.index('Score only the already committed prediction')
    assert barrier < download < materialise < score


def test_scoring_download_is_exactly_the_precommitted_target_half_hour() -> None:
    text = _text()
    assert '--start-utc 2026-08-25T15:00:00Z' in text
    assert '--end-exclusive-utc 2026-08-25T15:30:00Z' in text


def test_scoring_uses_only_the_git_committed_prediction_record() -> None:
    text = _text()
    prediction = 'reports/forward/v27/V0_27_PRETARGET_RECOVERY_2_PREDICTION.json'
    assert f'--prediction {prediction}' in text
    assert 'score_v27_precommitted_prediction.py' in text
    # The scoring workflow must not rerun a forecasting workflow or prediction builder.
    assert 'freeze_v27_recovery_forward_prediction.py' not in text
    assert 'run_v24_continuous_forward_monitor.py' not in text
    assert 'adaptive_direction_v27_candidate.py' not in text


def test_single_outcome_claim_boundary_is_fail_closed() -> None:
    text = _text()
    assert "SINGLE_PRECOMMITTED_FORWARD_OUTCOME_DESCRIPTIVE_ONLY" in text
    assert "score['promotion_eligible'] is not False" in text
    assert "score['automatic_model_change'] is not False" in text
    assert "prov['prediction_recomputed_during_scoring'] is not False" in text
    assert "prov['target_outcome_accessed_only_after_maturity_gate'] is not True" in text
