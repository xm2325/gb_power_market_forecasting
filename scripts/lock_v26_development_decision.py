#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

EXPECTED_SOURCE_ARTIFACT_SHA256 = "eb2585458aaddb15a2485b4f5c349e8f90917cfc97bbdbe179cf95009e90ab95"
EXPECTED_DEVELOPMENT_END = "2026-08-22T20:30:00+00:00"
EXPECTED_VALIDATION_ROWS = 96
EXPECTED_FORWARD_START = "2026-08-23T02:00:00+00:00"
EXPECTED_STATUS = "BLOCKED_BY_CHRONOLOGICAL_DEVELOPMENT_VALIDATION"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _exact_copy(source: Path, destination: Path) -> None:
    if destination.exists():
        raise FileExistsError(f"refusing to rewrite locked v0.26 evidence: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)
    if source.read_bytes() != destination.read_bytes():
        raise RuntimeError(f"byte-exact copy failed: {destination}")


def _metric_table(label: str, metrics: dict[str, Any]) -> list[str]:
    return [
        f"| {label} | {metrics['mae_gbp_mwh']:.6f} | {metrics['p95_abs_error_gbp_mwh']:.6f} | {metrics['signed_bias_gbp_mwh']:.6f} |",
    ]


def build_markdown(decision: dict[str, Any], artifact_id: int, artifact_sha256: str, run_id: int) -> str:
    selected = decision["selected"]
    val = selected["validation_diagnostic"] if selected else None
    sel = selected["selection"] if selected else None
    base_sel = decision["baseline_selection"]
    base_val = decision["baseline_validation"]
    guards = decision["validation_guards"]

    lines = [
        "# v0.26 causal EWMA development decision",
        "",
        f"Status: **`{decision['status']}`**.",
        "",
        "v0.26 was developed only on observations already available through `2026-08-22T20:30Z`. The last 96 observed half-hours were excluded from half-life/shrinkage selection and used only as chronological development validation.",
        "",
        f"Selection winner: **`{selected['candidate'] if selected else 'none'}`**.",
        "",
        "## Selection block",
        "",
        "| Model | MAE £/MWh | P95 abs error £/MWh | Signed bias £/MWh |",
        "|---|---:|---:|---:|",
    ]
    if selected:
        lines += _metric_table(selected["candidate"], sel)
    lines += _metric_table("Frozen 2h", base_sel["frozen"])
    lines += _metric_table("Previous-day reference", base_sel["reference"])
    lines += [
        "",
        "## Held-out 96-row development validation",
        "",
        "| Model | MAE £/MWh | P95 abs error £/MWh | Signed bias £/MWh |",
        "|---|---:|---:|---:|",
    ]
    if selected:
        lines += _metric_table(selected["candidate"], val)
    lines += _metric_table("Frozen 2h", base_val["frozen"])
    lines += _metric_table("Previous-day reference", base_val["reference"])
    lines += [
        "",
        "Validation gates:",
        "",
        f"- MAE better than frozen: **{guards['mae_better_than_frozen']}**;",
        f"- MAE better than previous-day reference: **{guards['mae_better_than_reference']}**;",
        f"- P95 non-worse than frozen: **{guards['p95_non_worse_than_frozen']}**;",
        f"- absolute signed bias non-worse than frozen: **{guards['absolute_bias_non_worse_than_frozen']}**;",
        f"- all guards passed: **{guards['passed']}**.",
        "",
        "Because the selected EWMA rule failed the frozen-model MAE, tail and bias safeguards, **no v0.26 forward test is launched**. Changing the candidate family after opening this validation block requires a new version and a new future boundary; these 96 rows cannot be reused as independent validation.",
        "",
        "## Locked source",
        "",
        f"- workflow run: `{run_id}`;",
        f"- development artifact ID: `{artifact_id}`;",
        f"- development artifact SHA-256: `{artifact_sha256}`;",
        f"- source v0.25 artifact SHA-256: `{decision['source_artifact']['artifact_sha256']}`;",
        f"- latest input target: `{decision['source_artifact']['latest_input_target_start_utc']}`;",
        f"- development end exclusive: `{decision['development_end_exclusive_utc']}`;",
        f"- originally proposed forward start (not activated): `{decision['proposed_forward_start_utc']}`.",
        "",
        "This is development/model-governance evidence, not an accuracy claim and not trading P&L.",
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--artifact-dir", required=True)
    ap.add_argument("--artifact-id", required=True, type=int)
    ap.add_argument("--artifact-sha256", required=True)
    ap.add_argument("--run-id", required=True, type=int)
    ap.add_argument("--locked-dir", default="reports/locked")
    ap.add_argument("--docs-dir", default="docs")
    args = ap.parse_args()

    artifact_dir = Path(args.artifact_dir)
    decision_src = artifact_dir / "v26_candidate_decision.json"
    grid_src = artifact_dir / "v26_candidate_grid.csv"
    rows_src = artifact_dir / "v26_selected_development_rows.csv"
    if not decision_src.is_file() or not grid_src.is_file():
        raise FileNotFoundError("v0.26 artifact lacks decision or candidate grid")
    if args.artifact_sha256 != "b4d5b9e3f72da959d1a7f2a3786c5e87951e285efb8506d534f4c5305643af1d":
        raise ValueError("unexpected v0.26 development artifact digest")

    decision = json.loads(decision_src.read_text(encoding="utf-8"))
    if decision["status"] != EXPECTED_STATUS:
        raise ValueError(f"unexpected v0.26 decision status: {decision['status']}")
    if decision["forward_test_allowed"] is not False:
        raise ValueError("blocked v0.26 decision unexpectedly allows forward testing")
    if decision["development_end_exclusive_utc"] != EXPECTED_DEVELOPMENT_END:
        raise ValueError("v0.26 development boundary changed")
    if int(decision["validation_rows"]) != EXPECTED_VALIDATION_ROWS:
        raise ValueError("v0.26 validation row count changed")
    if decision["proposed_forward_start_utc"] != EXPECTED_FORWARD_START:
        raise ValueError("v0.26 proposed forward boundary changed")
    if decision["source_artifact"]["artifact_sha256"] != EXPECTED_SOURCE_ARTIFACT_SHA256:
        raise ValueError("v0.26 source artifact changed")
    guards = decision["validation_guards"]
    if guards["passed"] is not False:
        raise ValueError("v0.26 validation unexpectedly passed")
    expected_failures = {
        "mae_better_than_frozen": False,
        "p95_non_worse_than_frozen": False,
        "absolute_bias_non_worse_than_frozen": False,
        "mae_better_than_reference": True,
    }
    for key, expected in expected_failures.items():
        if guards[key] is not expected:
            raise ValueError(f"unexpected v0.26 validation guard {key}: {guards[key]}")

    locked_dir = Path(args.locked_dir)
    docs_dir = Path(args.docs_dir)
    locked_dir.mkdir(parents=True, exist_ok=True)
    docs_dir.mkdir(parents=True, exist_ok=True)
    decision_dst = locked_dir / "V0_26_DEVELOPMENT_DECISION.json"
    grid_dst = locked_dir / "V0_26_CANDIDATE_GRID.csv"
    rows_dst = locked_dir / "V0_26_SELECTED_DEVELOPMENT_ROWS.csv"
    meta_dst = locked_dir / "V0_26_DEVELOPMENT_LOCK.json"
    doc_dst = docs_dir / "V0_26_DEVELOPMENT_RESULT.md"

    for p in [decision_dst, grid_dst, meta_dst, doc_dst]:
        if p.exists():
            raise FileExistsError(f"refusing to rewrite v0.26 locked result: {p}")
    _exact_copy(decision_src, decision_dst)
    _exact_copy(grid_src, grid_dst)
    if rows_src.is_file():
        _exact_copy(rows_src, rows_dst)

    meta = {
        "schema": "gb-power-market-v26-development-lock-v1",
        "status": "LOCKED_NEGATIVE_DEVELOPMENT_DECISION",
        "decision_status": decision["status"],
        "forward_test_allowed": False,
        "selected_candidate": decision["selected"]["candidate"] if decision["selected"] else None,
        "development_run_id": int(args.run_id),
        "development_artifact_id": int(args.artifact_id),
        "development_artifact_sha256": args.artifact_sha256,
        "source_v25_artifact_sha256": decision["source_artifact"]["artifact_sha256"],
        "development_end_exclusive_utc": decision["development_end_exclusive_utc"],
        "validation_rows": decision["validation_rows"],
        "validation_guards": guards,
        "decision_file_sha256": sha256_file(decision_dst),
        "grid_file_sha256": sha256_file(grid_dst),
        "selected_rows_file_sha256": sha256_file(rows_dst) if rows_dst.exists() else None,
        "claim_boundary": "v0.26 development validation failed; no forward test was launched and no numerical v0.26 accuracy claim is permitted",
    }
    meta_dst.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    doc_dst.write_text(
        build_markdown(decision, args.artifact_id, args.artifact_sha256, args.run_id),
        encoding="utf-8",
    )

    print(json.dumps({
        "status": meta["status"],
        "selected_candidate": meta["selected_candidate"],
        "validation_guards": guards,
        "decision_sha256": meta["decision_file_sha256"],
        "grid_sha256": meta["grid_file_sha256"],
        "doc": doc_dst.as_posix(),
    }, indent=2))


if __name__ == "__main__":
    main()
