import json
from pathlib import Path

import scripts.update_readme_v27_validation_status as updater


def _result(*, passed: bool) -> dict:
    gates = {
        "candidate_mae_strictly_better_than_frozen": passed,
        "candidate_p95_abs_error_non_worse_than_frozen": True,
        "candidate_absolute_signed_bias_non_worse_than_frozen": True,
        "candidate_mae_strictly_better_than_previous_day_reference": True,
    }
    return {
        "evidence_class": "INDEPENDENT_DEVELOPMENT_VALIDATION_NOT_FORWARD_EVIDENCE",
        "validation": {
            "rows": 48,
            "gate_evaluated": True,
            "candidate_mae_gbp_mwh": 9.0 if passed else 11.0,
            "frozen_mae_gbp_mwh": 10.0,
            "reference_mae_gbp_mwh": 12.0,
            "candidate_p95_abs_error_gbp_mwh": 20.0,
            "frozen_p95_abs_error_gbp_mwh": 20.0,
            "candidate_signed_bias_gbp_mwh": 1.0,
            "frozen_signed_bias_gbp_mwh": 1.5,
            "gates": gates,
            "all_validation_gates_passed": all(gates.values()),
        },
    }


def test_updater_is_noop_before_validation_result(monkeypatch, tmp_path: Path) -> None:
    readme = tmp_path / "README.md"
    original = "header\n\n## Source-clock audit\nbody\n"
    readme.write_text(original, encoding="utf-8")
    monkeypatch.setattr(updater, "RESULT_PATH", tmp_path / "missing-result.json")
    monkeypatch.setattr(updater, "ELIGIBILITY_PATH", tmp_path / "missing-eligibility.json")
    assert updater.update_readme(readme) == original
    assert readme.read_text(encoding="utf-8") == original


def test_updater_renders_locked_pass_without_claiming_forward_launch(monkeypatch, tmp_path: Path) -> None:
    readme = tmp_path / "README.md"
    readme.write_text("header\n\n## Source-clock audit\nbody\n", encoding="utf-8")
    result_path = tmp_path / "result.json"
    eligibility_path = tmp_path / "eligibility.json"
    result_path.write_text(json.dumps(_result(passed=True)), encoding="utf-8")
    eligibility_path.write_text(
        json.dumps({
            "validation_passed": True,
            "automatic_forward_launch": False,
            "status": "ELIGIBLE_TO_CREATE_FRESH_V27_FORWARD_LOCK",
        }),
        encoding="utf-8",
    )
    monkeypatch.setattr(updater, "RESULT_PATH", result_path)
    monkeypatch.setattr(updater, "ELIGIBILITY_PATH", eligibility_path)
    updated = updater.update_readme(readme)
    assert "Overall sealed development validation: **PASS**" in updated
    assert "ELIGIBLE_TO_CREATE_FRESH_V27_FORWARD_LOCK" in updated
    assert "not fresh v0.27 forward evidence" in updated
    assert updated.count(updater.START) == 1
    assert updater.update_readme(readme) == updated


def test_updater_renders_failure_as_rejection(monkeypatch, tmp_path: Path) -> None:
    readme = tmp_path / "README.md"
    readme.write_text("header\n\n## Source-clock audit\nbody\n", encoding="utf-8")
    result_path = tmp_path / "result.json"
    eligibility_path = tmp_path / "eligibility.json"
    result_path.write_text(json.dumps(_result(passed=False)), encoding="utf-8")
    eligibility_path.write_text(
        json.dumps({
            "validation_passed": False,
            "automatic_forward_launch": False,
            "status": "CANDIDATE_REJECTED_ON_SEALED_BLOCK",
        }),
        encoding="utf-8",
    )
    monkeypatch.setattr(updater, "RESULT_PATH", result_path)
    monkeypatch.setattr(updater, "ELIGIBILITY_PATH", eligibility_path)
    updated = updater.update_readme(readme)
    assert "Overall sealed development validation: **FAIL**" in updated
    assert "CANDIDATE_REJECTED_ON_SEALED_BLOCK" in updated
