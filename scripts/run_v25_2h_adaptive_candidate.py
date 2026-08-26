#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from gb_power_market.adaptive_bias_v25 import (
    V25_FORWARD_START_UTC,
    apply_causal_bias_correction,
    candidate_spec,
    summarise_candidate,
)
from gb_power_market.adaptive_monitor_v25 import build_adaptive_monitor_state
from gb_power_market.forward_ledger_v25 import (
    build_forward_ledger,
    load_locked_ledger,
    verify_locked_prefix,
)
from gb_power_market.promotion_gate_v25 import assess_promotion_readiness


FIRST_V25_FORWARD_ARTIFACT_SHA256 = "64d30a6e18a2c3fa2243fa28ceb800afec1abc66f7dc0816515d96ff9faf885c"
FIRST_V25_LEDGER_CHAIN_TIP_SHA256 = "b27a99b21466c8a4cbf58d29ad9c980a174b278cee1a741582a978af747789f2"
FIRST_V25_LEDGER_ROWS = 6
GENESIS_LEDGER_PATH = Path("reports/monitoring/V0_25_FORWARD_LEDGER_FIRST6.csv")
SNAPSHOT_REGISTRY_PATH = Path("reports/monitoring/V0_25_FORWARD_SNAPSHOT_REGISTRY.json")


def _segment(rows: pd.DataFrame, start: str, end: str | None = None) -> dict:
    x = rows[pd.to_datetime(rows["target_start_utc"], utc=True) >= pd.Timestamp(start)].copy()
    if end is not None:
        x = x[pd.to_datetime(x["target_start_utc"], utc=True) < pd.Timestamp(end)].copy()
    if x.empty:
        return {"rows": 0}
    y = x["realised_price_gbp_mwh"].astype(float)
    frozen = x["frozen_prediction_gbp_mwh"].astype(float)
    adaptive = x["adaptive_prediction_gbp_mwh"].astype(float)
    reference = x["previous_settlement_day_reference_gbp_mwh"].astype(float)
    frozen_mae = float((y - frozen).abs().mean())
    adaptive_mae = float((y - adaptive).abs().mean())
    reference_mae = float((y - reference).abs().mean())
    return {
        "rows": int(len(x)),
        "start_utc": pd.to_datetime(x["target_start_utc"], utc=True).min().isoformat(),
        "end_exclusive_utc": (pd.to_datetime(x["target_start_utc"], utc=True).max() + pd.Timedelta(minutes=30)).isoformat(),
        "frozen_model_mae_gbp_mwh": frozen_mae,
        "adaptive_candidate_mae_gbp_mwh": adaptive_mae,
        "reference_mae_gbp_mwh": reference_mae,
        "adaptive_improvement_vs_reference_pct": 100.0 * (reference_mae - adaptive_mae) / reference_mae if reference_mae else None,
        "adaptive_improvement_vs_frozen_pct": 100.0 * (frozen_mae - adaptive_mae) / frozen_mae if frozen_mae else None,
        "adaptive_win_rate_vs_reference": float(((y - adaptive).abs() < (y - reference).abs()).mean()),
        "mean_bias_correction_gbp_mwh": float(x["bias_correction_gbp_mwh"].mean()),
        "mean_history_rows": float(x["bias_history_rows"].mean()),
    }


def _registry_latest(path: Path) -> dict:
    registry = json.loads(path.read_text(encoding="utf-8"))
    if registry.get("candidate") != "2H_FROZEN_PLUS_CAUSAL_48H_RESIDUAL_MEAN":
        raise SystemExit("v0.25 snapshot registry candidate identity changed")
    snapshots = registry.get("snapshots", [])
    if not snapshots:
        raise SystemExit("v0.25 snapshot registry has no locked snapshots")
    latest = snapshots[-1]
    if int(latest["sequence"]) != len(snapshots):
        raise SystemExit("v0.25 snapshot registry sequence is not contiguous")
    return latest


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--v24-rows", default="reports/v24_forward/forward_rows_2h.csv")
    ap.add_argument("--out-dir", default="reports/v25_2h")
    ap.add_argument(
        "--locked-ledger",
        default=None,
        help="Optional explicit latest immutable prefix. By default use the latest ledger in the snapshot registry.",
    )
    ap.add_argument(
        "--snapshot-registry",
        default=str(SNAPSHOT_REGISTRY_PATH),
        help="Append-only registry whose latest ledger must be reproduced before new rows are accepted.",
    )
    ap.add_argument(
        "--genesis-ledger",
        default=str(GENESIS_LEDGER_PATH),
        help="Permanent first-six genesis ledger anchor.",
    )
    ap.add_argument(
        "--previous-snapshot-sha256",
        default=None,
        help="Optional explicit previous monitor digest. By default use the latest registry monitor SHA-256.",
    )
    args = ap.parse_args()

    rows = pd.read_csv(args.v24_rows)
    corrected = apply_causal_bias_correction(rows)
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    corrected.to_csv(out / "adaptive_rows_2h.csv", index=False)
    spec = candidate_spec()

    current_ledger = build_forward_ledger(corrected, forward_start_utc=V25_FORWARD_START_UTC)

    genesis = load_locked_ledger(args.genesis_ledger)
    genesis_check = verify_locked_prefix(current_ledger, genesis)
    if genesis_check["locked_rows"] != FIRST_V25_LEDGER_ROWS:
        raise SystemExit("v0.25 genesis ledger row count changed")
    if genesis_check["locked_chain_tip_sha256"] != FIRST_V25_LEDGER_CHAIN_TIP_SHA256:
        raise SystemExit("v0.25 genesis ledger chain tip changed")

    latest_snapshot = _registry_latest(Path(args.snapshot_registry))
    latest_ledger_path = Path(args.locked_ledger or latest_snapshot["ledger_path"])
    latest_locked = load_locked_ledger(latest_ledger_path)
    latest_check = verify_locked_prefix(current_ledger, latest_locked)
    if int(latest_check["locked_rows"]) != int(latest_snapshot["rows"]):
        raise SystemExit("latest locked ledger row count disagrees with snapshot registry")
    if latest_check["locked_chain_tip_sha256"] != latest_snapshot["ledger_chain_tip_sha256"]:
        raise SystemExit("latest locked ledger chain tip disagrees with snapshot registry")

    ledger_check = {
        **latest_check,
        "locked_registry_sequence": int(latest_snapshot["sequence"]),
        "locked_registry_ledger_path": str(latest_ledger_path),
        "genesis_anchor": genesis_check,
    }
    current_ledger.to_csv(out / "forward_ledger_2h.csv", index=False, lineterminator="\n")
    (out / "forward_ledger_check.json").write_text(json.dumps(ledger_check, indent=2), encoding="utf-8")

    summary = {
        "version": "0.25.0",
        "status": "2H_ADAPTIVE_CANDIDATE_REPLAYED",
        "candidate_spec": spec,
        "ledger_integrity": ledger_check,
        "development_diagnostics": {
            "locked_v20_window": _segment(corrected, "2026-07-12T12:00:00Z", "2026-08-15T07:30:00Z"),
            "august_1_to_forward_start": _segment(corrected, "2026-08-01T00:00:00Z", V25_FORWARD_START_UTC.isoformat()),
            "post_lock_to_forward_start": _segment(corrected, "2026-08-15T07:30:00Z", V25_FORWARD_START_UTC.isoformat()),
        },
        "new_forward_segment": summarise_candidate(corrected, start_utc=V25_FORWARD_START_UTC),
        "claim_boundary": (
            "Development diagnostics use previously inspected observations and are not new independent evidence. "
            "Only rows at or after 2026-08-21T11:30:00Z belong to the v0.25 versioned forward segment."
        ),
    }

    previous_snapshot_sha = args.previous_snapshot_sha256 or latest_snapshot["monitor_sha256"]
    monitor = build_adaptive_monitor_state(
        corrected,
        forward_start_utc=V25_FORWARD_START_UTC,
        candidate_id=spec["candidate"],
        model_version=spec["version"],
        previous_snapshot_sha256=previous_snapshot_sha,
    )
    monitor["ledger_integrity"] = ledger_check
    promotion = assess_promotion_readiness(monitor)
    monitor["promotion_readiness"] = promotion
    summary["promotion_readiness"] = promotion

    (out / "v25_2h_summary.json").write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    (out / "v25_2h_candidate_spec.json").write_text(json.dumps(spec, indent=2, default=str), encoding="utf-8")
    (out / "v25_monitor_state.json").write_text(json.dumps(monitor, indent=2, default=str), encoding="utf-8")
    print(json.dumps({"summary": summary, "monitor": monitor}, indent=2, default=str))


if __name__ == "__main__":
    main()
