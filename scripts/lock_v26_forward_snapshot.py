#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

import pandas as pd

from gb_power_market.forward_ledger_v26 import (
    load_v26_locked_ledger,
    verify_v26_ledger_chain,
    verify_v26_locked_prefix,
)


EXPECTED_CANDIDATE = "2H_FROZEN_PLUS_CAUSAL_6H_48H_CONSENSUS_CLIPPED_RESIDUAL"
REGISTRY_SCHEMA = "gb-power-market-v26-forward-snapshot-registry-v1"
PROVENANCE_SCHEMA = "gb-power-market-v26-execution-provenance-v1"
IMPLEMENTATION_LOCK_SCHEMA = "gb-power-market-v26-implementation-lock-v1"
FORWARD_START_UTC = "2026-08-22T20:30:00Z"
IMPLEMENTATION_LOCK_PATH = Path("reports/locked/V0_26_IMPLEMENTATION_LOCK.json")


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _utc(value: str) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    if ts.tzinfo is None:
        raise ValueError("snapshot boundary must be timezone-aware")
    return ts.tz_convert("UTC")


def _slug(end_exclusive_utc: pd.Timestamp) -> str:
    return end_exclusive_utc.strftime("%Y-%m-%d_%H%MZ")


def _copy_exact(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)
    if source.read_bytes() != destination.read_bytes():
        raise RuntimeError(f"byte-exact snapshot copy failed for {destination}")


def _validate_provenance(provenance: dict[str, Any], *, run_id: int) -> dict[str, Any]:
    implementation = json.loads(IMPLEMENTATION_LOCK_PATH.read_text(encoding="utf-8"))
    if implementation.get("schema") != IMPLEMENTATION_LOCK_SCHEMA:
        raise ValueError("unsupported v0.26 implementation lock")
    if provenance.get("schema") != PROVENANCE_SCHEMA:
        raise ValueError("unsupported v0.26 execution provenance")
    if provenance.get("version") != "0.26.0":
        raise ValueError("provenance v0.26 version changed")
    if provenance.get("candidate") != EXPECTED_CANDIDATE:
        raise ValueError("provenance candidate identity changed")
    if _utc(str(provenance.get("forward_start_utc"))) != _utc(FORWARD_START_UTC):
        raise ValueError("provenance forward boundary changed")
    if int(provenance.get("source_run_id", -1)) != int(run_id):
        raise ValueError("provenance source run does not match requested artifact run")
    if provenance.get("candidate_source") != implementation.get("candidate_source"):
        raise ValueError("provenance predictive source identity changed")
    if provenance.get("frozen_model_state") != implementation.get("frozen_model_state"):
        raise ValueError("provenance frozen model state identity changed")
    if provenance.get("implementation_lock_path") != IMPLEMENTATION_LOCK_PATH.as_posix():
        raise ValueError("provenance implementation lock path changed")
    execution_commit = str(provenance.get("execution_commit_sha", ""))
    if len(execution_commit) != 40:
        raise ValueError("provenance execution commit SHA is invalid")
    return implementation


def _result_markdown(
    *,
    summary: dict[str, Any],
    provenance: dict[str, Any],
    sequence: int,
    new_rows: int,
    artifact_id: int,
    artifact_sha256: str,
    run_id: int,
    checkpoint_sha256: str,
    provenance_sha256: str,
    ledger_sha256: str,
    chain_tip: str,
) -> str:
    forward = summary["forward_segment"]
    monitor = summary["monitor"]
    alerts = monitor.get("alerts", [])
    alert_text = ", ".join(f"`{x}`" for x in alerts) if alerts else "none"
    lines = [
        f"# v0.26 forward snapshot {sequence}",
        "",
        f"Locked unchanged candidate: `{EXPECTED_CANDIDATE}`.",
        "",
        f"- forward rows: **{forward['rows']}** ({new_rows} new since the preceding locked snapshot);",
        f"- end exclusive: `{forward['end_exclusive_utc']}`;",
        f"- candidate MAE: **{forward['candidate_mae_gbp_mwh']:.3f} £/MWh**;",
        f"- frozen-model MAE: **{forward['frozen_mae_gbp_mwh']:.3f} £/MWh**;",
        f"- v0.25 MAE: **{forward['v25_mae_gbp_mwh']:.3f} £/MWh**;",
        f"- previous-day reference MAE: **{forward['reference_mae_gbp_mwh']:.3f} £/MWh**;",
        f"- candidate improvement vs frozen: **{forward['candidate_improvement_vs_frozen_pct']:.1f}%**;",
        f"- candidate improvement vs reference: **{forward['candidate_improvement_vs_reference_pct']:.1f}%**;",
        f"- maturity: `{monitor['maturity_stage']}`;",
        f"- alert status: `{monitor['alert_status']}`; alerts: {alert_text};",
        f"- promotion status: `{summary['promotion_readiness']['status']}`.",
        "",
        "## Integrity",
        "",
        f"- GitHub Actions run: `{run_id}`;",
        f"- execution commit: `{provenance['execution_commit_sha']}`;",
        f"- predictive source blob: `{provenance['candidate_source']['git_blob_sha1']}`;",
        f"- frozen model-state SHA-256: `{provenance['frozen_model_state']['sha256']}`;",
        f"- artifact ID: `{artifact_id}`;",
        f"- artifact SHA-256: `{artifact_sha256}`;",
        f"- locked checkpoint SHA-256: `{checkpoint_sha256}`;",
        f"- locked provenance SHA-256: `{provenance_sha256}`;",
        f"- locked ledger SHA-256: `{ledger_sha256}`;",
        f"- ledger chain tip: `{chain_tip}`.",
        "",
        "Rows before the v0.26 forward boundary are development diagnostics, not fresh v0.26 evidence.",
        "Public-data metrics are forecasting evidence, not realised trading P&L.",
        "",
    ]
    return "\n".join(lines)


def lock_snapshot(
    *,
    artifact_dir: Path,
    registry_path: Path,
    monitoring_dir: Path,
    docs_dir: Path,
    artifact_id: int,
    artifact_sha256: str,
    run_id: int,
) -> dict[str, Any]:
    summary_source = artifact_dir / "v26_summary.json"
    ledger_source = artifact_dir / "v26_forward_ledger.csv"
    provenance_source = artifact_dir / "v26_implementation_provenance.json"
    if not summary_source.is_file() or not ledger_source.is_file() or not provenance_source.is_file():
        raise FileNotFoundError(
            "artifact must contain v26_summary.json, v26_forward_ledger.csv and v26_implementation_provenance.json"
        )

    summary = json.loads(summary_source.read_text(encoding="utf-8"))
    provenance = json.loads(provenance_source.read_text(encoding="utf-8"))
    _validate_provenance(provenance, run_id=run_id)

    spec = summary.get("candidate_spec", {})
    if spec.get("version") != "0.26.0":
        raise ValueError("artifact v0.26 version changed")
    if spec.get("candidate") != EXPECTED_CANDIDATE:
        raise ValueError("artifact candidate identity changed")
    start = _utc(str(spec.get("forward_start_utc")))
    if start != _utc(FORWARD_START_UTC):
        raise ValueError("artifact forward boundary changed")

    forward = summary.get("forward_segment", {})
    rows = int(forward.get("rows", 0))
    if rows <= 0:
        raise ValueError("artifact summary contains no v0.26 forward rows")
    end = _utc(str(forward.get("end_exclusive_utc")))
    if end <= start:
        raise ValueError("artifact forward end must be later than the v0.26 start")

    current_ledger = load_v26_locked_ledger(ledger_source)
    verify_v26_ledger_chain(current_ledger)
    if len(current_ledger) != rows:
        raise ValueError("summary row count and ledger row count differ")
    current_tip = str(current_ledger.iloc[-1]["chain_sha256"])

    ledger_integrity = summary.get("ledger_integrity", {})
    if ledger_integrity.get("status") != "LOCKED_PREFIX_REPRODUCED":
        raise ValueError("artifact did not reproduce a locked v0.26 prefix")

    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    if registry.get("schema") != REGISTRY_SCHEMA or registry.get("append_only") is not True:
        raise ValueError("unsupported or non-append-only v0.26 snapshot registry")
    if registry.get("candidate") != EXPECTED_CANDIDATE:
        raise ValueError("registry candidate identity changed")
    if _utc(str(registry.get("forward_start_utc"))) != _utc(FORWARD_START_UTC):
        raise ValueError("registry forward boundary changed")

    snapshots = list(registry.get("snapshots", []))
    if not snapshots:
        raise ValueError("snapshot registry must already contain the v0.26 genesis snapshot")
    latest = snapshots[-1]
    if int(latest["sequence"]) != len(snapshots):
        raise ValueError("snapshot registry sequence is not contiguous")

    previous_rows = int(latest["rows"])
    previous_end = _utc(str(latest["end_exclusive_utc"]))
    if rows <= previous_rows:
        raise ValueError(f"snapshot is not an append: {rows} <= {previous_rows}")
    if end <= previous_end:
        raise ValueError("snapshot end did not advance")

    previous_ledger_path = Path(str(latest["ledger_path"]))
    previous_ledger = load_v26_locked_ledger(previous_ledger_path)
    prefix = verify_v26_locked_prefix(current_ledger, previous_ledger)
    if int(prefix["locked_rows"]) != previous_rows:
        raise ValueError("latest registry row count does not match its ledger")
    if prefix["locked_chain_tip_sha256"] != str(latest["ledger_chain_tip_sha256"]):
        raise ValueError("latest registry chain tip does not match its ledger")
    if int(prefix["new_rows_after_locked_prefix"]) != rows - previous_rows:
        raise ValueError("new row count does not match prefix extension")
    if int(ledger_integrity.get("locked_rows", -1)) != previous_rows:
        raise ValueError("artifact locked-prefix row count is not the latest registered snapshot")
    if ledger_integrity.get("locked_chain_tip_sha256") != str(latest["ledger_chain_tip_sha256"]):
        raise ValueError("artifact locked-prefix chain tip is not the latest registered snapshot")

    sequence = int(latest["sequence"]) + 1
    slug = _slug(end)
    checkpoint_dest = monitoring_dir / f"V0_26_FORWARD_CHECKPOINT_{slug}.json"
    provenance_dest = monitoring_dir / f"V0_26_IMPLEMENTATION_PROVENANCE_{slug}.json"
    ledger_dest = monitoring_dir / f"V0_26_FORWARD_LEDGER_{slug}.csv"
    doc_path = docs_dir / f"V0_26_FORWARD_RESULTS_{slug}.md"
    destinations = [
        checkpoint_dest,
        provenance_dest,
        ledger_dest,
        checkpoint_dest.with_suffix(checkpoint_dest.suffix + ".sha256"),
        provenance_dest.with_suffix(provenance_dest.suffix + ".sha256"),
        ledger_dest.with_suffix(ledger_dest.suffix + ".sha256"),
        doc_path,
    ]
    if any(path.exists() for path in destinations):
        raise FileExistsError("snapshot destination already exists; refusing to rewrite history")

    _copy_exact(summary_source, checkpoint_dest)
    _copy_exact(provenance_source, provenance_dest)
    _copy_exact(ledger_source, ledger_dest)
    checkpoint_sha = sha256_file(checkpoint_dest)
    provenance_sha = sha256_file(provenance_dest)
    ledger_sha = sha256_file(ledger_dest)
    checkpoint_dest.with_suffix(checkpoint_dest.suffix + ".sha256").write_text(
        f"{checkpoint_sha}  {checkpoint_dest.name}\n", encoding="utf-8"
    )
    provenance_dest.with_suffix(provenance_dest.suffix + ".sha256").write_text(
        f"{provenance_sha}  {provenance_dest.name}\n", encoding="utf-8"
    )
    ledger_dest.with_suffix(ledger_dest.suffix + ".sha256").write_text(
        f"{ledger_sha}  {ledger_dest.name}\n", encoding="utf-8"
    )

    monitor = summary["monitor"]
    entry = {
        "sequence": sequence,
        "end_exclusive_utc": end.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "rows": rows,
        "new_rows": rows - previous_rows,
        "run_id": int(run_id),
        "artifact_id": int(artifact_id),
        "artifact_sha256": str(artifact_sha256),
        "checkpoint_path": checkpoint_dest.as_posix(),
        "checkpoint_sha256": checkpoint_sha,
        "provenance_path": provenance_dest.as_posix(),
        "provenance_sha256": provenance_sha,
        "ledger_path": ledger_dest.as_posix(),
        "ledger_sha256": ledger_sha,
        "ledger_chain_tip_sha256": current_tip,
        "maturity_stage": str(monitor["maturity_stage"]),
        "alert_status": str(monitor.get("alert_status")),
        "alerts": list(monitor.get("alerts", [])),
    }

    docs_dir.mkdir(parents=True, exist_ok=True)
    doc_path.write_text(
        _result_markdown(
            summary=summary,
            provenance=provenance,
            sequence=sequence,
            new_rows=rows - previous_rows,
            artifact_id=artifact_id,
            artifact_sha256=artifact_sha256,
            run_id=run_id,
            checkpoint_sha256=checkpoint_sha,
            provenance_sha256=provenance_sha,
            ledger_sha256=ledger_sha,
            chain_tip=current_tip,
        ),
        encoding="utf-8",
    )

    snapshots.append(entry)
    registry["snapshots"] = snapshots
    registry_path.write_text(json.dumps(registry, indent=2) + "\n", encoding="utf-8")

    return {
        "status": "SNAPSHOT_LOCKED",
        "sequence": sequence,
        "rows": rows,
        "new_rows": rows - previous_rows,
        "end_exclusive_utc": end.isoformat(),
        "checkpoint_path": checkpoint_dest.as_posix(),
        "checkpoint_sha256": checkpoint_sha,
        "provenance_path": provenance_dest.as_posix(),
        "provenance_sha256": provenance_sha,
        "ledger_path": ledger_dest.as_posix(),
        "ledger_sha256": ledger_sha,
        "ledger_chain_tip_sha256": current_tip,
        "doc_path": doc_path.as_posix(),
        "alert_status": monitor.get("alert_status"),
        "alerts": monitor.get("alerts", []),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--artifact-dir", required=True)
    ap.add_argument("--registry", default="reports/monitoring/V0_26_FORWARD_SNAPSHOT_REGISTRY.json")
    ap.add_argument("--monitoring-dir", default="reports/monitoring")
    ap.add_argument("--docs-dir", default="docs")
    ap.add_argument("--artifact-id", required=True, type=int)
    ap.add_argument("--artifact-sha256", required=True)
    ap.add_argument("--run-id", required=True, type=int)
    args = ap.parse_args()

    result = lock_snapshot(
        artifact_dir=Path(args.artifact_dir),
        registry_path=Path(args.registry),
        monitoring_dir=Path(args.monitoring_dir),
        docs_dir=Path(args.docs_dir),
        artifact_id=args.artifact_id,
        artifact_sha256=args.artifact_sha256,
        run_id=args.run_id,
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
