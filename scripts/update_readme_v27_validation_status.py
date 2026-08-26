#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path


RESULT_PATH = Path("reports/monitoring/V0_27_DEVELOPMENT_VALIDATION_RESULT.json")
ELIGIBILITY_PATH = Path("reports/monitoring/V0_27_FORWARD_ELIGIBILITY.json")
START = "## v0.27 sealed development-validation result"
END = "## Source-clock audit"


def build_section(result: dict, eligibility: dict) -> str:
    validation = result["validation"]
    if result.get("evidence_class") != "INDEPENDENT_DEVELOPMENT_VALIDATION_NOT_FORWARD_EVIDENCE":
        raise ValueError("v0.27 README result evidence class changed")
    if validation.get("rows") != 48 or validation.get("gate_evaluated") is not True:
        raise ValueError("v0.27 README result is not the complete sealed 48-row block")
    if eligibility.get("automatic_forward_launch") is not False:
        raise ValueError("v0.27 README eligibility claims automatic forward launch")
    if bool(eligibility.get("validation_passed")) != bool(validation.get("all_validation_gates_passed")):
        raise ValueError("v0.27 README result and eligibility disagree")

    gates = validation["gates"]
    overall = "PASS" if validation["all_validation_gates_passed"] else "FAIL"
    lines = [
        START,
        "",
        "The single byte-locked direction-veto candidate has now been evaluated exactly once on its sealed "
        "independent development block `[2026-08-23T22:00:00Z, 2026-08-24T22:00:00Z)` (**48 half-hours**).",
        "",
        "| Metric | Candidate | Frozen |",
        "|---|---:|---:|",
        f"| MAE (£/MWh) | **{validation['candidate_mae_gbp_mwh']:.3f}** | **{validation['frozen_mae_gbp_mwh']:.3f}** |",
        f"| P95 abs error (£/MWh) | {validation['candidate_p95_abs_error_gbp_mwh']:.3f} | {validation['frozen_p95_abs_error_gbp_mwh']:.3f} |",
        f"| Signed bias (£/MWh) | {validation['candidate_signed_bias_gbp_mwh']:.3f} | {validation['frozen_signed_bias_gbp_mwh']:.3f} |",
        "",
        f"Previous-day reference MAE: **{validation['reference_mae_gbp_mwh']:.3f} £/MWh**.",
        "",
        "Validation gates:",
        "",
        *[f"- `{name}`: **{'PASS' if bool(value) else 'FAIL'}**;" for name, value in gates.items()],
        "",
        f"Overall sealed development validation: **{overall}**.",
        f"Governed next state: `{eligibility['status']}`.",
        "",
        "These 48 labels are development evidence permanently. They are not fresh v0.27 forward evidence. "
        "Validation never auto-launches a challenger: a fail rejects this candidate on this block; a pass only "
        "permits a separately locked `0.27.0` experiment starting strictly after the validation boundary.",
        "",
        "Full locked result: [`docs/V0_27_DEVELOPMENT_VALIDATION_RESULT.md`](docs/V0_27_DEVELOPMENT_VALIDATION_RESULT.md).",
        "",
    ]
    return "\n".join(lines)


def update_readme(readme_path: Path = Path("README.md")) -> str:
    text = readme_path.read_text(encoding="utf-8")
    if not RESULT_PATH.exists() and not ELIGIBILITY_PATH.exists():
        return text
    if RESULT_PATH.exists() != ELIGIBILITY_PATH.exists():
        raise ValueError("partial v0.27 locked validation state: result and eligibility must appear together")
    if END not in text:
        raise ValueError("README source-clock boundary not found")

    result = json.loads(RESULT_PATH.read_text(encoding="utf-8"))
    eligibility = json.loads(ELIGIBILITY_PATH.read_text(encoding="utf-8"))
    section = build_section(result, eligibility).rstrip()

    if START in text:
        before, remainder = text.split(START, 1)
        _, after = remainder.split(END, 1)
        updated = before.rstrip() + "\n\n" + section + "\n\n" + END + after
    else:
        before, after = text.split(END, 1)
        updated = before.rstrip() + "\n\n" + section + "\n\n" + END + after
    readme_path.write_text(updated, encoding="utf-8")
    return updated


if __name__ == "__main__":
    update_readme()
