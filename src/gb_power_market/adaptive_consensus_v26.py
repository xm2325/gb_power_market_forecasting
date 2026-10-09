from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd


V26_FORWARD_START_UTC = pd.Timestamp("2026-08-22T20:30:00Z")
V26_CANDIDATE_ID = "2H_FROZEN_PLUS_CAUSAL_6H_48H_CONSENSUS_CLIPPED_RESIDUAL"


@dataclass(frozen=True)
class ConsensusCorrectionRule:
    horizon_minutes: int = 120
    outcome_delay_minutes: int = 30
    short_lookback_hours: int = 6
    long_lookback_hours: int = 48
    minimum_short_history_rows: int = 8
    minimum_long_history_rows: int = 24


def _history_indices(
    target: pd.Series,
    availability: pd.Series,
    *,
    decision: pd.Timestamp,
    lookback_hours: int,
    outcome_delay_minutes: int,
) -> np.ndarray:
    lower = decision - pd.Timedelta(hours=lookback_hours) - pd.Timedelta(
        minutes=outcome_delay_minutes
    )
    eligible = (availability <= decision) & (target > lower)
    return np.flatnonzero(eligible.to_numpy())


def apply_causal_consensus_correction(
    rows: pd.DataFrame,
    *,
    rule: ConsensusCorrectionRule = ConsensusCorrectionRule(),
) -> pd.DataFrame:
    """Apply a causal, regime-sensitive level correction to the frozen 2h model.

    The candidate keeps the v0.20 frozen point model unchanged. At each 2h
    decision time it estimates residual level over two already-observed windows:
    6h and 48h. A correction is applied only when the two residual means have the
    same non-zero sign. Its magnitude is clipped to the smaller absolute mean.

    This deliberately reacts conservatively to regime flips: if recent 6h bias
    disagrees with the slower 48h bias, the forecast falls back to the frozen
    model rather than carrying a stale level correction forward.
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
        raise ValueError(f"v0.26 input missing columns: {missing}")

    interval_present = {
        "interval_lower_gbp_mwh",
        "interval_upper_gbp_mwh",
    }.intersection(rows.columns)
    if interval_present and len(interval_present) != 2:
        raise ValueError("v0.26 input must contain both frozen interval endpoints or neither")

    x = rows.copy()
    x["target_start_utc"] = pd.to_datetime(x["target_start_utc"], utc=True, errors="raise")
    x["decision_time_utc"] = pd.to_datetime(x["decision_time_utc"], utc=True, errors="raise")
    x = x.sort_values("target_start_utc").reset_index(drop=True)
    if x["target_start_utc"].duplicated().any():
        raise ValueError("v0.26 input contains duplicate targets")

    expected_decision = x["target_start_utc"] - pd.Timedelta(minutes=rule.horizon_minutes)
    if not (x["decision_time_utc"] == expected_decision).all():
        raise ValueError("decision_time_utc does not match the frozen 2h horizon")

    residual = (
        x["realised_price_gbp_mwh"].astype(float)
        - x["frozen_prediction_gbp_mwh"].astype(float)
    ).to_numpy()
    target = x["target_start_utc"]
    availability = target + pd.Timedelta(minutes=rule.outcome_delay_minutes)

    correction = np.zeros(len(x), dtype=float)
    short_mean = np.full(len(x), np.nan, dtype=float)
    long_mean = np.full(len(x), np.nan, dtype=float)
    short_rows = np.zeros(len(x), dtype=int)
    long_rows = np.zeros(len(x), dtype=int)
    latest_history_target: list[str | None] = []
    gate_reason: list[str] = []

    for i, decision in enumerate(x["decision_time_utc"]):
        short_idx = _history_indices(
            target,
            availability,
            decision=decision,
            lookback_hours=rule.short_lookback_hours,
            outcome_delay_minutes=rule.outcome_delay_minutes,
        )
        long_idx = _history_indices(
            target,
            availability,
            decision=decision,
            lookback_hours=rule.long_lookback_hours,
            outcome_delay_minutes=rule.outcome_delay_minutes,
        )
        short_rows[i] = len(short_idx)
        long_rows[i] = len(long_idx)

        eligible_latest = long_idx[-1] if len(long_idx) else None
        latest_history_target.append(
            target.iloc[eligible_latest].isoformat() if eligible_latest is not None else None
        )

        if len(short_idx) < rule.minimum_short_history_rows:
            gate_reason.append("INSUFFICIENT_SHORT_HISTORY")
            continue
        if len(long_idx) < rule.minimum_long_history_rows:
            gate_reason.append("INSUFFICIENT_LONG_HISTORY")
            continue

        s_mean = float(residual[short_idx].mean())
        l_mean = float(residual[long_idx].mean())
        short_mean[i] = s_mean
        long_mean[i] = l_mean

        if s_mean == 0.0 or l_mean == 0.0 or np.sign(s_mean) != np.sign(l_mean):
            gate_reason.append("REGIME_DISAGREEMENT_FALLBACK_FROZEN")
            continue

        magnitude = min(abs(s_mean), abs(l_mean))
        correction[i] = float(np.sign(s_mean) * magnitude)
        gate_reason.append("CONSENSUS_CLIPPED_CORRECTION")

    x["v26_short_residual_mean_gbp_mwh"] = short_mean
    x["v26_long_residual_mean_gbp_mwh"] = long_mean
    x["v26_short_history_rows"] = short_rows
    x["v26_long_history_rows"] = long_rows
    x["v26_history_latest_target_utc"] = latest_history_target
    x["v26_gate_reason"] = gate_reason
    x["v26_correction_gbp_mwh"] = correction
    x["v26_prediction_gbp_mwh"] = x["frozen_prediction_gbp_mwh"].astype(float) + correction
    x["v26_abs_error_gbp_mwh"] = np.abs(
        x["realised_price_gbp_mwh"].astype(float) - x["v26_prediction_gbp_mwh"]
    )

    if interval_present:
        lower = x["interval_lower_gbp_mwh"].astype(float)
        upper = x["interval_upper_gbp_mwh"].astype(float)
        if (upper < lower).any():
            raise ValueError("frozen conformal interval has upper < lower")
        x["v26_interval_lower_gbp_mwh"] = lower + correction
        x["v26_interval_upper_gbp_mwh"] = upper + correction
        x["v26_interval_width_gbp_mwh"] = upper - lower
        y = x["realised_price_gbp_mwh"].astype(float)
        x["v26_interval_covered"] = (
            (y >= x["v26_interval_lower_gbp_mwh"])
            & (y <= x["v26_interval_upper_gbp_mwh"])
        )

    return x


def summarise_v26(rows: pd.DataFrame, *, start_utc: str | pd.Timestamp) -> dict:
    x = rows.copy()
    x["target_start_utc"] = pd.to_datetime(x["target_start_utc"], utc=True, errors="raise")
    start = pd.Timestamp(start_utc)
    if start.tzinfo is None:
        raise ValueError("v0.26 segment start must be timezone-aware")
    x = x[x["target_start_utc"] >= start].copy()
    if x.empty:
        return {"rows": 0, "status": "NO_FORWARD_ROWS"}

    y = x["realised_price_gbp_mwh"].to_numpy(float)
    frozen = x["frozen_prediction_gbp_mwh"].to_numpy(float)
    candidate = x["v26_prediction_gbp_mwh"].to_numpy(float)
    reference = x["previous_settlement_day_reference_gbp_mwh"].to_numpy(float)
    frozen_abs = np.abs(y - frozen)
    candidate_abs = np.abs(y - candidate)
    reference_abs = np.abs(y - reference)
    frozen_mae = float(frozen_abs.mean())
    candidate_mae = float(candidate_abs.mean())
    reference_mae = float(reference_abs.mean())

    result = {
        "status": "FORWARD_MONITORING",
        "rows": int(len(x)),
        "start_utc": start.isoformat(),
        "end_exclusive_utc": (x["target_start_utc"].max() + pd.Timedelta(minutes=30)).isoformat(),
        "candidate_mae_gbp_mwh": candidate_mae,
        "frozen_mae_gbp_mwh": frozen_mae,
        "reference_mae_gbp_mwh": reference_mae,
        "candidate_improvement_vs_frozen_pct": (
            100.0 * (frozen_mae - candidate_mae) / frozen_mae if frozen_mae else None
        ),
        "candidate_improvement_vs_reference_pct": (
            100.0 * (reference_mae - candidate_mae) / reference_mae if reference_mae else None
        ),
        "candidate_win_rate_vs_frozen": float((candidate_abs < frozen_abs).mean()),
        "candidate_win_rate_vs_reference": float((candidate_abs < reference_abs).mean()),
        "candidate_signed_bias_gbp_mwh": float((candidate - y).mean()),
        "frozen_signed_bias_gbp_mwh": float((frozen - y).mean()),
        "candidate_p95_abs_error_gbp_mwh": float(np.quantile(candidate_abs, 0.95)),
        "frozen_p95_abs_error_gbp_mwh": float(np.quantile(frozen_abs, 0.95)),
        "reference_p95_abs_error_gbp_mwh": float(np.quantile(reference_abs, 0.95)),
        "mean_correction_gbp_mwh": float(x["v26_correction_gbp_mwh"].mean()),
        "fallback_rate": float(
            (x["v26_gate_reason"] != "CONSENSUS_CLIPPED_CORRECTION").mean()
        ),
    }
    if "v26_interval_covered" in x.columns:
        result["candidate_interval_coverage"] = float(x["v26_interval_covered"].astype(float).mean())
        result["candidate_interval_mean_width_gbp_mwh"] = float(
            x["v26_interval_width_gbp_mwh"].astype(float).mean()
        )
    return result


def candidate_spec(rule: ConsensusCorrectionRule = ConsensusCorrectionRule()) -> dict:
    return {
        "version": "0.26.0",
        "candidate": V26_CANDIDATE_ID,
        "forward_start_utc": V26_FORWARD_START_UTC.isoformat(),
        "rule": asdict(rule),
        "selection_contract": (
            "No parameter search is performed. The 48h residual window is inherited from v0.25 and the 6h "
            "window is inherited from the pre-registered v0.25 monitoring policy."
        ),
        "information_contract": (
            "Both residual windows contain only outcomes available by the current 2h decision time. If recent "
            "and long-run residual means disagree in sign, the candidate falls back to the unchanged frozen model."
        ),
        "evidence_contract": (
            "All observations before 2026-08-22T20:30:00Z are development diagnostics. Only later targets form "
            "the versioned v0.26 forward segment."
        ),
    }
