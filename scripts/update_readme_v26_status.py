#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


START_HEADING = "## v0.26 — causal 6h/48h consensus-clipped 2h adaptation"
END_HEADING = "## Earlier prospective/blinding experiments"
CANDIDATE = "2H_FROZEN_PLUS_CAUSAL_6H_48H_CONSENSUS_CLIPPED_RESIDUAL"
V27_CANDIDATE = "2H_FROZEN_PLUS_CAUSAL_6H_48H_CONSENSUS_WITH_FROZEN_DIRECTION_VETO"
V27_RESULT = Path("reports/monitoring/V0_27_DEVELOPMENT_VALIDATION_RESULT.json")
V27_ELIGIBILITY = Path("reports/monitoring/V0_27_FORWARD_ELIGIBILITY.json")
V27_IMPLEMENTATION_LOCK = Path("reports/locked/V0_27_IMPLEMENTATION_LOCK.json")
VERSION_PATH = Path("VERSION")


def _pct(value: float) -> str:
    return f"{value:.1f}%"


def _v27_status_lines() -> list[str]:
    result_exists = V27_RESULT.is_file()
    eligibility_exists = V27_ELIGIBILITY.is_file()
    implementation_exists = V27_IMPLEMENTATION_LOCK.is_file()
    if result_exists != eligibility_exists:
        raise ValueError("partial v0.27 validation state")
    if implementation_exists and not result_exists:
        raise ValueError("v0.27 implementation lock exists without locked validation result")

    if implementation_exists:
        result = json.loads(V27_RESULT.read_text(encoding="utf-8"))
        eligibility = json.loads(V27_ELIGIBILITY.read_text(encoding="utf-8"))
        lock = json.loads(V27_IMPLEMENTATION_LOCK.read_text(encoding="utf-8"))
        validation = result["validation"]
        if validation.get("all_validation_gates_passed") is not True:
            raise ValueError("v0.27 implementation lock exists after failed validation")
        if eligibility.get("status") != "ELIGIBLE_TO_CREATE_FRESH_V27_FORWARD_LOCK":
            raise ValueError("v0.27 implementation lock lacks PASS eligibility")
        if lock.get("version") != "0.27.0" or lock.get("forward_evidence_rows_at_lock") != 0:
            raise ValueError("unexpected v0.27 implementation-lock state")
        if lock.get("candidate") != V27_CANDIDATE:
            raise ValueError("v0.27 implementation-lock candidate changed")
        return [
            "### v0.27 — sealed validation PASS, fresh forward boundary locked",
            "",
            f"The single byte-locked direction-veto candidate `{V27_CANDIDATE}` was evaluated exactly once on "
            "its sealed independent 48-half-hour development block. All four predeclared validation gates passed.",
            "",
            "| Sealed development validation | Candidate | Frozen 2h |",
            "|---|---:|---:|",
            f"| MAE (£/MWh) | **{validation['candidate_mae_gbp_mwh']:.3f}** | {validation['frozen_mae_gbp_mwh']:.3f} |",
            f"| P95 abs error (£/MWh) | **{validation['candidate_p95_abs_error_gbp_mwh']:.3f}** | {validation['frozen_p95_abs_error_gbp_mwh']:.3f} |",
            f"| Signed bias (£/MWh) | {validation['candidate_signed_bias_gbp_mwh']:.3f} | {validation['frozen_signed_bias_gbp_mwh']:.3f} |",
            "",
            f"Previous-day reference MAE: **{validation['reference_mae_gbp_mwh']:.3f} £/MWh**. "
            "These 48 labels are permanently classified as development validation, **not v0.27 forward evidence**.",
            "",
            "After the PASS result was immutably locked, the validated predictive bytes were promoted without "
            "modification to software version `0.27.0`. The pre-registered boundary rule then fixed the fresh "
            "forward experiment before any v0.27 forward outcome was read:",
            "",
            f"- implementation lock timestamp: `{lock['implementation_lock_timestamp_utc']}`;",
            f"- first forward decision: `{lock['first_forward_decision_time_utc']}`;",
            f"- first forward target / forward start: **`{lock['forward_start_utc']}`**;",
            f"- predictive source blob: `{lock['candidate_source']['git_blob_sha1']}`;",
            "- forward outcomes present at implementation lock: **0**;",
            "- automatic forward launch: **false**.",
            "",
            "The first target is the 2h horizon from the next 30-minute decision grid strictly after the "
            "implementation lock. That boundary is deterministic and cannot be moved after observing prices.",
            "",
            "Evidence: [`reports/locked/V0_27_IMPLEMENTATION_LOCK.json`](reports/locked/V0_27_IMPLEMENTATION_LOCK.json), "
            "[`docs/V0_27_DEVELOPMENT_VALIDATION_RESULT.md`](docs/V0_27_DEVELOPMENT_VALIDATION_RESULT.md), and "
            "[`docs/V0_27_POST_VALIDATION_GOVERNANCE.md`](docs/V0_27_POST_VALIDATION_GOVERNANCE.md).",
            "",
        ]

    if result_exists:
        result = json.loads(V27_RESULT.read_text(encoding="utf-8"))
        eligibility = json.loads(V27_ELIGIBILITY.read_text(encoding="utf-8"))
        validation = result["validation"]
        overall = "PASS" if validation["all_validation_gates_passed"] else "FAIL"
        return [
            f"### v0.27 sealed development validation — {overall}, no fresh forward lock yet",
            "",
            f"The byte-locked candidate `{V27_CANDIDATE}` has been evaluated exactly once on the sealed "
            "48-half-hour development block. This result is development evidence only.",
            "",
            f"Candidate MAE: **{validation['candidate_mae_gbp_mwh']:.3f} £/MWh**; frozen MAE: "
            f"**{validation['frozen_mae_gbp_mwh']:.3f} £/MWh**; governed next state: `{eligibility['status']}`.",
            "",
            "No v0.27 forward outcomes exist at this stage.",
            "",
        ]

    return [
        "### v0.27 development candidate — locked, not yet validated",
        "",
        f"A single later development candidate is byte-locked as `{V27_CANDIDATE}`. It retains the unchanged "
        "v0.26 consensus proposal and adds a sign-only frozen-direction veto: a residual correction is applied "
        "only when its sign agrees with the frozen model's direction from the latest causally available history "
        "target to the current 2h target. There is no magnitude threshold, lookback search or refit.",
        "",
        "Its one permitted independent validation block is sealed as "
        "`[2026-08-23T22:00:00Z, 2026-08-24T22:00:00Z)` — exactly **48 half-hours / 24 hours**. "
        "The validation workflow fails before any market-data download until the whole block is mature under the "
        "90-minute safety lag, and it uses an exact Elexon timestamp cutoff so post-validation prices are not read.",
        "",
        "This is **development only**: software version remains `0.26.0`, no v0.27 forward experiment has been "
        "launched, and pass/fail validation labels can never be relabelled as fresh v0.27 forward evidence. See "
        "[`docs/V0_27_CANDIDATE_LOCK.md`](docs/V0_27_CANDIDATE_LOCK.md) and "
        "[`docs/V0_27_DEVELOPMENT_PROTOCOL.md`](docs/V0_27_DEVELOPMENT_PROTOCOL.md).",
        "",
    ]


def build_v26_section(registry: dict, checkpoint: dict) -> str:
    latest = registry["snapshots"][-1]
    spec = checkpoint["candidate_spec"]
    development = checkpoint["development_diagnostics"]["v25_forward_window_reused_for_v26_development"]
    forward = checkpoint["forward_segment"]
    monitor = checkpoint["monitor"]

    if registry["candidate"] != CANDIDATE or spec["candidate"] != CANDIDATE:
        raise ValueError("v0.26 README renderer candidate identity changed")
    if int(latest["rows"]) != int(forward["rows"]):
        raise ValueError("latest registry row count disagrees with checkpoint")
    if latest["end_exclusive_utc"].replace("Z", "+00:00") != forward["end_exclusive_utc"]:
        raise ValueError("latest registry end disagrees with checkpoint")

    alerts = monitor.get("alerts", [])
    alerts_text = ", ".join(f"`{x}`" for x in alerts) if alerts else "none"
    alert_min_rows = int(monitor["alert_min_rows"])
    if int(monitor["rows_observed"]) < alert_min_rows:
        alert_gate_text = f"Performance alerts remain gated until {alert_min_rows} forward rows."
    else:
        alert_gate_text = f"The predeclared {alert_min_rows}-row degradation-alert gate is active on this snapshot."

    if alerts:
        governance_text = (
            "The unchanged frozen v0.20 2h model remains the current champion. v0.26 is an alerted "
            "challenger and is not retuned after this checkpoint."
        )
    else:
        governance_text = (
            "The unchanged frozen v0.20 2h model remains the comparison champion while v0.26 continues "
            "forward monitoring; no candidate auto-promotes."
        )

    lines = [
        START_HEADING,
        "",
        "v0.26 responds to the observed v0.25 lag/overshoot without refitting the frozen 2h ridge model. "
        "The 48h residual window is retained and the 6h window comes from the already predeclared v0.25 "
        "monitoring policy; there is no search over lookback lengths.",
        "",
        "At each 2h decision, both residual windows use only outcomes already available at decision time. "
        "A correction is applied only when the 6h and 48h residual means agree in sign, with magnitude clipped "
        "to the smaller absolute mean. Sign disagreement falls back to the unchanged frozen model.",
        "",
        f"Candidate ID: `{CANDIDATE}`.",
        "",
        f"The rule and forward boundary were fixed before v0.26 outcomes were read. Forward start: **{registry['forward_start_utc']}**.",
        "",
        "### Development diagnostic — not new evidence",
        "",
        "The already-observed v0.25 forward window was reused only for development diagnostics:",
        "",
        "| Model | MAE (£/MWh) |",
        "|---|---:|",
        f"| v0.26 consensus candidate | **{development['candidate_mae_gbp_mwh']:.3f}** |",
        f"| frozen v0.20 2h | {development['frozen_mae_gbp_mwh']:.3f} |",
        f"| v0.25 48h correction | {development['v25_mae_gbp_mwh']:.3f} |",
        f"| previous-day reference | {development['reference_mae_gbp_mwh']:.3f} |",
        "",
        "These rows were already observed before v0.26 and are not counted as fresh v0.26 evidence.",
        "",
        f"### Latest locked forward snapshot — sequence {latest['sequence']}",
        "",
        f"Snapshot sequence **{latest['sequence']}** contains **{forward['rows']} genuine forward half-hours** "
        f"through `{latest['end_exclusive_utc']}` end-exclusive, including **{latest['new_rows']} rows added** "
        "since the preceding locked snapshot.",
        "",
        "| Model | Forward MAE (£/MWh) |",
        "|---|---:|",
        f"| v0.26 consensus candidate | **{forward['candidate_mae_gbp_mwh']:.3f}** |",
        f"| frozen v0.20 2h | **{forward['frozen_mae_gbp_mwh']:.3f}** |",
        f"| v0.25 48h correction | {forward['v25_mae_gbp_mwh']:.3f} |",
        f"| previous-day reference | {forward['reference_mae_gbp_mwh']:.3f} |",
        "",
        f"Current v0.26 improvement vs frozen: **{_pct(forward['candidate_improvement_vs_frozen_pct'])}**; "
        f"vs v0.25: **{_pct(forward['candidate_improvement_vs_v25_pct'])}**; "
        f"vs previous-day reference: **{_pct(forward['candidate_improvement_vs_reference_pct'])}**.",
        "",
        f"Maturity: `{monitor['maturity_stage']}`. Alert status: `{monitor['alert_status']}`; alerts: {alerts_text}. {alert_gate_text}",
        "",
        governance_text,
        "",
        "Integrity:",
        "",
        f"- source run: `{latest['run_id']}`; artifact ID: `{latest['artifact_id']}`;",
        f"- artifact SHA-256: `{latest['artifact_sha256']}`;",
        f"- ledger chain tip: `{latest['ledger_chain_tip_sha256']}`;",
        f"- locked checkpoint: [`{latest['checkpoint_path']}`]({latest['checkpoint_path']});",
        "- snapshot registry: [`reports/monitoring/V0_26_FORWARD_SNAPSHOT_REGISTRY.json`](reports/monitoring/V0_26_FORWARD_SNAPSHOT_REGISTRY.json).",
        "",
        "The two-row first v0.26 ledger remains the permanent genesis anchor. Every later snapshot must reproduce "
        "the latest registered prefix before appending rows. The predictive source and frozen model state are "
        "also byte-locked; changing either requires a new candidate version and forward boundary.",
        "",
        "The first post-lock gate-effectiveness analysis is preserved at "
        "[`docs/V0_26_GATE_EFFECTIVENESS_2026-08-23_0800Z.md`](docs/V0_26_GATE_EFFECTIVENESS_2026-08-23_0800Z.md). "
        "The first active-alert root-cause analysis is preserved at "
        "[`docs/V0_26_ALERT_ROOT_CAUSE_2026-08-23_2200Z.md`](docs/V0_26_ALERT_ROOT_CAUSE_2026-08-23_2200Z.md).",
        "",
        *_v27_status_lines(),
        "Promotion review remains unavailable before **336 half-hours / 7 days**, and no gate auto-promotes a candidate.",
        "",
    ]
    return "\n".join(lines)


def update_readme(*, readme_path: Path, registry_path: Path) -> str:
    text = readme_path.read_text(encoding="utf-8")
    if START_HEADING not in text or END_HEADING not in text:
        raise ValueError("README v0.26 section boundaries not found")

    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    latest = registry["snapshots"][-1]
    checkpoint = json.loads(Path(latest["checkpoint_path"]).read_text(encoding="utf-8"))
    section = build_v26_section(registry, checkpoint)

    before, remainder = text.split(START_HEADING, 1)
    _, after = remainder.split(END_HEADING, 1)
    updated = before.rstrip() + "\n\n" + section.rstrip() + "\n\n" + END_HEADING + after

    version = VERSION_PATH.read_text(encoding="utf-8").strip()
    updated, count = re.subn(
        r"Current software version: \*\*v[^*]+\*\*\.",
        f"Current software version: **v{version}**.",
        updated,
        count=1,
    )
    if count != 1:
        raise ValueError("README current software version line not found")

    readme_path.write_text(updated, encoding="utf-8")
    return updated


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--readme", default="README.md")
    ap.add_argument("--registry", default="reports/monitoring/V0_26_FORWARD_SNAPSHOT_REGISTRY.json")
    args = ap.parse_args()
    update_readme(readme_path=Path(args.readme), registry_path=Path(args.registry))


if __name__ == "__main__":
    main()
