from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd


V25_FORWARD_START_UTC = pd.Timestamp("2026-08-21T11:30:00Z")


@dataclass(frozen=True)
class BiasCorrectionRule:
    horizon_minutes: int = 120
    outcome_delay_minutes: int = 30
    lookback_hours: int = 48
    minimum_history_rows: int = 24


def apply_causal_bias_correction(
    rows: pd.DataFrame,
    *,
    rule: BiasCorrectionRule = BiasCorrectionRule(),
) -> pd.DataFrame:
    """Apply a rolling residual-level correction without using unavailable outcomes.

    For a target starting at t, the 2h frozen prediction is made at t-120m.
    A historical target s may contribute to the correction only if its realised
    outcome is available by that decision time, conservatively taken as s+30m.
    Therefore the current target and the most recent 150 minutes of target labels
    can never enter its own correction.
    """
    required = {
        "target_start_utc",
        "decision_time_utc",
        "realised_price_gbp_mwh",
        "frozen_prediction_gbp_mwh",
        "previous_settlement_day_reference_gbp_mwh",
    }
    missing = sorted(required - set(rows.columns))
    if missing:
        raise ValueError(f"adaptive-bias input missing columns: {missing}")

    x = rows.copy()
    x["target_start_utc"] = pd.to_datetime(x["target_start_utc"], utc=True, errors="raise")
    x["decision_time_utc"] = pd.to_datetime(x["decision_time_utc"], utc=True, errors="raise")
    x = x.sort_values("target_start_utc").reset_index(drop=True)
    if x["target_start_utc"].duplicated().any():
        raise ValueError("adaptive-bias input contains duplicate targets")

    expected_decision = x["target_start_utc"] - pd.Timedelta(minutes=rule.horizon_minutes)
    if not (x["decision_time_utc"] == expected_decision).all():
        raise ValueError("decision_time_utc does not match the frozen horizon")

    residual = (
        x["realised_price_gbp_mwh"].astype(float)
        - x["frozen_prediction_gbp_mwh"].astype(float)
    ).to_numpy()
    correction = np.zeros(len(x), dtype=float)
    history_rows = np.zeros(len(x), dtype=int)
    history_latest_target: list[str | None] = []

    target = x["target_start_utc"]
    availability = target + pd.Timedelta(minutes=rule.outcome_delay_minutes)
    lookback = pd.Timedelta(hours=rule.lookback_hours)

    for i, decision in enumerate(x["decision_time_utc"]):
        eligible = (availability <= decision) & (target > decision - lookback - pd.Timedelta(minutes=rule.outcome_delay_minutes))
        idx = np.flatnonzero(eligible.to_numpy())
        history_rows[i] = len(idx)
        if len(idx) >= rule.minimum_history_rows:
            correction[i] = float(residual[idx].mean())
            history_latest_target.append(target.iloc[idx[-1]].isoformat())
        else:
            correction[i] = 0.0
            history_latest_target.append(None)

    x["bias_correction_gbp_mwh"] = correction
    x["bias_history_rows"] = history_rows
    x["bias_history_latest_target_utc"] = history_latest_target
    x["adaptive_prediction_gbp_mwh"] = x["frozen_prediction_gbp_mwh"].astype(float) + correction
    x["adaptive_abs_error_gbp_mwh"] = np.abs(
        x["realised_price_gbp_mwh"].astype(float) - x["adaptive_prediction_gbp_mwh"]
    )
    x["adaptive_minus_reference_abs_error_gbp_mwh"] = (
        x["adaptive_abs_error_gbp_mwh"]
        - np.abs(
            x["realised_price_gbp_mwh"].astype(float)
            - x["previous_settlement_day_reference_gbp_mwh"].astype(float)
        )
    )
    return x


def summarise_candidate(rows: pd.DataFrame, *, start_utc: str | pd.Timestamp) -> dict:
    x = rows.copy()
    x["target_start_utc"] = pd.to_datetime(x["target_start_utc"], utc=True, errors="raise")
    start = pd.Timestamp(start_utc)
    if start.tzinfo is None:
        raise ValueError("candidate segment start must be timezone-aware")
    x = x[x["target_start_utc"] >= start].copy()
    if x.empty:
        return {"rows": 0, "status": "NO_FORWARD_ROWS"}

    y = x["realised_price_gbp_mwh"].to_numpy(float)
    frozen = x["frozen_prediction_gbp_mwh"].to_numpy(float)
    adaptive = x["adaptive_prediction_gbp_mwh"].to_numpy(float)
    reference = x["previous_settlement_day_reference_gbp_mwh"].to_numpy(float)
    mae_frozen = float(np.abs(y - frozen).mean())
    mae_adaptive = float(np.abs(y - adaptive).mean())
    mae_reference = float(np.abs(y - reference).mean())
    return {
        "status": "FORWARD_MONITORING",
        "rows": int(len(x)),
        "start_utc": start.isoformat(),
        "end_exclusive_utc": (x["target_start_utc"].max() + pd.Timedelta(minutes=30)).isoformat(),
        "frozen_model_mae_gbp_mwh": mae_frozen,
        "adaptive_candidate_mae_gbp_mwh": mae_adaptive,
        "reference_mae_gbp_mwh": mae_reference,
        "adaptive_improvement_vs_reference_pct": (
            100.0 * (mae_reference - mae_adaptive) / mae_reference if mae_reference else None
        ),
        "adaptive_improvement_vs_frozen_pct": (
            100.0 * (mae_frozen - mae_adaptive) / mae_frozen if mae_frozen else None
        ),
        "adaptive_win_rate_vs_reference": float((np.abs(y - adaptive) < np.abs(y - reference)).mean()),
        "mean_bias_correction_gbp_mwh": float(x["bias_correction_gbp_mwh"].mean()),
    }


def candidate_spec(rule: BiasCorrectionRule = BiasCorrectionRule()) -> dict:
    return {
        "version": "0.25.0",
        "candidate": "2H_FROZEN_PLUS_CAUSAL_48H_RESIDUAL_MEAN",
        "forward_start_utc": V25_FORWARD_START_UTC.isoformat(),
        "rule": asdict(rule),
        "information_contract": (
            "Each correction uses only residuals whose target outcome is available by the current decision time; "
            "the candidate does not refit the frozen v0.20 ridge coefficients or NESO feature family."
        ),
        "evidence_contract": (
            "Rows before the forward start are development diagnostics. Rows at or after the forward start form a "
            "new versioned monitoring segment and are not relabelled if the rule changes later."
        ),
    }
