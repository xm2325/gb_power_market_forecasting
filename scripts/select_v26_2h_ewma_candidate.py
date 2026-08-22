#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from gb_power_market.adaptive_ewma_v26 import (
    EWMACorrectionRule,
    V26_DEVELOPMENT_END_EXCLUSIVE_UTC,
    V26_DEVELOPMENT_START_UTC,
    apply_causal_ewma_correction,
    select_v26_candidate,
)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rows", required=True, help="Exact v0.25 artifact adaptive_rows_2h.csv")
    ap.add_argument("--out-dir", default="reports/v26_development")
    ap.add_argument("--source-run-id", required=True, type=int)
    ap.add_argument("--source-artifact-id", required=True, type=int)
    ap.add_argument("--source-artifact-sha256", required=True)
    args = ap.parse_args()

    rows = pd.read_csv(args.rows)
    rows["target_start_utc"] = pd.to_datetime(rows["target_start_utc"], utc=True, errors="raise")
    if rows.empty:
        raise SystemExit("v0.26 development input is empty")

    # The source artifact is already frozen at the v0.25 66-row boundary. Any
    # later target would indicate that the wrong artifact was supplied.
    later = rows[rows["target_start_utc"] >= V26_DEVELOPMENT_END_EXCLUSIVE_UTC]
    if not later.empty:
        raise SystemExit(
            "v0.26 development input contains targets at/after the locked 2026-08-22T20:30Z boundary"
        )

    decision = select_v26_candidate(rows)
    decision["source_artifact"] = {
        "run_id": int(args.source_run_id),
        "artifact_id": int(args.source_artifact_id),
        "artifact_sha256": str(args.source_artifact_sha256),
        "latest_input_target_start_utc": rows["target_start_utc"].max().isoformat(),
    }

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    decision_path = out / "v26_candidate_decision.json"
    decision_path.write_text(json.dumps(decision, indent=2, default=str) + "\n", encoding="utf-8")

    records: list[dict[str, object]] = []
    for candidate in decision["grid"]:
        records.append(
            {
                "candidate": candidate["candidate"],
                "half_life_hours": candidate["rule"]["half_life_hours"],
                "shrinkage": candidate["rule"]["shrinkage"],
                "selection_mae_gbp_mwh": candidate["selection"]["mae_gbp_mwh"],
                "selection_p95_gbp_mwh": candidate["selection"]["p95_abs_error_gbp_mwh"],
                "selection_signed_bias_gbp_mwh": candidate["selection"]["signed_bias_gbp_mwh"],
                "selection_eligible": candidate["selection_guards"]["eligible"],
                "validation_mae_gbp_mwh": candidate["validation_diagnostic"]["mae_gbp_mwh"],
                "validation_p95_gbp_mwh": candidate["validation_diagnostic"]["p95_abs_error_gbp_mwh"],
                "validation_signed_bias_gbp_mwh": candidate["validation_diagnostic"]["signed_bias_gbp_mwh"],
            }
        )
    pd.DataFrame(records).to_csv(out / "v26_candidate_grid.csv", index=False)

    selected = decision.get("selected")
    if selected is not None:
        rule = EWMACorrectionRule(**selected["rule"])
        scored = apply_causal_ewma_correction(rows, rule=rule)
        t = pd.to_datetime(scored["target_start_utc"], utc=True)
        development = scored[
            (t >= V26_DEVELOPMENT_START_UTC)
            & (t < V26_DEVELOPMENT_END_EXCLUSIVE_UTC)
        ].copy()
        keep = [
            "target_start_utc",
            "decision_time_utc",
            "realised_price_gbp_mwh",
            "frozen_prediction_gbp_mwh",
            "previous_settlement_day_reference_gbp_mwh",
            "ewma_correction_gbp_mwh",
            "ewma_prediction_gbp_mwh",
            "ewma_abs_error_gbp_mwh",
            "ewma_history_rows",
            "ewma_history_latest_target_utc",
        ]
        optional = [
            "ewma_interval_lower_gbp_mwh",
            "ewma_interval_upper_gbp_mwh",
            "ewma_interval_covered",
        ]
        development[[*keep, *[x for x in optional if x in development.columns]]].to_csv(
            out / "v26_selected_development_rows.csv", index=False
        )

    print(
        json.dumps(
            {
                "status": decision["status"],
                "selected": None if selected is None else selected["candidate"],
                "validation_guards": decision.get("validation_guards"),
                "forward_test_allowed": decision["forward_test_allowed"],
                "proposed_forward_start_utc": decision["proposed_forward_start_utc"],
                "source_artifact": decision["source_artifact"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
