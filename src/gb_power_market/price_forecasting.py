from __future__ import annotations

from dataclasses import dataclass
import math

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class PricePromotionRule:
    minimum_validation_improvement_pct: float = 5.0
    minimum_validation_rows: int = 100


class NumpyRidge:
    """Small deterministic ridge regressor with standardised predictors."""

    def __init__(self, alpha: float = 10.0):
        if alpha < 0:
            raise ValueError("alpha must be non-negative")
        self.alpha = float(alpha)
        self.mean_: np.ndarray | None = None
        self.scale_: np.ndarray | None = None
        self.coef_: np.ndarray | None = None

    def fit(self, x: np.ndarray, y: np.ndarray) -> "NumpyRidge":
        x = np.asarray(x, dtype=float)
        y = np.asarray(y, dtype=float)
        if x.ndim != 2 or y.ndim != 1 or len(x) != len(y):
            raise ValueError("invalid x/y shapes")
        if len(x) == 0 or not np.isfinite(x).all() or not np.isfinite(y).all():
            raise ValueError("training data must be finite and non-empty")
        self.mean_ = x.mean(axis=0)
        self.scale_ = x.std(axis=0)
        self.scale_[self.scale_ == 0] = 1.0
        xs = (x - self.mean_) / self.scale_
        design = np.column_stack([np.ones(len(xs)), xs])
        penalty = np.eye(design.shape[1]) * self.alpha
        penalty[0, 0] = 0.0
        system = design.T @ design + penalty
        rhs = design.T @ y
        try:
            self.coef_ = np.linalg.solve(system, rhs)
        except np.linalg.LinAlgError:
            # alpha=0 is a supported OLS candidate. Collinear/constant inputs
            # can make the normal equations singular, so use the minimum-norm
            # least-squares solution rather than failing the full experiment.
            if self.alpha != 0.0:
                raise
            self.coef_ = np.linalg.lstsq(design, y, rcond=None)[0]
        return self

    def predict(self, x: np.ndarray) -> np.ndarray:
        if self.mean_ is None or self.scale_ is None or self.coef_ is None:
            raise ValueError("model is not fitted")
        x = np.asarray(x, dtype=float)
        if not np.isfinite(x).all():
            raise ValueError("prediction data must be finite")
        xs = (x - self.mean_) / self.scale_
        return np.column_stack([np.ones(len(xs)), xs]) @ self.coef_


def build_information_safe_price_frame(
    market: pd.DataFrame,
    *,
    price_col: str = "reference_market_price_gbp_mwh",
    time_col: str = "target_start_utc",
    horizon_minutes: int = 30,
) -> pd.DataFrame:
    """Build safe lag/calendar features for a half-hourly GB price target.

    At decision time `target - horizon`, the current decision settlement period
    is not yet an observed outcome. The last completed price therefore starts at
    least one extra half-hour earlier, giving safe shift `horizon_periods + 1`.
    """
    if horizon_minutes <= 0 or horizon_minutes % 30:
        raise ValueError("horizon_minutes must be a positive multiple of 30")
    h = horizon_minutes // 30
    df = market[[time_col, price_col]].copy()
    df[time_col] = pd.to_datetime(df[time_col], utc=True, errors="raise")
    df = df.sort_values(time_col).drop_duplicates(time_col).reset_index(drop=True)
    if len(df) >= 2:
        gaps = df[time_col].diff().dropna()
        if not (gaps == pd.Timedelta(minutes=30)).all():
            raise ValueError("price series must be a complete 30-minute UTC grid")
    df[price_col] = pd.to_numeric(df[price_col], errors="raise").astype(float)
    safe_shift = h + 1
    df["decision_time_utc"] = df[time_col] - pd.to_timedelta(horizon_minutes, unit="m")
    df["price_lag_last_completed"] = df[price_col].shift(safe_shift)
    df["price_lag_2_completed"] = df[price_col].shift(safe_shift + 1)
    if 48 < safe_shift:
        raise ValueError("previous-day same-target price is not safe at this horizon")
    df["price_lag_1d_same_target"] = df[price_col].shift(48)
    df["price_lag_7d_same_target"] = df[price_col].shift(48 * 7)
    shifted = df[price_col].shift(safe_shift)
    df["price_roll_3h_mean"] = shifted.rolling(6, min_periods=6).mean()
    df["price_roll_24h_median"] = shifted.rolling(48, min_periods=48).median()
    hour = df[time_col].dt.hour + df[time_col].dt.minute / 60.0
    dow = df[time_col].dt.dayofweek.astype(float)
    df["hour_sin"] = np.sin(2 * np.pi * hour / 24.0)
    df["hour_cos"] = np.cos(2 * np.pi * hour / 24.0)
    df["dow_sin"] = np.sin(2 * np.pi * dow / 7.0)
    df["dow_cos"] = np.cos(2 * np.pi * dow / 7.0)
    df["horizon_minutes"] = int(horizon_minutes)
    df["safe_price_shift_periods"] = int(safe_shift)
    return df


def audit_asof_feature_publications(
    frame: pd.DataFrame,
    *,
    decision_col: str = "decision_time_utc",
    publish_cols: list[str],
) -> dict:
    df = frame.copy()
    decision = pd.to_datetime(df[decision_col], utc=True, errors="raise")
    future_by_col = {}
    missing_by_col = {}
    for col in publish_cols:
        pub = pd.to_datetime(df[col], utc=True, errors="coerce")
        future_by_col[col] = int((pub.notna() & (pub > decision)).sum())
        missing_by_col[col] = int(pub.isna().sum())
    n_future = int(sum(future_by_col.values()))
    return {
        "status": "PASS" if n_future == 0 else "BLOCKED",
        "n_rows": int(len(df)),
        "future_publications": n_future,
        "future_by_column": future_by_col,
        "missing_by_column": missing_by_col,
        "rule": "every exogenous forecast publication used as a feature must be <= decision_time_utc",
    }


def price_metrics(actual: np.ndarray, prediction: np.ndarray, last_known: np.ndarray | None = None) -> dict:
    y = np.asarray(actual, dtype=float)
    p = np.asarray(prediction, dtype=float)
    err = np.abs(y - p)
    out = {
        "mae_gbp_mwh": float(err.mean()),
        "rmse_gbp_mwh": float(np.sqrt(np.mean((y - p) ** 2))),
        "p95_abs_error_gbp_mwh": float(np.quantile(err, 0.95)),
        "n_rows": int(len(y)),
    }
    if last_known is not None:
        lk = np.asarray(last_known, dtype=float)
        realised_direction = np.sign(y - lk)
        predicted_direction = np.sign(p - lk)
        moving = realised_direction != 0
        out["direction_accuracy"] = float((predicted_direction[moving] == realised_direction[moving]).mean()) if moving.any() else None
    return out


def run_chronological_price_experiment(
    frame: pd.DataFrame,
    *,
    target_col: str = "reference_market_price_gbp_mwh",
    feature_cols: list[str] | None = None,
    train_fraction: float = 0.60,
    validation_fraction: float = 0.20,
    alpha_grid: tuple[float, ...] = (0.0, 1.0, 10.0, 100.0),
    promotion_rule: PricePromotionRule = PricePromotionRule(),
) -> dict:
    """Select ridge strength on validation, then evaluate final once.

    The domain baseline is previous-day same-target market price. Model family,
    alpha and promotion are fixed before the final split is scored.
    """
    if feature_cols is None:
        feature_cols = [
            "price_lag_last_completed", "price_lag_2_completed",
            "price_lag_1d_same_target", "price_lag_7d_same_target",
            "price_roll_3h_mean", "price_roll_24h_median",
            "hour_sin", "hour_cos", "dow_sin", "dow_cos",
        ]
    cols = [target_col, "price_lag_1d_same_target", "price_lag_last_completed"] + feature_cols
    df = frame.dropna(subset=list(dict.fromkeys(cols))).copy().reset_index(drop=True)
    n = len(df)
    if n < 30:
        raise ValueError("too few complete rows for chronological experiment")
    train_end = int(math.floor(n * train_fraction))
    val_end = int(math.floor(n * (train_fraction + validation_fraction)))
    if not (0 < train_end < val_end < n):
        raise ValueError("invalid split fractions")
    train = df.iloc[:train_end]
    val = df.iloc[train_end:val_end]
    final = df.iloc[val_end:]

    x_train = train[feature_cols].to_numpy(float)
    y_train = train[target_col].to_numpy(float)
    x_val = val[feature_cols].to_numpy(float)
    y_val = val[target_col].to_numpy(float)
    val_ref = val["price_lag_1d_same_target"].to_numpy(float)
    ref_val_mae = float(np.abs(y_val - val_ref).mean())

    candidates = []
    for alpha in alpha_grid:
        model = NumpyRidge(alpha).fit(x_train, y_train)
        pred = model.predict(x_val)
        mae = float(np.abs(y_val - pred).mean())
        candidates.append({"alpha": float(alpha), "validation_mae_gbp_mwh": mae})
    selected = min(candidates, key=lambda x: (x["validation_mae_gbp_mwh"], x["alpha"]))
    validation_improvement = 100.0 * (ref_val_mae - selected["validation_mae_gbp_mwh"]) / ref_val_mae if ref_val_mae else float("nan")
    promoted = (
        len(val) >= promotion_rule.minimum_validation_rows
        and validation_improvement >= promotion_rule.minimum_validation_improvement_pct
    )

    fit = pd.concat([train, val], ignore_index=True)
    final_model = NumpyRidge(selected["alpha"]).fit(
        fit[feature_cols].to_numpy(float), fit[target_col].to_numpy(float)
    )
    raw_model_pred = final_model.predict(final[feature_cols].to_numpy(float))
    baseline_pred = final["price_lag_1d_same_target"].to_numpy(float)
    deployed_pred = raw_model_pred if promoted else baseline_pred
    y_final = final[target_col].to_numpy(float)
    last_known = final["price_lag_last_completed"].to_numpy(float)

    return {
        "target": "volume-weighted short-term market reference price [GBP/MWh]",
        "split": {"train_rows": int(len(train)), "validation_rows": int(len(val)), "final_rows": int(len(final))},
        "feature_cols": feature_cols,
        "validation": {
            "reference_mae_gbp_mwh": ref_val_mae,
            "selected_alpha": selected["alpha"],
            "selected_model_mae_gbp_mwh": selected["validation_mae_gbp_mwh"],
            "model_improvement_pct": float(validation_improvement),
            "promoted": bool(promoted),
            "promotion_rule": {
                "minimum_validation_improvement_pct": promotion_rule.minimum_validation_improvement_pct,
                "minimum_validation_rows": promotion_rule.minimum_validation_rows,
            },
            "all_alpha_candidates": candidates,
        },
        "final_test": {
            "reference": price_metrics(y_final, baseline_pred, last_known),
            "raw_model": price_metrics(y_final, raw_model_pred, last_known),
            "deployed": price_metrics(y_final, deployed_pred, last_known),
            "deployed_source": "RIDGE_MODEL" if promoted else "PREVIOUS_DAY_FALLBACK",
        },
        "selection_boundary": "alpha and promotion fixed on validation; final test scored once",
    }
