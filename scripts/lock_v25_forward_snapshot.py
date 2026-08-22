#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

import pandas as pd

from gb_power_market.forward_ledger_v25 import load_locked_ledger, verify_ledger_chain, verify_locked_prefix


EXPECTED_CANDIDATE = "2H_FROZEN_PLUS_CAUSAL_48H_RESIDUAL_MEAN"
REGISTRY_SCHEMA = "gb-power-market-v25-forward-snapshot-registry-v1"


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


def _result_markdown(
    *,
    monitor: dict[str, Any],
    sequence: int,
    new_rows: int,
    artifact_id: int,
    artifact_sha256: str,
    run_id: int,
    ledger_sha256: str,
    chain_tip: str,
) -> str:
    cumulative = monitor["cumulative"]
    last24 = monitor["rolling"].get("last_24h", {})
    alerts = monitor.get("alerts", [])
    alert_text = ", ".join(f"`{x}`" for x in alerts) if alerts else "none"
    lines = [
        f"# v0.25 forward snapshot {sequence}",
        "",
        f"Locked unchanged candidate: `{monitor['candidate']}`.",
        "",
        f"- forward rows: **{cumulative['rows']}** ({new_rows} new since the preceding locked snapshot);",
        f"- end exclusive: `{cumulative['end_exclusive_utc']}`;",
        f"- adaptive MAE: **{cumulative['adaptive_mae_gbp_mwh']:.3f} £/MWh**;",
        f"- frozen-model MAE: **{cumulative['frozen_mae_gbp_mwh']:.3f} £/MWh**;",
        f"- previous-day reference MAE: **{cumulative['reference_mae_gbp_mwh']:.3f} £/MWh**;",
        f"- cumulative adaptive improvement vs reference: **{cumulative['adaptive_improvement_vs_reference_pct']:.1f}%**;",
        f"- cumulative adaptive improvement vs frozen: **{cumulative['adaptive_improvement_vs_frozen_pct']:.1f}%**;",
        f"- maturity: `{monitor['maturity_stage']}`;",
        f"- alert status: `{monitor['alert_status']}`; alerts: {alert_text};",
        f"- promotion status: `{monitor['promotion_readiness']['status']}`.",
        "",
    ]
    if last24.get("rows") == 48:
        lines += [
            "## Predeclared latest-24h monitor",
            "",
            f"- adaptive MAE: **{last24['adaptive_mae_gbp_mwh']:.3f} £/MWh**;",
            f"- frozen MAE: **{last24['frozen_mae_gbp_mwh']:.3f} £/MWh**;",
            f"- reference MAE: **{last24['reference_mae_gbp_mwh']:.3f} £/MWh**;",
            f"- adaptive signed bias: **{last24['adaptive_signed_bias_gbp_mwh']:.3f} £/MWh**;",
            f"- frozen signed bias: **{last24['frozen_signed_bias_gbp_mwh']:.3f} £/MWh**;",
            f"- adaptive P95 absolute error: **{last24['adaptive_p95_abs_error_gbp_mwh']:.3f} £/MWh**;",
            f"- frozen P95 absolute error: **{last24['frozen_p95_abs_error_gbp_mwh']:.3f} £/MWh**.",
            "",
            "The alert rules were fixed before these 48 rows were available. Triggered alerts are preserved rather than tuned away.",
            "",
        ]
    lines += [
        "## Integrity",
        "",
        f"- GitHub Actions run: `{run_id}`;",
        f"- artifact ID: `{artifact_id}`;",
        f"- artifact SHA-256: `{artifact_sha256}`;",
        f"- locked ledger SHA-256: `{ledger_sha256}`;",
        f"- ledger chain tip: `{chain_tip}`.",
        "",
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
    monitor_source = artifact_dir / "v25_monitor_state.json"
    ledger_source = artifact_dir / "forward_ledger_2h.csv"
    if not monitor_source.is_file() or not ledger_source.is_file():
        raise FileNotFoundError("artifact must contain v25_monitor_state.json and forward_ledger_2h.csv")

    monitor = json.loads(monitor_source.read_text(encoding="utf-8"))
    if monitor.get("candidate") != EXPECTED_CANDIDATE:
        raise ValueError("artifact candidate identity changed")
    cumulative = monitor.get("cumulative", {})
    rows = int(cumulative.get("rows", 0))
    end = _utc(str(cumulative.get("end_exclusive_utc")))
    if rows <= 0:
        raise ValueError("artifact monitor contains no forward rows")

    current_ledger = load_locked_ledger(ledger_source)
    verify_ledger_chain(current_ledger)
    if len(current_ledger) != rows:
        raise ValueError("monitor row count and ledger row count differ")
    current_tip = str(current_ledger.iloc[-1]["chain_sha256"])

    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    if registry.get("schema") != REGISTRY_SCHEMA or registry.get("append_only") is not True:
        raise ValueError("unsupported or non-append-only v0.25 snapshot registry")
    if registry.get("candidate") != EXPECTED_CANDIDATE:
        raise ValueError("registry candidate identity changed")
    snapshots = list(registry.get("snapshots", []))
    if not snapshots:
        raise ValueError("snapshot registry must already contain a genesis snapshot")

    latest = snapshots[-1]
    previous_rows = int(latest["rows"])
    previous_end = _utc(str(latest["end_exclusive_utc"]))
    if rows <= previous_rows:
        raise ValueError(f"snapshot is not an append: {rows} <= {previous_rows}")
    if end <= previous_end:
        raise ValueError("snapshot end did not advance")

    previous_ledger_path = Path(str(latest["ledger_path"]))
    previous_ledger = load_locked_ledger(previous_ledger_path)
    prefix = verify_locked_prefix(current_ledger, previous_ledger)
    if prefix["locked_chain_tip_sha256"] != str(latest["ledger_chain_tip_sha256"]):
        raise ValueError("latest registry chain tip does not match the registered ledger")
    if prefix["new_rows_after_locked_prefix"] != rows - previous_rows:
        raise ValueError("new row count does not match prefix extension")

    sequence = int(latest["sequence"]) + 1
    slug = _slug(end)
    monitor_dest = monitoring_dir / f"V0_25_MONITOR_STATE_{slug}.json"
    ledger_dest = monitoring_dir / f"V0_25_FORWARD_LEDGER_{slug}.csv"
    if monitor_dest.exists() or ledger_dest.exists():
        raise FileExistsError("snapshot destination already exists; refusing to rewrite history")

    _copy_exact(monitor_source, monitor_dest)
    _copy_exact(ledger_source, ledger_dest)
    monitor_sha = sha256_file(monitor_dest)
    ledger_sha = sha256_file(ledger_dest)
    (monitor_dest.with_suffix(monitor_dest.suffix + ".sha256")).write_text(
        f"{monitor_sha}  {monitor_dest.name}\n", encoding="utf-8"
    )
    (ledger_dest.with_suffix(ledger_dest.suffix + ".sha256")).write_text(
        f"{ledger_sha}  {ledger_dest.name}\n", encoding="utf-8"
    )

    entry = {
        "sequence": sequence,
        "end_exclusive_utc": end.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "rows": rows,
        "new_rows": rows - previous_rows,
        "run_id": int(run_id),
        "artifact_id": int(artifact_id),
        "artifact_sha256": str(artifact_sha256),
        "monitor_path": monitor_dest.as_posix(),
        "monitor_sha256": monitor_sha,
        "ledger_path": ledger_dest.as_posix(),
        "ledger_sha256": ledger_sha,
        "ledger_chain_tip_sha256": current_tip,
        "maturity_stage": str(monitor["maturity_stage"]),
        "alert_status": str(monitor.get("alert_status")),
        "alerts": list(monitor.get("alerts", [])),
    }
    snapshots.append(entry)
    registry["snapshots"] = snapshots
    registry_path.write_text(json.dumps(registry, indent=2) + "\n", encoding="utf-8")

    docs_dir.mkdir(parents=True, exist_ok=True)
    doc_path = docs_dir / f"V0_25_FORWARD_RESULTS_{slug}.md"
    doc_path.write_text(
        _result_markdown(
            monitor=monitor,
            sequence=sequence,
            new_rows=rows - previous_rows,
            artifact_id=artifact_id,
            artifact_sha256=artifact_sha256,
            run_id=run_id,
            ledger_sha256=ledger_sha,
            chain_tip=current_tip,
        ),
        encoding="utf-8",
    )

    return {
        "status": "SNAPSHOT_LOCKED",
        "sequence": sequence,
        "rows": rows,
        "new_rows": rows - previous_rows,
        "end_exclusive_utc": end.isoformat(),
        "monitor_path": monitor_dest.as_posix(),
        "monitor_sha256": monitor_sha,
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
    ap.add_argument("--registry", default="reports/monitoring/V0_25_FORWARD_SNAPSHOT_REGISTRY.json")
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
