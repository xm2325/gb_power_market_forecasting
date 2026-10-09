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

    If the frozen replay contains conformal interval endpoints, v0.25 translates
    both endpoints by the same causal level correction. The conformal width and
    calibration quantile are unchanged; no future label is used to recalculate
    interval width.
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

    interval_present = {
        "interval_lower_gbp_mwh",
        "interval_upper_gbp_mwh",
    }.intersection(rows.columns)
    if interval_present and len(interval_present) != 2:
        raise ValueError("adaptive-bias input must contain both frozen interval endpoints or neither")

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
        eligible = (availability <= decision) & (
            target > decision - lookback - pd.Timedelta(minutes=rule.outcome_delay_minutes)
        )
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

    if interval_present:
        lower = x["interval_lower_gbp_mwh"].astype(float)
        upper = x["interval_upper_gbp_mwh"].astype(float)
        if (upper < lower).any():
            raise ValueError("frozen conformal interval has upper < lower")
        x["adaptive_interval_lower_gbp_mwh"] = lower + correction
        x["adaptive_interval_upper_gbp_mwh"] = upper + correction
        x["adaptive_interval_width_gbp_mwh"] = upper - lower
        y = x["realised_price_gbp_mwh"].astype(float)
        x["adaptive_interval_covered"] = (
            (y >= x["adaptive_interval_lower_gbp_mwh"])
            & (y <= x["adaptive_interval_upper_gbp_mwh"])
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
    result = {
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
    if "adaptive_interval_covered" in x.columns:
        result["adaptive_interval_coverage"] = float(x["adaptive_interval_covered"].astype(float).mean())
        result["adaptive_interval_mean_width_gbp_mwh"] = float(
            x["adaptive_interval_width_gbp_mwh"].astype(float).mean()
        )
    return result


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
        "uncertainty_contract": (
            "When frozen conformal bounds are present, both bounds are translated by the same causal bias "
            "correction as the point forecast. Interval width and the frozen calibration quantile remain unchanged; "
            "no v0.25 forward label is used to recalibrate uncertainty."
        ),
        "evidence_contract": (
            "Rows before the forward start are development diagnostics. Rows at or after the forward start form a "
            "new versioned monitoring segment and are not relabelled if the rule changes later."
        ),
    }
