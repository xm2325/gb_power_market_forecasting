from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

import numpy as np
import pandas as pd


V26_DEVELOPMENT_START_UTC = pd.Timestamp("2026-08-15T07:30:00Z")
V26_DEVELOPMENT_END_EXCLUSIVE_UTC = pd.Timestamp("2026-08-22T20:30:00Z")
V26_FORWARD_START_UTC = pd.Timestamp("2026-08-23T02:00:00Z")
V26_VALIDATION_ROWS = 96
V26_HALF_LIFE_HOURS = (3.0, 6.0, 12.0, 24.0)
V26_SHRINKAGES = (0.5, 1.0)
V26_MINIMUM_HISTORY_ROWS = 24
V26_CANDIDATE_FAMILY = "2H_FROZEN_PLUS_CAUSAL_EWMA_RESIDUAL"


@dataclass(frozen=True)
class EWMACorrectionRule:
    horizon_minutes: int = 120
    outcome_delay_minutes: int = 30
    half_life_hours: float = 6.0
    shrinkage: float = 1.0
    minimum_history_rows: int = V26_MINIMUM_HISTORY_ROWS


def _utc(value: str | pd.Timestamp) -> pd.Timestamp:
    out = pd.Timestamp(value)
    if out.tzinfo is None:
        raise ValueError("v0.26 time boundaries must be timezone-aware")
    return out.tz_convert("UTC")


def apply_causal_ewma_correction(
    rows: pd.DataFrame,
    *,
    rule: EWMACorrectionRule,
) -> pd.DataFrame:
    """Translate the unchanged frozen 2h forecast by a causal EWMA residual state.

    For target t the prediction decision is t-120m. A historical target s may
    contribute only after its outcome is available, conservatively s+30m. The
    correction is shrinkage * exponentially weighted mean(realised-frozen),
    with the half-life measured from outcome-availability time to the current
    decision time. No coefficient or NESO feature in the frozen model changes.
    """
    required = {
        "target_start_utc",
        "decision_time_utc",
        "realised_price_gbp_mwh",
        "frozen_prediction_gbp_mwh",
        "previous_settlement_day_reference_gbp_mwh",
    }
    missing = sorted(required.difference(rows.columns))
    if missing:
        raise ValueError(f"v0.26 EWMA input missing columns: {missing}")
    if rule.horizon_minutes != 120:
        raise ValueError("v0.26 EWMA family is frozen for the 2h horizon")
    if rule.half_life_hours <= 0:
        raise ValueError("EWMA half-life must be positive")
    if not (0.0 <= rule.shrinkage <= 1.0):
        raise ValueError("EWMA shrinkage must lie in [0, 1]")
    if rule.minimum_history_rows <= 0:
        raise ValueError("minimum history must be positive")

    x = rows.copy()
    x["target_start_utc"] = pd.to_datetime(x["target_start_utc"], utc=True, errors="raise")
    x["decision_time_utc"] = pd.to_datetime(x["decision_time_utc"], utc=True, errors="raise")
    x = x.sort_values("target_start_utc").reset_index(drop=True)
    if x["target_start_utc"].duplicated().any():
        raise ValueError("v0.26 EWMA input contains duplicate targets")

    expected_decision = x["target_start_utc"] - pd.Timedelta(minutes=rule.horizon_minutes)
    if not (x["decision_time_utc"] == expected_decision).all():
        raise ValueError("decision_time_utc does not match the frozen 2h horizon")

    target = x["target_start_utc"]
    availability = target + pd.Timedelta(minutes=rule.outcome_delay_minutes)
    residual = (
        x["realised_price_gbp_mwh"].astype(float)
        - x["frozen_prediction_gbp_mwh"].astype(float)
    ).to_numpy()

    correction = np.zeros(len(x), dtype=float)
    history_rows = np.zeros(len(x), dtype=int)
    latest_history_target: list[str | None] = []

    for i, decision in enumerate(x["decision_time_utc"]):
        eligible = availability <= decision
        idx = np.flatnonzero(eligible.to_numpy())
        history_rows[i] = len(idx)
        if len(idx) < rule.minimum_history_rows:
            correction[i] = 0.0
            latest_history_target.append(None)
            continue

        eligible_availability = availability.iloc[idx]
        age_hours = (
            (decision - eligible_availability).dt.total_seconds().to_numpy(float) / 3600.0
        )
        if np.any(age_hours < -1e-12):
            raise AssertionError("future outcome entered v0.26 EWMA state")
        weights = np.power(0.5, age_hours / rule.half_life_hours)
        if not np.isfinite(weights).all() or float(weights.sum()) <= 0.0:
            raise ValueError("invalid EWMA weights")
        correction[i] = rule.shrinkage * float(np.average(residual[idx], weights=weights))
        latest_history_target.append(target.iloc[int(idx[-1])].isoformat())

    x["ewma_half_life_hours"] = float(rule.half_life_hours)
    x["ewma_shrinkage"] = float(rule.shrinkage)
    x["ewma_history_rows"] = history_rows
    x["ewma_history_latest_target_utc"] = latest_history_target
    x["ewma_correction_gbp_mwh"] = correction
    x["ewma_prediction_gbp_mwh"] = x["frozen_prediction_gbp_mwh"].astype(float) + correction
    x["ewma_abs_error_gbp_mwh"] = np.abs(
        x["realised_price_gbp_mwh"].astype(float) - x["ewma_prediction_gbp_mwh"]
    )

    if {"interval_lower_gbp_mwh", "interval_upper_gbp_mwh"}.issubset(x.columns):
        lower = x["interval_lower_gbp_mwh"].astype(float)
        upper = x["interval_upper_gbp_mwh"].astype(float)
        if (upper < lower).any():
            raise ValueError("frozen conformal interval has upper < lower")
        x["ewma_interval_lower_gbp_mwh"] = lower + correction
        x["ewma_interval_upper_gbp_mwh"] = upper + correction
        x["ewma_interval_width_gbp_mwh"] = upper - lower
        y = x["realised_price_gbp_mwh"].astype(float)
        x["ewma_interval_covered"] = (
            (y >= x["ewma_interval_lower_gbp_mwh"])
            & (y <= x["ewma_interval_upper_gbp_mwh"])
        )
    return x


def _metrics(block: pd.DataFrame, prediction_col: str) -> dict[str, float | int]:
    if block.empty:
        raise ValueError("cannot score an empty v0.26 block")
    y = block["realised_price_gbp_mwh"].astype(float).to_numpy()
    pred = block[prediction_col].astype(float).to_numpy()
    err = y - pred
    abs_err = np.abs(err)
    return {
        "rows": int(len(block)),
        "mae_gbp_mwh": float(abs_err.mean()),
        "p95_abs_error_gbp_mwh": float(np.quantile(abs_err, 0.95)),
        "signed_bias_gbp_mwh": float(err.mean()),
    }


def _candidate_key(rule: EWMACorrectionRule) -> str:
    half = f"{rule.half_life_hours:g}h"
    shrink = f"{rule.shrinkage:g}"
    return f"EWMA_{half}_SHRINK_{shrink}"


def select_v26_candidate(
    rows: pd.DataFrame,
    *,
    development_start_utc: str | pd.Timestamp = V26_DEVELOPMENT_START_UTC,
    development_end_exclusive_utc: str | pd.Timestamp = V26_DEVELOPMENT_END_EXCLUSIVE_UTC,
    validation_rows: int = V26_VALIDATION_ROWS,
) -> dict[str, Any]:
    """Chronologically select and then validate one predeclared EWMA rule.

    The last `validation_rows` observations are never used to choose half-life
    or shrinkage. They only decide whether the selection winner is suitable for
    a new forward test. All rows here are already observed development data.
    """
    start = _utc(development_start_utc)
    end = _utc(development_end_exclusive_utc)
    if end > V26_DEVELOPMENT_END_EXCLUSIVE_UTC:
        raise ValueError("v0.26 development cannot extend beyond the locked 66-row artifact boundary")
    if V26_FORWARD_START_UTC <= end:
        raise ValueError("v0.26 forward start must be strictly after development end")
    if validation_rows <= 0:
        raise ValueError("validation_rows must be positive")

    base = rows.copy()
    base["target_start_utc"] = pd.to_datetime(base["target_start_utc"], utc=True, errors="raise")
    development = base[
        (base["target_start_utc"] >= start) & (base["target_start_utc"] < end)
    ].sort_values("target_start_utc")
    if len(development) <= 2 * validation_rows:
        raise ValueError("development window is too short for chronological selection and validation")

    validation = development.iloc[-validation_rows:].copy()
    selection = development.iloc[:-validation_rows].copy()
    validation_start = pd.Timestamp(validation["target_start_utc"].iloc[0])

    baseline_selection = {
        "frozen": _metrics(selection, "frozen_prediction_gbp_mwh"),
        "reference": _metrics(selection, "previous_settlement_day_reference_gbp_mwh"),
    }
    baseline_validation = {
        "frozen": _metrics(validation, "frozen_prediction_gbp_mwh"),
        "reference": _metrics(validation, "previous_settlement_day_reference_gbp_mwh"),
    }

    candidates: list[dict[str, Any]] = []
    scored_frames: dict[str, pd.DataFrame] = {}
    for half_life in V26_HALF_LIFE_HOURS:
        for shrinkage in V26_SHRINKAGES:
            rule = EWMACorrectionRule(half_life_hours=half_life, shrinkage=shrinkage)
            scored = apply_causal_ewma_correction(base, rule=rule)
            scored_frames[_candidate_key(rule)] = scored
            t = scored["target_start_utc"]
            sel = scored[(t >= start) & (t < validation_start)].copy()
            val = scored[(t >= validation_start) & (t < end)].copy()
            sel_metrics = _metrics(sel, "ewma_prediction_gbp_mwh")
            val_metrics = _metrics(val, "ewma_prediction_gbp_mwh")
            frozen_sel = baseline_selection["frozen"]
            selection_tail_guard = (
                sel_metrics["p95_abs_error_gbp_mwh"] <= frozen_sel["p95_abs_error_gbp_mwh"]
            )
            selection_bias_guard = (
                abs(sel_metrics["signed_bias_gbp_mwh"]) <= abs(frozen_sel["signed_bias_gbp_mwh"])
            )
            selection_mae_guard = sel_metrics["mae_gbp_mwh"] < frozen_sel["mae_gbp_mwh"]
            candidates.append(
                {
                    "candidate": _candidate_key(rule),
                    "rule": asdict(rule),
                    "selection": sel_metrics,
                    "validation_diagnostic": val_metrics,
                    "selection_guards": {
                        "mae_better_than_frozen": bool(selection_mae_guard),
                        "p95_non_worse_than_frozen": bool(selection_tail_guard),
                        "absolute_bias_non_worse_than_frozen": bool(selection_bias_guard),
                        "eligible": bool(selection_mae_guard and selection_tail_guard and selection_bias_guard),
                    },
                }
            )

    eligible = [c for c in candidates if c["selection_guards"]["eligible"]]
    if not eligible:
        return {
            "version": "0.26.0",
            "status": "NO_EWMA_CANDIDATE_PASSED_SELECTION_GUARDS",
            "candidate_family": V26_CANDIDATE_FAMILY,
            "development_start_utc": start.isoformat(),
            "development_end_exclusive_utc": end.isoformat(),
            "selection_end_exclusive_utc": validation_start.isoformat(),
            "validation_rows": int(validation_rows),
            "proposed_forward_start_utc": V26_FORWARD_START_UTC.isoformat(),
            "baseline_selection": baseline_selection,
            "baseline_validation": baseline_validation,
            "grid": candidates,
            "selected": None,
            "forward_test_allowed": False,
        }

    winner = min(
        eligible,
        key=lambda c: (
            c["selection"]["mae_gbp_mwh"],
            c["selection"]["p95_abs_error_gbp_mwh"],
            c["rule"]["half_life_hours"],
            c["rule"]["shrinkage"],
        ),
    )
    val = winner["validation_diagnostic"]
    frozen_val = baseline_validation["frozen"]
    reference_val = baseline_validation["reference"]
    validation_guards = {
        "mae_better_than_frozen": bool(val["mae_gbp_mwh"] < frozen_val["mae_gbp_mwh"]),
        "mae_better_than_reference": bool(val["mae_gbp_mwh"] < reference_val["mae_gbp_mwh"]),
        "p95_non_worse_than_frozen": bool(
            val["p95_abs_error_gbp_mwh"] <= frozen_val["p95_abs_error_gbp_mwh"]
        ),
        "absolute_bias_non_worse_than_frozen": bool(
            abs(val["signed_bias_gbp_mwh"]) <= abs(frozen_val["signed_bias_gbp_mwh"])
        ),
    }
    validation_guards["passed"] = bool(all(validation_guards.values()))

    return {
        "version": "0.26.0",
        "status": (
            "ELIGIBLE_FOR_NEW_FORWARD_TEST"
            if validation_guards["passed"]
            else "BLOCKED_BY_CHRONOLOGICAL_DEVELOPMENT_VALIDATION"
        ),
        "candidate_family": V26_CANDIDATE_FAMILY,
        "development_start_utc": start.isoformat(),
        "development_end_exclusive_utc": end.isoformat(),
        "selection_end_exclusive_utc": validation_start.isoformat(),
        "validation_rows": int(validation_rows),
        "proposed_forward_start_utc": V26_FORWARD_START_UTC.isoformat(),
        "grid_contract": {
            "half_life_hours": list(V26_HALF_LIFE_HOURS),
            "shrinkage": list(V26_SHRINKAGES),
            "minimum_history_rows": V26_MINIMUM_HISTORY_ROWS,
            "selection_objective": "lowest selection MAE among candidates with non-worse frozen P95 and absolute signed bias",
            "validation_gate": "selected rule must beat frozen and reference MAE and be non-worse than frozen P95 and absolute signed bias",
        },
        "baseline_selection": baseline_selection,
        "baseline_validation": baseline_validation,
        "grid": candidates,
        "selected": winner,
        "validation_guards": validation_guards,
        "forward_test_allowed": bool(validation_guards["passed"]),
        "evidence_contract": (
            "Every row through 2026-08-22T20:30Z is development evidence already observed before v0.26. "
            "No v0.26 accuracy claim may use these rows. A successful development gate only permits a new "
            "versioned forward test beginning no earlier than 2026-08-23T02:00Z."
        ),
    }
