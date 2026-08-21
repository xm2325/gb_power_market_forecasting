from __future__ import annotations

from dataclasses import dataclass, asdict

import numpy as np


@dataclass(frozen=True)
class TailGuardRule:
    large_move_quantile: float = 0.90
    minimum_large_move_rows: int = 20
    maximum_large_move_mae_degradation_pct: float = 5.0

    def __post_init__(self) -> None:
        if not 0.5 < self.large_move_quantile < 1.0:
            raise ValueError("large_move_quantile must be between 0.5 and 1")
        if self.minimum_large_move_rows < 1:
            raise ValueError("minimum_large_move_rows must be positive")
        if self.maximum_large_move_mae_degradation_pct < 0:
            raise ValueError("maximum degradation must be non-negative")


def fit_large_move_threshold(actual: np.ndarray, last_completed: np.ndarray, quantile: float) -> float:
    y = np.asarray(actual, dtype=float)
    lk = np.asarray(last_completed, dtype=float)
    if y.shape != lk.shape or y.ndim != 1 or len(y) == 0:
        raise ValueError("actual and last_completed must be equal non-empty vectors")
    if not np.isfinite(y).all() or not np.isfinite(lk).all():
        raise ValueError("threshold inputs must be finite")
    if not 0 < quantile < 1:
        raise ValueError("quantile must be between 0 and 1")
    return float(np.quantile(np.abs(y - lk), quantile))


def tail_metrics(
    actual: np.ndarray,
    prediction: np.ndarray,
    last_completed: np.ndarray,
    *,
    large_move_threshold_gbp_mwh: float,
) -> dict:
    y = np.asarray(actual, dtype=float)
    p = np.asarray(prediction, dtype=float)
    lk = np.asarray(last_completed, dtype=float)
    if not (y.shape == p.shape == lk.shape) or y.ndim != 1:
        raise ValueError("actual, prediction and last_completed must align")
    abs_err = np.abs(y - p)
    move = np.abs(y - lk)
    mask = move >= float(large_move_threshold_gbp_mwh)
    realised_direction = np.sign(y - lk)
    predicted_direction = np.sign(p - lk)
    direction_mask = mask & (realised_direction != 0)
    return {
        "large_move_threshold_gbp_mwh": float(large_move_threshold_gbp_mwh),
        "n_rows": int(len(y)),
        "n_large_move_rows": int(mask.sum()),
        "large_move_share": float(mask.mean()) if len(mask) else 0.0,
        "mae_gbp_mwh": float(abs_err.mean()),
        "p95_abs_error_gbp_mwh": float(np.quantile(abs_err, 0.95)),
        "large_move_mae_gbp_mwh": float(abs_err[mask].mean()) if mask.any() else None,
        "large_move_p95_abs_error_gbp_mwh": float(np.quantile(abs_err[mask], 0.95)) if mask.any() else None,
        "large_move_direction_accuracy": (
            float((predicted_direction[direction_mask] == realised_direction[direction_mask]).mean())
            if direction_mask.any() else None
        ),
    }


def evaluate_tail_guard(
    actual: np.ndarray,
    challenger: np.ndarray,
    baseline: np.ndarray,
    last_completed: np.ndarray,
    *,
    threshold_gbp_mwh: float,
    rule: TailGuardRule = TailGuardRule(),
) -> dict:
    base = tail_metrics(
        actual, baseline, last_completed,
        large_move_threshold_gbp_mwh=threshold_gbp_mwh,
    )
    cand = tail_metrics(
        actual, challenger, last_completed,
        large_move_threshold_gbp_mwh=threshold_gbp_mwh,
    )
    n_tail = cand["n_large_move_rows"]
    if n_tail < rule.minimum_large_move_rows:
        passed = False
        degradation = None
        reason = "too few validation large-move rows"
    else:
        base_tail = float(base["large_move_mae_gbp_mwh"])
        cand_tail = float(cand["large_move_mae_gbp_mwh"])
        degradation = 100.0 * (cand_tail - base_tail) / base_tail if base_tail else float("inf")
        passed = degradation <= rule.maximum_large_move_mae_degradation_pct
        reason = "PASS" if passed else "large-move MAE degradation exceeds guard"
    return {
        "status": "PASS" if passed else "BLOCKED",
        "reason": reason,
        "large_move_mae_degradation_pct": degradation,
        "baseline": base,
        "challenger": cand,
        "rule": asdict(rule),
    }
