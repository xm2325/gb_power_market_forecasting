from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


APPLIED_REASON = "CONSENSUS_CLIPPED_CORRECTION"


def _run_summary(x: pd.DataFrame, delta: pd.Series) -> dict[str, Any]:
    correction = x["v26_correction_gbp_mwh"].astype(float)
    return {
        "rows": int(len(x)),
        "start_utc": str(x.iloc[0]["target_start_utc"]),
        "end_utc": str(x.iloc[-1]["target_start_utc"]),
        "candidate_excess_abs_error_vs_frozen_gbp_mwh": float(delta.loc[x.index].sum()),
        "candidate_better_rows": int((delta.loc[x.index] < 0).sum()),
        "candidate_worse_rows": int((delta.loc[x.index] > 0).sum()),
        "candidate_tied_rows": int((delta.loc[x.index] == 0).sum()),
        "mean_abs_correction_gbp_mwh": float(correction.abs().mean()),
        "negative_correction_rows": int((correction < 0).sum()),
        "positive_correction_rows": int((correction > 0).sum()),
        "realised_start_gbp_mwh": float(x.iloc[0]["realised_price_gbp_mwh"]),
        "realised_end_gbp_mwh": float(x.iloc[-1]["realised_price_gbp_mwh"]),
        "frozen_start_gbp_mwh": float(x.iloc[0]["frozen_prediction_gbp_mwh"]),
        "frozen_end_gbp_mwh": float(x.iloc[-1]["frozen_prediction_gbp_mwh"]),
        "short_residual_mean_start_gbp_mwh": float(
            x.iloc[0]["v26_short_residual_mean_gbp_mwh"]
        ),
        "short_residual_mean_end_gbp_mwh": float(
            x.iloc[-1]["v26_short_residual_mean_gbp_mwh"]
        ),
        "long_residual_mean_start_gbp_mwh": float(
            x.iloc[0]["v26_long_residual_mean_gbp_mwh"]
        ),
        "long_residual_mean_end_gbp_mwh": float(
            x.iloc[-1]["v26_long_residual_mean_gbp_mwh"]
        ),
    }


def summarise_v26_alert_root_cause(ledger: pd.DataFrame) -> dict[str, Any]:
    required = {
        "target_start_utc",
        "realised_price_gbp_mwh",
        "frozen_prediction_gbp_mwh",
        "v26_short_residual_mean_gbp_mwh",
        "v26_long_residual_mean_gbp_mwh",
        "v26_gate_reason",
        "v26_correction_gbp_mwh",
        "v26_prediction_gbp_mwh",
    }
    missing = sorted(required - set(ledger.columns))
    if missing:
        raise ValueError(f"missing v0.26 alert-analysis columns: {missing}")
    if ledger.empty:
        return {
            "rows": 0,
            "status": "NO_ROWS",
            "monitoring_only": True,
        }

    x = ledger.copy().reset_index(drop=True)
    y = x["realised_price_gbp_mwh"].astype(float)
    frozen = x["frozen_prediction_gbp_mwh"].astype(float)
    candidate = x["v26_prediction_gbp_mwh"].astype(float)
    correction = x["v26_correction_gbp_mwh"].astype(float)

    reconstruction = (candidate - (frozen + correction)).abs()
    max_reconstruction_diff = float(reconstruction.max())
    if max_reconstruction_diff > 1e-9:
        raise ValueError("v0.26 prediction is not frozen prediction plus recorded correction")

    candidate_abs = (y - candidate).abs()
    frozen_abs = (y - frozen).abs()
    delta = candidate_abs - frozen_abs
    applied = x["v26_gate_reason"].eq(APPLIED_REASON)

    fallback_mismatch = (
        (~applied)
        & (
            (correction.abs() > 1e-9)
            | ((candidate - frozen).abs() > 1e-9)
        )
    )
    if fallback_mismatch.any():
        raise ValueError("v0.26 fallback row does not reproduce frozen prediction")

    applied_delta = delta[applied]
    harmful = applied_delta[applied_delta > 0]
    helpful = applied_delta[applied_delta < 0]

    runs: list[dict[str, Any]] = []
    run_ids = applied.ne(applied.shift(fill_value=bool(applied.iloc[0]))).cumsum()
    for _, group in x.groupby(run_ids, sort=False):
        if bool(applied.loc[group.index[0]]):
            runs.append(_run_summary(group, delta))

    longest_run = max(runs, key=lambda item: item["rows"]) if runs else None

    return {
        "rows": int(len(x)),
        "status": "DESCRIPTIVE_ALERT_ROOT_CAUSE",
        "monitoring_only": True,
        "correction_applied_rows": int(applied.sum()),
        "fallback_rows": int((~applied).sum()),
        "applied_rows_candidate_better_than_frozen": int((applied_delta < 0).sum()),
        "applied_rows_candidate_worse_than_frozen": int((applied_delta > 0).sum()),
        "applied_rows_candidate_tied_with_frozen": int((applied_delta == 0).sum()),
        "candidate_excess_abs_error_vs_frozen_gbp_mwh": float(delta.sum()),
        "harmful_applied_excess_abs_error_gbp_mwh": float(harmful.sum()),
        "helpful_applied_abs_error_saved_gbp_mwh": float(-helpful.sum()),
        "prediction_reconstruction_max_abs_diff_gbp_mwh": max_reconstruction_diff,
        "applied_runs": runs,
        "longest_applied_run": longest_run,
        "interpretation_contract": (
            "This analysis explains an already-observed frozen v0.26 alert. It is development/monitoring "
            "evidence only and must not be treated as fresh evidence for a later candidate."
        ),
    }
