from __future__ import annotations

from dataclasses import asdict, dataclass
import math

import numpy as np
import pandas as pd

from .price_feature_families import (
    FeatureFamilyRule,
    HISTORY_FEATURES,
    LEVEL_FEATURES,
    REVISION_FEATURES,
)
from .price_forecasting import NumpyRidge, price_metrics
from .price_tail import TailGuardRule, evaluate_tail_guard, fit_large_move_threshold


@dataclass(frozen=True)
class ProbabilisticRule:
    nominal_coverage: float = 0.90
    minimum_calibration_rows: int = 100
    local_scale_floor_gbp_mwh: float = 1.0
    scale_alpha: float = 10.0

    def __post_init__(self) -> None:
        if not 0.5 < self.nominal_coverage < 1.0:
            raise ValueError("nominal_coverage must be between 0.5 and 1")
        if self.minimum_calibration_rows < 20:
            raise ValueError("minimum_calibration_rows must be at least 20")
        if self.local_scale_floor_gbp_mwh <= 0:
            raise ValueError("local_scale_floor_gbp_mwh must be positive")
        if self.scale_alpha < 0:
            raise ValueError("scale_alpha must be non-negative")


FAMILIES = {
    "PRICE_HISTORY_ONLY": HISTORY_FEATURES,
    "PRICE_PLUS_NESO_LEVELS": HISTORY_FEATURES + LEVEL_FEATURES,
    "PRICE_PLUS_NESO_LEVELS_AND_REVISIONS": HISTORY_FEATURES + LEVEL_FEATURES + REVISION_FEATURES,
}


def finite_sample_conformal_quantile(scores: np.ndarray, coverage: float) -> float:
    """Finite-sample split-conformal quantile.

    Uses k = ceil((n + 1) * coverage), capped at n, and returns the k-th
    ordered nonconformity score. The calibration labels alone determine this
    correction; final-test labels are never read.
    """
    s = np.asarray(scores, dtype=float)
    if s.ndim != 1 or len(s) == 0 or not np.isfinite(s).all():
        raise ValueError("scores must be a non-empty finite vector")
    if not 0 < coverage < 1:
        raise ValueError("coverage must be between 0 and 1")
    ordered = np.sort(s)
    k = int(math.ceil((len(ordered) + 1) * coverage))
    k = min(max(k, 1), len(ordered))
    return float(ordered[k - 1])


def interval_metrics(actual: np.ndarray, lower: np.ndarray, upper: np.ndarray, coverage: float) -> dict:
    y = np.asarray(actual, dtype=float)
    lo = np.asarray(lower, dtype=float)
    hi = np.asarray(upper, dtype=float)
    if not (y.shape == lo.shape == hi.shape) or y.ndim != 1:
        raise ValueError("actual/lower/upper must be aligned vectors")
    if (lo > hi).any():
        raise ValueError("lower interval bound exceeds upper")
    alpha = 1.0 - float(coverage)
    width = hi - lo
    miss_low = y < lo
    miss_high = y > hi
    score = width.copy()
    score[miss_low] += (2.0 / alpha) * (lo[miss_low] - y[miss_low])
    score[miss_high] += (2.0 / alpha) * (y[miss_high] - hi[miss_high])
    covered = (y >= lo) & (y <= hi)
    return {
        "nominal_coverage": float(coverage),
        "empirical_coverage": float(covered.mean()),
        "mean_width_gbp_mwh": float(width.mean()),
        "median_width_gbp_mwh": float(np.median(width)),
        "p95_width_gbp_mwh": float(np.quantile(width, 0.95)),
        "mean_interval_score": float(score.mean()),
        "n_rows": int(len(y)),
    }


def abstention_metrics(
    actual: np.ndarray,
    point_prediction: np.ndarray,
    lower: np.ndarray,
    upper: np.ndarray,
    last_completed: np.ndarray,
) -> dict:
    """Evaluate interval-gated directional signals.

    UP is emitted only if the complete predictive interval is above the last
    completed market price; DOWN only if it is fully below. Otherwise the
    policy abstains. This is a forecast-confidence diagnostic, not a trading
    strategy and contains no position sizing or P&L claim.
    """
    y = np.asarray(actual, dtype=float)
    p = np.asarray(point_prediction, dtype=float)
    lo = np.asarray(lower, dtype=float)
    hi = np.asarray(upper, dtype=float)
    lk = np.asarray(last_completed, dtype=float)
    if not (y.shape == p.shape == lo.shape == hi.shape == lk.shape) or y.ndim != 1:
        raise ValueError("all inputs must be aligned vectors")
    signal = np.zeros(len(y), dtype=int)
    signal[lo > lk] = 1
    signal[hi < lk] = -1
    acted = signal != 0
    realised = np.sign(y - lk).astype(int)
    moving_acted = acted & (realised != 0)
    point_direction = np.sign(p - lk).astype(int)
    return {
        "rule": "UP iff lower_bound > last_completed; DOWN iff upper_bound < last_completed; otherwise ABSTAIN",
        "n_rows": int(len(y)),
        "n_actions": int(acted.sum()),
        "action_rate": float(acted.mean()),
        "abstention_rate": float((~acted).mean()),
        "direction_accuracy_on_actions": (
            float((signal[moving_acted] == realised[moving_acted]).mean()) if moving_acted.any() else None
        ),
        "ungated_point_direction_accuracy": (
            float((point_direction[realised != 0] == realised[realised != 0]).mean())
            if (realised != 0).any() else None
        ),
    }


def _four_way_split(
    frame: pd.DataFrame,
    required: list[str],
    train_fraction: float,
    selection_fraction: float,
    calibration_fraction: float,
):
    df = frame.dropna(subset=required).copy().sort_values("target_start_utc").reset_index(drop=True)
    n = len(df)
    if n < 80:
        raise ValueError("too few common complete rows")
    train_end = int(math.floor(n * train_fraction))
    selection_end = int(math.floor(n * (train_fraction + selection_fraction)))
    calibration_end = int(math.floor(n * (train_fraction + selection_fraction + calibration_fraction)))
    if not (0 < train_end < selection_end < calibration_end < n):
        raise ValueError("invalid four-way split fractions")
    return (
        df,
        df.iloc[:train_end],
        df.iloc[train_end:selection_end],
        df.iloc[selection_end:calibration_end],
        df.iloc[calibration_end:],
    )


def _best_ridge(train: pd.DataFrame, selection: pd.DataFrame, features: list[str], target_col: str, alpha_grid):
    rows = []
    y = selection[target_col].to_numpy(float)
    for alpha in alpha_grid:
        m = NumpyRidge(alpha).fit(train[features].to_numpy(float), train[target_col].to_numpy(float))
        pred = m.predict(selection[features].to_numpy(float))
        rows.append({
            "alpha": float(alpha),
            "selection_mae_gbp_mwh": float(np.abs(y - pred).mean()),
        })
    return min(rows, key=lambda r: (r["selection_mae_gbp_mwh"], r["alpha"])), rows


def _fit_local_scale_model(features: np.ndarray, abs_residual: np.ndarray, alpha: float) -> NumpyRidge:
    target = np.log1p(np.asarray(abs_residual, dtype=float))
    return NumpyRidge(alpha).fit(np.asarray(features, dtype=float), target)


def _predict_local_scale(model: NumpyRidge, features: np.ndarray, floor: float) -> np.ndarray:
    log_scale = model.predict(np.asarray(features, dtype=float))
    # Protect the uncertainty layer from numerical overflow on unusual feature
    # combinations while allowing the conformal correction to widen intervals.
    scale = np.expm1(np.clip(log_scale, np.log1p(floor), 20.0))
    return np.maximum(scale, float(floor))


def run_probabilistic_price_experiment(
    frame: pd.DataFrame,
    *,
    target_col: str = "reference_market_price_gbp_mwh",
    train_fraction: float = 0.50,
    selection_fraction: float = 0.20,
    calibration_fraction: float = 0.15,
    alpha_grid: tuple[float, ...] = (0.0, 1.0, 10.0, 100.0),
    family_rule: FeatureFamilyRule = FeatureFamilyRule(),
    tail_rule: TailGuardRule = TailGuardRule(),
    probabilistic_rule: ProbabilisticRule = ProbabilisticRule(),
) -> dict:
    """Leakage-safe point selection followed by locally scaled split conformal.

    Boundaries:
      train -> choose alpha/family on selection -> freeze deployed predictor
      -> calibrate interval correction on calibration -> final test once.

    Calibration labels cannot change the selected point family. Final labels
    cannot change the family, alpha, promotion decision, scale model or
    conformal quantile.
    """
    if train_fraction + selection_fraction + calibration_fraction >= 1.0:
        raise ValueError("four-way split must leave a non-empty final fraction")
    required = list(dict.fromkeys([
        target_col, "target_start_utc", "price_lag_1d_same_target", "price_lag_last_completed",
        *FAMILIES["PRICE_PLUS_NESO_LEVELS_AND_REVISIONS"],
    ]))
    common, train, selection, calibration, final = _four_way_split(
        frame, required, train_fraction, selection_fraction, calibration_fraction
    )
    if len(calibration) < probabilistic_rule.minimum_calibration_rows:
        raise ValueError("too few calibration rows for probabilistic layer")

    y_sel = selection[target_col].to_numpy(float)
    baseline_sel = selection["price_lag_1d_same_target"].to_numpy(float)
    last_sel = selection["price_lag_last_completed"].to_numpy(float)
    ref_sel_mae = float(np.abs(y_sel - baseline_sel).mean())
    selection_tail_threshold = fit_large_move_threshold(
        train[target_col].to_numpy(float),
        train["price_lag_last_completed"].to_numpy(float),
        tail_rule.large_move_quantile,
    )

    family_selection: dict[str, dict] = {}
    selection_predictions: dict[str, np.ndarray] = {}
    for name, features in FAMILIES.items():
        best, candidates = _best_ridge(train, selection, features, target_col, alpha_grid)
        model = NumpyRidge(best["alpha"]).fit(
            train[features].to_numpy(float), train[target_col].to_numpy(float)
        )
        pred = model.predict(selection[features].to_numpy(float))
        selection_predictions[name] = pred
        mae = best["selection_mae_gbp_mwh"]
        improvement = 100.0 * (ref_sel_mae - mae) / ref_sel_mae if ref_sel_mae else np.nan
        tail_guard = evaluate_tail_guard(
            y_sel, pred, baseline_sel, last_sel,
            threshold_gbp_mwh=selection_tail_threshold,
            rule=tail_rule,
        )
        family_selection[name] = {
            "features": features,
            "selected_alpha": best["alpha"],
            "selection_mae_gbp_mwh": mae,
            "improvement_vs_previous_day_pct": float(improvement),
            "tail_guard": tail_guard,
            "alpha_candidates": candidates,
        }

    simple_names = ["PRICE_HISTORY_ONLY", "PRICE_PLUS_NESO_LEVELS"]
    eligible_simple = [n for n in simple_names if family_selection[n]["tail_guard"]["status"] == "PASS"]
    best_simple = min(
        eligible_simple if eligible_simple else simple_names,
        key=lambda n: family_selection[n]["selection_mae_gbp_mwh"],
    )
    revision_name = "PRICE_PLUS_NESO_LEVELS_AND_REVISIONS"
    simple_mae = family_selection[best_simple]["selection_mae_gbp_mwh"]
    rev_mae = family_selection[revision_name]["selection_mae_gbp_mwh"]
    revision_margin = 100.0 * (simple_mae - rev_mae) / simple_mae if simple_mae else np.nan
    revision_eligible = (
        revision_margin >= family_rule.minimum_margin_to_add_revision_pct
        and family_selection[revision_name]["tail_guard"]["status"] == "PASS"
    )
    selected_family = revision_name if revision_eligible else best_simple
    selected = family_selection[selected_family]
    promoted = (
        len(selection) >= family_rule.minimum_validation_rows
        and selected["improvement_vs_previous_day_pct"] >= family_rule.minimum_improvement_vs_previous_day_pct
        and selected["tail_guard"]["status"] == "PASS"
    )
    deployed_source = selected_family if promoted else "PREVIOUS_DAY_FALLBACK"
    selected_features = FAMILIES[selected_family]

    # Point predictor is frozen before any calibration labels are consumed.
    point_fit = pd.concat([train, selection], ignore_index=True)
    if promoted:
        point_model = NumpyRidge(selected["selected_alpha"]).fit(
            point_fit[selected_features].to_numpy(float), point_fit[target_col].to_numpy(float)
        )
        cal_point = point_model.predict(calibration[selected_features].to_numpy(float))
        final_point = point_model.predict(final[selected_features].to_numpy(float))
        # Local scale learns from out-of-sample selection residuals produced by
        # the train-only selected model, never from calibration or final labels.
        scale_residual = np.abs(y_sel - selection_predictions[selected_family])
    else:
        point_model = None
        cal_point = calibration["price_lag_1d_same_target"].to_numpy(float)
        final_point = final["price_lag_1d_same_target"].to_numpy(float)
        scale_residual = np.abs(y_sel - baseline_sel)

    scale_model = _fit_local_scale_model(
        selection[selected_features].to_numpy(float),
        scale_residual,
        probabilistic_rule.scale_alpha,
    )
    cal_scale = _predict_local_scale(
        scale_model, calibration[selected_features].to_numpy(float), probabilistic_rule.local_scale_floor_gbp_mwh
    )
    y_cal = calibration[target_col].to_numpy(float)
    cal_scores = np.abs(y_cal - cal_point) / cal_scale
    conformal_q = finite_sample_conformal_quantile(cal_scores, probabilistic_rule.nominal_coverage)
    cal_lower = cal_point - conformal_q * cal_scale
    cal_upper = cal_point + conformal_q * cal_scale

    final_scale = _predict_local_scale(
        scale_model, final[selected_features].to_numpy(float), probabilistic_rule.local_scale_floor_gbp_mwh
    )
    final_lower = final_point - conformal_q * final_scale
    final_upper = final_point + conformal_q * final_scale
    y_final = final[target_col].to_numpy(float)
    last_final = final["price_lag_last_completed"].to_numpy(float)

    pre_final = pd.concat([train, selection, calibration], ignore_index=True)
    final_large_move_threshold = fit_large_move_threshold(
        pre_final[target_col].to_numpy(float),
        pre_final["price_lag_last_completed"].to_numpy(float),
        tail_rule.large_move_quantile,
    )
    large_move_mask = np.abs(y_final - last_final) >= final_large_move_threshold
    all_interval = interval_metrics(y_final, final_lower, final_upper, probabilistic_rule.nominal_coverage)
    large_interval = (
        interval_metrics(
            y_final[large_move_mask], final_lower[large_move_mask], final_upper[large_move_mask],
            probabilistic_rule.nominal_coverage,
        ) if large_move_mask.any() else None
    )

    return {
        "version": "0.14.0",
        "common_intersection": {
            "rows": int(len(common)),
            "train_rows": int(len(train)),
            "selection_rows": int(len(selection)),
            "calibration_rows": int(len(calibration)),
            "final_rows": int(len(final)),
            "rule": "all families and uncertainty diagnostics use the same complete target intersection",
        },
        "point_selection": {
            "reference_selection_mae_gbp_mwh": ref_sel_mae,
            "selection_tail_threshold_source": "train only",
            "selection_tail_threshold_gbp_mwh": float(selection_tail_threshold),
            "by_family": family_selection,
            "best_simple_family": best_simple,
            "revision_margin_vs_best_simple_pct": float(revision_margin),
            "selected_family": selected_family,
            "selected_alpha": float(selected["selected_alpha"]),
            "promoted": bool(promoted),
            "deployed_source": deployed_source,
            "family_rule": asdict(family_rule),
            "tail_rule": asdict(tail_rule),
            "boundary": "alpha, feature family, mean-error gate and tail guard are frozen before calibration and final labels",
        },
        "calibration": {
            "method": "locally scaled split conformal",
            "scale_training_source": "model-selection residuals from a train-only predictor",
            "conformal_score": "abs(y - point_prediction) / predicted_local_scale",
            "nominal_coverage": probabilistic_rule.nominal_coverage,
            "finite_sample_quantile": float(conformal_q),
            "interval_metrics": interval_metrics(y_cal, cal_lower, cal_upper, probabilistic_rule.nominal_coverage),
            "rule": asdict(probabilistic_rule),
            "boundary": "calibration labels set the conformal correction only; they cannot change point-family selection",
        },
        "final_test": {
            "point": price_metrics(y_final, final_point, last_final),
            "interval": all_interval,
            "large_move_interval": large_interval,
            "large_move_threshold_gbp_mwh": float(final_large_move_threshold),
            "n_large_move_rows": int(large_move_mask.sum()),
            "abstention": abstention_metrics(y_final, final_point, final_lower, final_upper, last_final),
            "deployed_source": deployed_source,
        },
        "claim_boundary": (
            "Prediction intervals quantify historical forecast uncertainty under the replay design; they are not guarantees. "
            "ABSTAIN is a confidence gate for directional forecast reporting, not a trading recommendation, position-sizing rule or P&L claim."
        ),
    }
