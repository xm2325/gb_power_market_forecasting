from pathlib import Path


WORKFLOW = Path('.github/workflows/v27-historical-walkforward.yml')


def test_historical_walkforward_is_manual_only_and_starts_scoring_may_1() -> None:
    text = WORKFLOW.read_text(encoding='utf-8')
    assert 'workflow_dispatch:' in text
    assert 'pull_request:' not in text
    assert '--score-start-utc 2026-05-01T00:00:00Z' in text
    assert '--score-end-exclusive-utc 2026-08-23T22:00:00Z' in text
    assert '--fold-days 7' in text


def test_historical_workflow_rechecks_locked_adaptation_blobs_before_network() -> None:
    text = WORKFLOW.read_text(encoding='utf-8')
    verify = text.index('Verify historical protocol and unchanged adaptation sources before network access')
    network = text.index('Download immutable Jan-Jun legacy NESO forecast archive')
    assert verify < network
    assert '2ccb3d2a0762eec66d646e164262f8ac5b759d8e' in text
    assert '399915c6cdd0d3b016bde73cb0ef92eb2697adf8' in text
    assert '3c361dbb0e1665bbbad2e1097b8580ce062a203f' in text


def test_historical_workflow_requires_exact_contiguous_5516_rows_and_nonlive_label() -> None:
    text = WORKFLOW.read_text(encoding='utf-8')
    assert 'len(rows) != 5516' in text
    assert 'HISTORICAL_ASOF_ROLLING_ORIGIN_NOT_LIVE_FORWARD' in text
    assert 'future_labels_passed_to_fold_runner' in text
    assert "pd.date_range('2026-05-01T00:00:00Z', '2026-08-23T22:00:00Z'" in text
