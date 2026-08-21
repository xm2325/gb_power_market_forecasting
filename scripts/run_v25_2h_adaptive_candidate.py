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


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--v24-rows", default="reports/v24_forward/forward_rows_2h.csv")
    ap.add_argument("--out-dir", default="reports/v25_2h")
    args = ap.parse_args()

    rows = pd.read_csv(args.v24_rows)
    corrected = apply_causal_bias_correction(rows)
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)

    corrected.to_csv(out / "adaptive_rows_2h.csv", index=False)
    spec = candidate_spec()
    summary = {
        "version": "0.25.0",
        "status": "2H_ADAPTIVE_CANDIDATE_REPLAYED",
        "candidate_spec": spec,
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
    (out / "v25_2h_summary.json").write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    Path(out / "v25_2h_candidate_spec.json").write_text(json.dumps(spec, indent=2, default=str), encoding="utf-8")
    print(json.dumps(summary, indent=2, default=str))


if __name__ == "__main__":
    main()
