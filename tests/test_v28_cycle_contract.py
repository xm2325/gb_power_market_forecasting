from pathlib import Path
import json

from gb_power_market.prospective_v28 import MIN_FORWARD_ROWS_FOR_REVIEW, METHODS


ROOT = Path(__file__).resolve().parents[1]


def test_live_workflow_has_schedule_and_manual_path():
    workflow = (ROOT / ".github/workflows/v28-prospective-shadow.yml").read_text()
    assert "workflow_dispatch:" in workflow
    assert "schedule:" in workflow
    assert "cron: '11,41 * * * *'" in workflow
    assert "cancel-in-progress: false" in workflow
    assert "--input-end-exclusive-utc" in workflow
    assert "--download-manifest" in workflow


def test_live_workflow_requires_freeze_before_push():
    workflow = (ROOT / ".github/workflows/v28-prospective-shadow.yml").read_text()
    assert workflow.index("Verify target is still in future") < workflow.index("git push origin HEAD:main")
    assert "FORECAST_CONTAINS_TARGET_LABEL" in workflow
    assert 'git commit -m "[skip ci] Append v0.28 prospective shadow evidence"' in workflow


def test_run_script_enforces_committed_pretarget_state():
    script = (ROOT / "scripts/run_v28_shadow_cycle.py").read_text()
    assert "_committed_before_target(" in script
    assert '["git", "log", "-1", "--format=%cI"' in script
    assert "write_json_new(score_path, score)" in script
    assert "write_json_new(target_path, prediction)" in script
    assert 'args.minimum_delay_minutes < 90' in script


def test_shadow_is_separate_from_locked_historical_evidence():
    assert set(METHODS) == {"previous_day", "consensus", "direction_veto"}
    assert MIN_FORWARD_ROWS_FOR_REVIEW == 336
    locked = json.loads(
        (ROOT / "reports/locked/V0_27_CANDIDATE_LOCK.json").read_text()
    )
    assert locked["schema"] == "gb-power-market-v27-development-candidate-lock-v1"
