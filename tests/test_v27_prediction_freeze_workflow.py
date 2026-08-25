from pathlib import Path


WORKFLOW = Path(".github/workflows/freeze-v27-first-prediction.yml")


def test_freeze_workflow_checks_time_before_any_market_download() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    preflight = text.index("Require locked first decision and pre-target execution before network access")
    neso = text.index("Download bounded NESO vintages for causal first prediction")
    elexon = text.index("Download Elexon history only through the locked decision boundary")
    assert preflight < neso < elexon
    assert "verify_freeze_window" in text


def test_freeze_workflow_never_downloads_elexon_at_or_after_decision() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "--end-exclusive-utc 2026-08-25T00:30:00Z" in text
    assert "elexon['end_exclusive_utc'] != '2026-08-25T00:30:00Z'" in text
    assert "request_to_inclusive_utc" in text
    assert "PRE_TARGET_COMMIT_WINDOW_MISSED" in text
    assert "PRE_TARGET_PUSH_WINDOW_MISSED" in text


def test_freeze_workflow_commits_only_no_label_prediction_and_manifests() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "V0_27_FIRST_FORWARD_PREDICTION_2026-08-25_0230Z.json" in text
    assert "V0_27_FIRST_FORWARD_PREDICTION_PROVENANCE.json" in text
    assert "UNOBSERVED_NOT_ACCESSED" in text
    assert "PRE_TARGET_PREDICTION_NOT_YET_SCORED" in text
    assert "target_label_accessed" in text
    assert "reports/v24_for_v27_first_freeze" not in text.split("git add", 1)[1].split("git commit", 1)[0]
    assert "data/external" not in text.split("git add", 1)[1].split("git commit", 1)[0]
