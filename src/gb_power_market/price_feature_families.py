from __future__ import annotations

from dataclasses import dataclass, asdict
import math

import numpy as np
import pandas as pd

from .price_forecasting import NumpyRidge, price_metrics
from .price_tail import TailGuardRule, evaluate_tail_guard, fit_large_move_threshold, tail_metrics


HISTORY_FEATURES = [
    "price_lag_last_completed", "price_lag_2_completed",
    "price_lag_1d_same_target", "price_lag_7d_same_target",
    "price_roll_3h_mean", "price_roll_24h_median",
    "hour_sin", "hour_cos", "dow_sin", "dow_cos",
]
LEVEL_FEATURES = [
    "neso_embedded_wind_forecast_mw", "neso_embedded_solar_forecast_mw",
    "neso_embedded_wind_capacity_mw", "neso_embedded_solar_capacity_mw",
    "neso_forecast_age_minutes",
]
REVISION_FEATURES = [
    "neso_embedded_wind_revision_delta_mw",
    "neso_embedded_wind_abs_revision_delta_mw",
    "neso_embedded_solar_revision_delta_mw",
    "neso_embedded_solar_abs_revision_delta_mw",
]


@dataclass(frozen=True)
class FeatureFamilyRule:
    minimum_validation_rows: int = 100
    minimum_improvement_vs_previous_day_pct: float = 5.0
    minimum_margin_to_add_revision_pct: float = 0.5


def merge_price_and_neso_features(price_frame: pd.DataFrame, selected_neso: pd.DataFrame) -> pd.DataFrame:
    feature_cols = [
        "target_start_utc", "neso_publish_time_utc", "neso_source_regime",
        "neso_forecast_age_minutes",
        *LEVEL_FEATURES[:4], *REVISION_FEATURES,
    ]
    missing = [c for c in feature_cols if c not in selected_neso.columns]
    if missing:
        raise ValueError(f"selected NESO frame missing columns: {missing}")
    out = price_frame.merge(selected_neso[feature_cols], on="target_start_utc", how="left")
    pub = pd.to_datetime(out["neso_publish_time_utc"], utc=True, errors="coerce")
    dec = pd.to_datetime(out["decision_time_utc"], utc=True, errors="raise")
    if (pub.notna() & (pub > dec)).any():
        raise ValueError("future NESO publication entered price feature frame")
    return out


def _split_common(frame: pd.DataFrame, required: list[str], train_fraction: float, validation_fraction: float):
    df = frame.dropna(subset=required).copy().sort_values("target_start_utc").reset_index(drop=True)
    n = len(df)
    if n < 30:
        raise ValueError("too few common complete rows")
    train_end = int(math.floor(n * train_fraction))
    val_end = int(math.floor(n * (train_fraction + validation_fraction)))
    if not (0 < train_end < val_end < n):
        raise ValueError("invalid split fractions")
    return df, df.iloc[:train_end], df.iloc[train_end:val_end], df.iloc[val_end:]


def _best_ridge(train: pd.DataFrame, val: pd.DataFrame, features: list[str], target_col: str, alpha_grid):
    candidates = []
    for alpha in alpha_grid:
        model = NumpyRidge(alpha).fit(train[features].to_numpy(float), train[target_col].to_numpy(float))
        pred = model.predict(val[features].to_numpy(float))
        mae = float(np.abs(val[target_col].to_numpy(float) - pred).mean())
        candidates.append({"alpha": float(alpha), "validation_mae_gbp_mwh": mae})
    return min(candidates, key=lambda x: (x["validation_mae_gbp_mwh"], x["alpha"])), candidates


def run_price_feature_family_experiment(
    frame: pd.DataFrame,
    *,
    target_col: str = "reference_market_price_gbp_mwh",
    train_fraction: float = 0.60,
    validation_fraction: float = 0.20,
    alpha_grid: tuple[float, ...] = (0.0, 1.0, 10.0, 100.0),
    rule: FeatureFamilyRule = FeatureFamilyRule(),
    tail_rule: TailGuardRule = TailGuardRule(),
) -> dict:
    """Compare price history, physical levels and revision feature families.

    All feature families use one common complete-row intersection. Alpha,
    family and promotion are selected before final scoring. v0.13 additionally
    requires the chosen family to pass a large-price-move validation guard.
    """
    families = {
        "PRICE_HISTORY_ONLY": HISTORY_FEATURES,
        "PRICE_PLUS_NESO_LEVELS": HISTORY_FEATURES + LEVEL_FEATURES,
        "PRICE_PLUS_NESO_LEVELS_AND_REVISIONS": HISTORY_FEATURES + LEVEL_FEATURES + REVISION_FEATURES,
    }
    required = list(dict.fromkeys([
        target_col, "target_start_utc", "price_lag_1d_same_target", "price_lag_last_completed",
        *families["PRICE_PLUS_NESO_LEVELS_AND_REVISIONS"],
    ]))
    common, train, val, final = _split_common(frame, required, train_fraction, validation_fraction)
    y_val = val[target_col].to_numpy(float)
    val_ref = val["price_lag_1d_same_target"].to_numpy(float)
    val_last = val["price_lag_last_completed"].to_numpy(float)
    ref_val_mae = float(np.abs(y_val - val_ref).mean())

    # The large-move definition used for model promotion is fitted from train
    # only. Final-test target values therefore cannot decide which periods count
    # as large moves during validation selection.
    selection_tail_threshold = fit_large_move_threshold(
        train[target_col].to_numpy(float),
        train["price_lag_last_completed"].to_numpy(float),
        tail_rule.large_move_quantile,
    )

    validation: dict[str, dict] = {}
    best_models: dict[str, dict] = {}
    validation_predictions: dict[str, np.ndarray] = {}
    for name, features in families.items():
        best, all_candidates = _best_ridge(train, val, features, target_col, alpha_grid)
        fitted = NumpyRidge(best["alpha"]).fit(
            train[features].to_numpy(float), train[target_col].to_numpy(float)
        )
        pred = fitted.predict(val[features].to_numpy(float))
        validation_predictions[name] = pred
        improvement = 100.0 * (ref_val_mae - best["validation_mae_gbp_mwh"]) / ref_val_mae if ref_val_mae else np.nan
        tail_guard = evaluate_tail_guard(
            y_val, pred, val_ref, val_last,
            threshold_gbp_mwh=selection_tail_threshold,
            rule=tail_rule,
        )
        validation[name] = {
            "features": features,
            "selected_alpha": best["alpha"],
            "mae_gbp_mwh": best["validation_mae_gbp_mwh"],
            "improvement_vs_previous_day_pct": float(improvement),
            "tail_guard": tail_guard,
            "alpha_candidates": all_candidates,
        }
        best_models[name] = best

    # A simple family that fails the tail guard is not eligible for promotion.
    simple_names = ["PRICE_HISTORY_ONLY", "PRICE_PLUS_NESO_LEVELS"]
    eligible_simple = [n for n in simple_names if validation[n]["tail_guard"]["status"] == "PASS"]
    best_simple = min(
        eligible_simple if eligible_simple else simple_names,
        key=lambda n: validation[n]["mae_gbp_mwh"],
    )
    revision_name = "PRICE_PLUS_NESO_LEVELS_AND_REVISIONS"
    simple_mae = validation[best_simple]["mae_gbp_mwh"]
    rev_mae = validation[revision_name]["mae_gbp_mwh"]
    revision_margin_pct = 100.0 * (simple_mae - rev_mae) / simple_mae if simple_mae else np.nan
    revision_eligible = (
        revision_margin_pct >= rule.minimum_margin_to_add_revision_pct
        and validation[revision_name]["tail_guard"]["status"] == "PASS"
    )
    selected_family = revision_name if revision_eligible else best_simple
    selected_improvement = validation[selected_family]["improvement_vs_previous_day_pct"]
    selected_tail_pass = validation[selected_family]["tail_guard"]["status"] == "PASS"
    promoted = (
        len(val) >= rule.minimum_validation_rows
        and selected_improvement >= rule.minimum_improvement_vs_previous_day_pct
        and selected_tail_pass
    )

    fit = pd.concat([train, val], ignore_index=True)
    y_final = final[target_col].to_numpy(float)
    baseline_pred = final["price_lag_1d_same_target"].to_numpy(float)
    last_known = final["price_lag_last_completed"].to_numpy(float)

    # A separate reporting threshold is refitted using all pre-final rows. This
    # affects only final diagnostics, never family selection or promotion.
    final_tail_threshold = fit_large_move_threshold(
        fit[target_col].to_numpy(float),
        fit["price_lag_last_completed"].to_numpy(float),
        tail_rule.large_move_quantile,
    )

    final_by_family = {}
    selected_pred = baseline_pred
    for name, features in families.items():
        alpha = best_models[name]["alpha"]
        model = NumpyRidge(alpha).fit(fit[features].to_numpy(float), fit[target_col].to_numpy(float))
        pred = model.predict(final[features].to_numpy(float))
        final_by_family[name] = {
            "standard": price_metrics(y_final, pred, last_known),
            "tail": tail_metrics(
                y_final, pred, last_known,
                large_move_threshold_gbp_mwh=final_tail_threshold,
            ),
        }
        if name == selected_family:
            selected_pred = pred

    deployed_pred = selected_pred if promoted else baseline_pred
    deployed_source = selected_family if promoted else "PREVIOUS_DAY_FALLBACK"
    return {
        "common_intersection": {
            "rows": int(len(common)),
            "train_rows": int(len(train)),
            "validation_rows": int(len(val)),
            "final_rows": int(len(final)),
            "rule": "all feature families use the same complete target rows",
        },
        "validation_reference_mae_gbp_mwh": ref_val_mae,
        "tail_definition": {
            "selection_threshold_source": "train only",
            "selection_large_move_threshold_gbp_mwh": float(selection_tail_threshold),
            "final_reporting_threshold_source": "train + validation only",
            "final_large_move_threshold_gbp_mwh": float(final_tail_threshold),
            "rule": asdict(tail_rule),
        },
        "validation_by_family": validation,
        "selection": {
            "best_simple_family": best_simple,
            "revision_margin_vs_best_simple_pct": float(revision_margin_pct),
            "revision_tail_guard_pass": validation[revision_name]["tail_guard"]["status"] == "PASS",
            "selected_family": selected_family,
            "selected_tail_guard_pass": selected_tail_pass,
            "promoted": bool(promoted),
            "deployed_source": deployed_source,
            "rule": asdict(rule),
            "boundary": "family, alpha, mean-error promotion and tail guard selected before final test",
        },
        "final_test": {
            "reference": {
                "standard": price_metrics(y_final, baseline_pred, last_known),
                "tail": tail_metrics(
                    y_final, baseline_pred, last_known,
                    large_move_threshold_gbp_mwh=final_tail_threshold,
                ),
            },
            "by_frozen_family": final_by_family,
            "deployed": {
                "standard": price_metrics(y_final, deployed_pred, last_known),
                "tail": tail_metrics(
                    y_final, deployed_pred, last_known,
                    large_move_threshold_gbp_mwh=final_tail_threshold,
                ),
            },
            "deployed_source": deployed_source,
        },
        "claim_boundary": (
            "A lower final error is a historical forecasting result, not realised trading P&L. "
            "Large-move diagnostics are outcome-conditioned error analysis. Revision features are predictive only."
        ),
    }
