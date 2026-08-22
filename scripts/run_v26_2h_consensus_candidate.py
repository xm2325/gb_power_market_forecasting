#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from gb_power_market.adaptive_bias_v25 import apply_causal_bias_correction
from gb_power_market.adaptive_consensus_v26 import (
    V26_CANDIDATE_ID,
    V26_FORWARD_START_UTC,
    apply_causal_consensus_correction,
    candidate_spec,
)
from gb_power_market.forward_ledger_v26 import (
    build_v26_forward_ledger,
    load_v26_locked_ledger,
    verify_v26_locked_prefix,
)


V25_FORWARD_START = pd.Timestamp("2026-08-21T11:30:00Z")


def _metrics(x: pd.DataFrame) -> dict:
    if x.empty:
        return {"rows": 0}
    y = x["realised_price_gbp_mwh"].to_numpy(float)
    candidate = x["v26_prediction_gbp_mwh"].to_numpy(float)
    frozen = x["frozen_prediction_gbp_mwh"].to_numpy(float)
    reference = x["previous_settlement_day_reference_gbp_mwh"].to_numpy(float)
    v25 = x["v25_prediction_gbp_mwh"].to_numpy(float)
    c_abs = np.abs(y - candidate)
    f_abs = np.abs(y - frozen)
    r_abs = np.abs(y - reference)
    v25_abs = np.abs(y - v25)
    c_mae = float(c_abs.mean())
    f_mae = float(f_abs.mean())
    r_mae = float(r_abs.mean())
    v25_mae = float(v25_abs.mean())
    target = pd.to_datetime(x["target_start_utc"], utc=True)
    result = {
        "rows": int(len(x)),
        "start_utc": target.min().isoformat(),
        "end_exclusive_utc": (target.max() + pd.Timedelta(minutes=30)).isoformat(),
        "candidate_mae_gbp_mwh": c_mae,
        "frozen_mae_gbp_mwh": f_mae,
        "v25_mae_gbp_mwh": v25_mae,
        "reference_mae_gbp_mwh": r_mae,
        "candidate_improvement_vs_frozen_pct": 100.0 * (f_mae - c_mae) / f_mae if f_mae else None,
        "candidate_improvement_vs_v25_pct": 100.0 * (v25_mae - c_mae) / v25_mae if v25_mae else None,
        "candidate_improvement_vs_reference_pct": 100.0 * (r_mae - c_mae) / r_mae if r_mae else None,
        "candidate_win_rate_vs_frozen": float((c_abs < f_abs).mean()),
        "candidate_win_rate_vs_v25": float((c_abs < v25_abs).mean()),
        "candidate_win_rate_vs_reference": float((c_abs < r_abs).mean()),
        "candidate_signed_bias_gbp_mwh": float((candidate - y).mean()),
        "frozen_signed_bias_gbp_mwh": float((frozen - y).mean()),
        "v25_signed_bias_gbp_mwh": float((v25 - y).mean()),
        "candidate_p95_abs_error_gbp_mwh": float(np.quantile(c_abs, 0.95)),
        "frozen_p95_abs_error_gbp_mwh": float(np.quantile(f_abs, 0.95)),
        "v25_p95_abs_error_gbp_mwh": float(np.quantile(v25_abs, 0.95)),
        "reference_p95_abs_error_gbp_mwh": float(np.quantile(r_abs, 0.95)),
        "mean_correction_gbp_mwh": float(x["v26_correction_gbp_mwh"].mean()),
        "fallback_rate": float(
            (x["v26_gate_reason"] != "CONSENSUS_CLIPPED_CORRECTION").mean()
        ),
    }
    if "v26_interval_covered" in x.columns:
        result["candidate_interval_coverage"] = float(x["v26_interval_covered"].astype(float).mean())
        if "interval_covered" in x.columns:
            result["frozen_interval_coverage"] = float(x["interval_covered"].astype(float).mean())
    return result


def _slice(rows: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp | None = None) -> pd.DataFrame:
    target = pd.to_datetime(rows["target_start_utc"], utc=True)
    mask = target >= start
    if end is not None:
        mask &= target < end
    return rows.loc[mask].copy()


def _maturity(n: int) -> str:
    if n < 24:
        return "EARLY_ONLY"
    if n < 96:
        return "INTRADAY_TO_2DAY_MONITORING"
    if n < 336:
        return "MULTIDAY_MONITORING"
    return "ONE_WEEK_PLUS_FORWARD"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--v24-rows", default="reports/v24_forward/forward_rows_2h.csv")
    ap.add_argument("--out-dir", default="reports/v26_2h")
    ap.add_argument("--locked-ledger", default=None)
    args = ap.parse_args()

    rows = pd.read_csv(args.v24_rows)
    v25 = apply_causal_bias_correction(rows)
    corrected = apply_causal_consensus_correction(rows)
    corrected["v25_prediction_gbp_mwh"] = v25["adaptive_prediction_gbp_mwh"].to_numpy(float)
    corrected["v25_correction_gbp_mwh"] = v25["bias_correction_gbp_mwh"].to_numpy(float)

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    corrected.to_csv(out / "v26_rows_2h.csv", index=False, lineterminator="\n")

    ledger = build_v26_forward_ledger(corrected, forward_start_utc=V26_FORWARD_START_UTC)
    ledger.to_csv(out / "v26_forward_ledger.csv", index=False, lineterminator="\n")
    if args.locked_ledger:
        locked = load_v26_locked_ledger(args.locked_ledger)
        ledger_integrity = verify_v26_locked_prefix(ledger, locked)
    else:
        ledger_integrity = {
            "status": "FIRST_VERSIONED_FORWARD_LEDGER",
            "locked_rows": 0,
            "current_rows": int(len(ledger)),
            "new_rows_after_locked_prefix": int(len(ledger)),
            "current_chain_tip_sha256": (
                str(ledger.iloc[-1]["chain_sha256"]) if len(ledger) else None
            ),
        }

    development = _slice(corrected, V25_FORWARD_START, V26_FORWARD_START_UTC)
    forward = _slice(corrected, V26_FORWARD_START_UTC)
    n = int(len(forward))

    rolling: dict[str, dict] = {}
    for name, width in (("last_6h", 12), ("last_24h", 48), ("last_3d", 144), ("last_7d", 336)):
        rolling[name] = _metrics(forward.tail(width)) if n >= width else {
            "rows": n,
            "status": f"INSUFFICIENT_ROWS_NEED_{width}",
        }

    alerts: list[str] = []
    if n < 48:
        alert_status = "INSUFFICIENT_SAMPLE_FOR_ALERTS"
    else:
        last24 = rolling["last_24h"]
        if last24["candidate_mae_gbp_mwh"] > last24["frozen_mae_gbp_mwh"]:
            alerts.append("V26_TRAILS_FROZEN_24H")
        if last24["candidate_mae_gbp_mwh"] > last24["reference_mae_gbp_mwh"]:
            alerts.append("V26_TRAILS_REFERENCE_24H")
        if abs(last24["candidate_signed_bias_gbp_mwh"]) > abs(last24["frozen_signed_bias_gbp_mwh"]):
            alerts.append("V26_BIAS_WORSE_THAN_FROZEN_24H")
        alert_status = "ALERTS_PRESENT" if alerts else "NO_DEGRADATION_ALERTS"

    summary = {
        "version": "0.26.0",
        "candidate_spec": candidate_spec(),
        "development_diagnostics": {
            "status": "PREVIOUSLY_OBSERVED_ROWS_NOT_NEW_EVIDENCE",
            "v25_forward_window_reused_for_v26_development": _metrics(development),
        },
        "forward_segment": _metrics(forward),
        "monitor": {
            "maturity_stage": _maturity(n),
            "rows_observed": n,
            "alert_min_rows": 48,
            "alert_status": alert_status,
            "alerts": alerts,
            "rolling": rolling,
        },
        "ledger_integrity": ledger_integrity,
        "promotion_readiness": {
            "minimum_forward_rows": 336,
            "rows_observed": n,
            "status": (
                "ELIGIBLE_FOR_HUMAN_REVIEW" if n >= 336 and not alerts else "NOT_ELIGIBLE"
            ),
            "automatic_promotion": False,
        },
        "claim_boundary": (
            "Rows before 2026-08-22T20:30:00Z are development diagnostics. Only later targets are v0.26 "
            "versioned forward evidence. No v0.25 row is relabelled as fresh v0.26 evidence."
        ),
    }

    (out / "v26_summary.json").write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    (out / "v26_candidate_spec.json").write_text(
        json.dumps(candidate_spec(), indent=2, default=str), encoding="utf-8"
    )
    (out / "v26_ledger_check.json").write_text(
        json.dumps(ledger_integrity, indent=2, default=str), encoding="utf-8"
    )
    print(json.dumps(summary, indent=2, default=str))


if __name__ == "__main__":
    main()
