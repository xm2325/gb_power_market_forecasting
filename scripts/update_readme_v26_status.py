#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path


START_HEADING = "## v0.26 — causal 6h/48h consensus-clipped 2h adaptation"
END_HEADING = "## Earlier prospective/blinding experiments"
CANDIDATE = "2H_FROZEN_PLUS_CAUSAL_6H_48H_CONSENSUS_CLIPPED_RESIDUAL"
V27_CANDIDATE = "2H_FROZEN_PLUS_CAUSAL_6H_48H_CONSENSUS_WITH_FROZEN_DIRECTION_VETO"


def _pct(value: float) -> str:
    return f"{value:.1f}%"


def build_v26_section(registry: dict, checkpoint: dict) -> str:
    latest = registry["snapshots"][-1]
    spec = checkpoint["candidate_spec"]
    development = checkpoint["development_diagnostics"][
        "v25_forward_window_reused_for_v26_development"
    ]
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
        alert_gate_text = (
            f"The predeclared {alert_min_rows}-row degradation-alert gate is active on this snapshot."
        )

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
        f"The rule and forward boundary were fixed before v0.26 outcomes were read. Forward start: "
        f"**{registry['forward_start_utc']}**.",
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
        f"Maturity: `{monitor['maturity_stage']}`. Alert status: `{monitor['alert_status']}`; alerts: {alerts_text}. "
        f"{alert_gate_text}",
        "",
        governance_text,
        "",
        "Integrity:",
        "",
        f"- source run: `{latest['run_id']}`; artifact ID: `{latest['artifact_id']}`;",
        f"- artifact SHA-256: `{latest['artifact_sha256']}`;",
        f"- ledger chain tip: `{latest['ledger_chain_tip_sha256']}`;",
        f"- locked checkpoint: [`{latest['checkpoint_path']}`]({latest['checkpoint_path']});",
        f"- snapshot registry: [`reports/monitoring/V0_26_FORWARD_SNAPSHOT_REGISTRY.json`](reports/monitoring/V0_26_FORWARD_SNAPSHOT_REGISTRY.json).",
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
        "### v0.27 development candidate — locked, not yet validated",
        "",
        f"A single later development candidate is now byte-locked as `{V27_CANDIDATE}`. It retains the unchanged "
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
    checkpoint_path = Path(latest["checkpoint_path"])
    checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    section = build_v26_section(registry, checkpoint)

    before, remainder = text.split(START_HEADING, 1)
    _, after = remainder.split(END_HEADING, 1)
    updated = before.rstrip() + "\n\n" + section.rstrip() + "\n\n" + END_HEADING + after
    readme_path.write_text(updated, encoding="utf-8")
    return updated


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--readme", default="README.md")
    ap.add_argument(
        "--registry", default="reports/monitoring/V0_26_FORWARD_SNAPSHOT_REGISTRY.json"
    )
    args = ap.parse_args()
    update_readme(readme_path=Path(args.readme), registry_path=Path(args.registry))


if __name__ == "__main__":
    main()
