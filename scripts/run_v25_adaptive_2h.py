#!/usr/bin/env python3
"""Apply the frozen v0.25 causal 2h trust gate to v0.24 row-level replay output."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from gb_power_market.adaptive_2h_v25 import (
    V25_FORWARD_START_UTC,
    apply_adaptive_2h_gate,
    build_v25_report,
)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rows", required=True, help="v0.24 forward_rows_2h.csv")
    ap.add_argument("--out-dir", default="reports/v25_adaptive_2h")
    args = ap.parse_args()

    rows = pd.read_csv(args.rows)
    gated = apply_adaptive_2h_gate(rows)
    report = build_v25_report(gated)

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    gated.to_csv(out / "adaptive_rows_2h.csv", index=False)

    daily = gated.copy()
    daily["utc_day"] = pd.to_datetime(daily["target_start_utc"], utc=True).dt.strftime("%Y-%m-%d")
    records = []
    for day, block in daily.groupby("utc_day", sort=True):
        ref = float(block["reference_abs_error_gbp_mwh"].mean())
        adaptive = float(block["adaptive_abs_error_gbp_mwh"].mean())
        frozen = float(block["model_abs_error_gbp_mwh"].mean())
        records.append(
            {
                "utc_day": day,
                "rows": int(len(block)),
                "adaptive_mae_gbp_mwh": adaptive,
                "frozen_model_mae_gbp_mwh": frozen,
                "reference_mae_gbp_mwh": ref,
                "adaptive_improvement_vs_reference_pct": (
                    100.0 * (ref - adaptive) / ref if ref else None
                ),
                "frozen_model_use_rate": float((block["adaptive_source"] == "FROZEN_MODEL").mean()),
                "forward_rows": int(
                    (pd.to_datetime(block["target_start_utc"], utc=True) >= V25_FORWARD_START_UTC).sum()
                ),
            }
        )
    pd.DataFrame(records).to_csv(out / "adaptive_daily_2h.csv", index=False)

    (out / "adaptive_2h_report.json").write_text(
        json.dumps(report, indent=2, default=str), encoding="utf-8"
    )

    fresh = report["segments"]["fresh_v025_forward"]
    dev = report["segments"]["development_to_freeze"]
    print(
        "development diagnostic:",
        {
            "rows": dev.get("rows"),
            "adaptive_mae": dev.get("adaptive_mae_gbp_mwh"),
            "reference_mae": dev.get("reference_mae_gbp_mwh"),
            "improvement_pct": dev.get("adaptive_improvement_vs_reference_pct"),
        },
        flush=True,
    )
    print(
        "fresh v0.25 forward:",
        {
            "rows": fresh.get("rows"),
            "adaptive_mae": fresh.get("adaptive_mae_gbp_mwh"),
            "frozen_model_mae": fresh.get("frozen_model_mae_gbp_mwh"),
            "reference_mae": fresh.get("reference_mae_gbp_mwh"),
            "improvement_pct": fresh.get("adaptive_improvement_vs_reference_pct"),
            "frozen_model_use_rate": fresh.get("frozen_model_use_rate"),
        },
        flush=True,
    )


if __name__ == "__main__":
    main()
