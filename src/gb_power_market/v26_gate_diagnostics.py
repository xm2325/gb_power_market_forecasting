from __future__ import annotations

from collections import Counter

import numpy as np
import pandas as pd


APPLIED_REASON = "CONSENSUS_CLIPPED_CORRECTION"
REGIME_FALLBACK_REASON = "REGIME_DISAGREEMENT_FALLBACK_FROZEN"


def _streak_lengths(mask: np.ndarray) -> tuple[int, int]:
    longest = 0
    current = 0
    for value in mask:
        if bool(value):
            current += 1
            longest = max(longest, current)
        else:
            current = 0

    trailing = 0
    for value in mask[::-1]:
        if bool(value):
            trailing += 1
        else:
            break
    return longest, trailing


def summarise_v26_gate_diagnostics(rows: pd.DataFrame) -> dict:
    """Describe how the frozen v0.26 consensus gate behaved on observed rows.

    This function is monitoring-only. It does not select parameters, change the
    v0.26 prediction, or define a promotion rule. In particular, comparisons to
    v0.25 explain whether fallback avoided the already-observed failure mode;
    they are not a new model-selection objective.
    """
    required = {
        "realised_price_gbp_mwh",
        "frozen_prediction_gbp_mwh",
        "v25_prediction_gbp_mwh",
        "v26_prediction_gbp_mwh",
        "v26_correction_gbp_mwh",
        "v26_gate_reason",
    }
    missing = sorted(required - set(rows.columns))
    if missing:
        raise ValueError(f"v0.26 gate diagnostics missing columns: {missing}")

    if rows.empty:
        return {
            "rows": 0,
            "status": "NO_ROWS",
            "monitoring_only": True,
        }

    x = rows.reset_index(drop=True)
    y = x["realised_price_gbp_mwh"].to_numpy(float)
    frozen = x["frozen_prediction_gbp_mwh"].to_numpy(float)
    v25 = x["v25_prediction_gbp_mwh"].to_numpy(float)
    candidate = x["v26_prediction_gbp_mwh"].to_numpy(float)
    correction = x["v26_correction_gbp_mwh"].to_numpy(float)
    reasons = x["v26_gate_reason"].astype(str).to_numpy()

    reconstructed = frozen + correction
    reconstruction_error = np.abs(candidate - reconstructed)
    if float(reconstruction_error.max()) > 1e-9:
        raise ValueError("v0.26 prediction is not frozen prediction plus recorded correction")

    applied = reasons == APPLIED_REASON
    fallback = ~applied
    regime_fallback = reasons == REGIME_FALLBACK_REASON

    if fallback.any():
        fallback_prediction_diff = np.abs(candidate[fallback] - frozen[fallback])
        fallback_correction = np.abs(correction[fallback])
        if float(fallback_prediction_diff.max()) > 1e-9:
            raise ValueError("v0.26 fallback row does not reproduce frozen prediction")
        if float(fallback_correction.max()) > 1e-9:
            raise ValueError("v0.26 fallback row has a non-zero correction")

    candidate_abs = np.abs(y - candidate)
    frozen_abs = np.abs(y - frozen)
    v25_abs = np.abs(y - v25)

    longest_regime_streak, current_regime_streak = _streak_lengths(regime_fallback)
    reason_counts = Counter(str(reason) for reason in reasons)

    applied_better = int((candidate_abs[applied] < frozen_abs[applied]).sum())
    applied_worse = int((candidate_abs[applied] > frozen_abs[applied]).sum())
    applied_tied = int(applied.sum()) - applied_better - applied_worse

    if fallback.any():
        fallback_advantage = v25_abs[fallback] - frozen_abs[fallback]
        fallback_v25_worse = int((fallback_advantage > 0).sum())
        fallback_v25_better = int((fallback_advantage < 0).sum())
        fallback_v25_tied = int(fallback.sum()) - fallback_v25_worse - fallback_v25_better
        fallback_total_avoided = float(fallback_advantage.sum())
        fallback_mean_avoided = float(fallback_advantage.mean())
    else:
        fallback_v25_worse = 0
        fallback_v25_better = 0
        fallback_v25_tied = 0
        fallback_total_avoided = 0.0
        fallback_mean_avoided = 0.0

    return {
        "rows": int(len(x)),
        "status": "DESCRIPTIVE_FORWARD_GATE_DIAGNOSTIC",
        "monitoring_only": True,
        "correction_applied_rows": int(applied.sum()),
        "fallback_rows": int(fallback.sum()),
        "correction_applied_rate": float(applied.mean()),
        "fallback_rate": float(fallback.mean()),
        "gate_reason_counts": dict(sorted(reason_counts.items())),
        "longest_regime_disagreement_streak_rows": int(longest_regime_streak),
        "current_regime_disagreement_streak_rows": int(current_regime_streak),
        "mean_abs_correction_when_applied_gbp_mwh": (
            float(np.abs(correction[applied]).mean()) if applied.any() else 0.0
        ),
        "applied_rows_candidate_better_than_frozen": applied_better,
        "applied_rows_candidate_worse_than_frozen": applied_worse,
        "applied_rows_candidate_tied_with_frozen": applied_tied,
        "fallback_rows_v25_worse_than_frozen": fallback_v25_worse,
        "fallback_rows_v25_better_than_frozen": fallback_v25_better,
        "fallback_rows_v25_tied_with_frozen": fallback_v25_tied,
        "fallback_total_abs_error_avoided_vs_v25_gbp_mwh": fallback_total_avoided,
        "fallback_mean_abs_error_avoided_vs_v25_gbp_mwh": fallback_mean_avoided,
        "overall_total_abs_error_avoided_vs_v25_gbp_mwh": float((v25_abs - candidate_abs).sum()),
        "overall_mean_abs_error_avoided_vs_v25_gbp_mwh": float((v25_abs - candidate_abs).mean()),
        "prediction_reconstruction_max_abs_diff_gbp_mwh": float(reconstruction_error.max()),
        "interpretation_contract": (
            "These metrics describe the already-frozen gate on observed forward rows. They must not be used "
            "to retune v0.26 or relabel observed rows as fresh evidence for another candidate."
        ),
    }
