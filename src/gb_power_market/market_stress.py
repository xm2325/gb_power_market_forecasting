from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class StressGate:
    minimum_rows: int = 500
    minimum_stress_rows: int = 50
    minimum_price_coverage: float = 0.95


def fit_spread_regime_thresholds(
    calibration: pd.DataFrame,
    *,
    spread_col: str = "absolute_spread_gbp_mwh",
    high_quantile: float = 0.80,
    extreme_quantile: float = 0.95,
) -> dict:
    """Fit stress thresholds on a pre-final calibration population only.

    The function intentionally has no access to the final-test frame. Callers
    must materialise the calibration split explicitly before calling it.
    """
    if not 0 < high_quantile < extreme_quantile < 1:
        raise ValueError("expected 0 < high_quantile < extreme_quantile < 1")
    x = pd.to_numeric(calibration[spread_col], errors="coerce").dropna()
    if x.empty:
        raise ValueError("no finite calibration spread values")
    if (x < 0).any():
        raise ValueError("absolute spread cannot be negative")
    return {
        "spread_col": spread_col,
        "high_quantile": float(high_quantile),
        "extreme_quantile": float(extreme_quantile),
        "high_threshold_gbp_mwh": float(x.quantile(high_quantile)),
        "extreme_threshold_gbp_mwh": float(x.quantile(extreme_quantile)),
        "n_calibration_rows": int(len(x)),
        "fit_population": "pre-final calibration only",
    }


def apply_spread_regimes(
    frame: pd.DataFrame,
    thresholds: dict,
    *,
    out_col: str = "spread_regime",
) -> pd.DataFrame:
    df = frame.copy()
    spread_col = thresholds["spread_col"]
    x = pd.to_numeric(df[spread_col], errors="coerce")
    high = float(thresholds["high_threshold_gbp_mwh"])
    extreme = float(thresholds["extreme_threshold_gbp_mwh"])
    regime = np.select(
        [x >= extreme, x >= high, x.notna()],
        ["extreme", "high", "normal"],
        default="missing",
    )
    df[out_col] = pd.Categorical(
        regime,
        categories=["normal", "high", "extreme", "missing"],
        ordered=True,
    )
    return df


def conditioned_forecast_metrics(
    frame: pd.DataFrame,
    *,
    actual_col: str,
    reference_col: str,
    challenger_col: str,
    regime_col: str = "spread_regime",
    spread_col: str = "absolute_spread_gbp_mwh",
    interval_hours: float = 0.5,
) -> dict:
    """Compare forecast skill within pre-defined price-stress regimes.

    The exposure metric is descriptive and is not realised trading P&L.
    """
    cols = [actual_col, reference_col, challenger_col, regime_col, spread_col]
    df = frame[cols].dropna().copy()
    if df.empty:
        raise ValueError("no complete rows for conditioned metrics")

    df["reference_abs_error_mw"] = (df[actual_col] - df[reference_col]).abs()
    df["challenger_abs_error_mw"] = (df[actual_col] - df[challenger_col]).abs()
    df["reference_exposure_gbp"] = (
        df["reference_abs_error_mw"] * interval_hours * df[spread_col]
    )
    df["challenger_exposure_gbp"] = (
        df["challenger_abs_error_mw"] * interval_hours * df[spread_col]
    )

    def summarise(g: pd.DataFrame) -> dict:
        ref_mae = float(g["reference_abs_error_mw"].mean())
        chal_mae = float(g["challenger_abs_error_mw"].mean())
        ref_exp = float(g["reference_exposure_gbp"].sum())
        chal_exp = float(g["challenger_exposure_gbp"].sum())
        return {
            "n_rows": int(len(g)),
            "reference_mae_mw": ref_mae,
            "challenger_mae_mw": chal_mae,
            "mae_reduction_pct": float(100.0 * (ref_mae - chal_mae) / ref_mae) if ref_mae else None,
            "reference_spread_exposure_gbp": ref_exp,
            "challenger_spread_exposure_gbp": chal_exp,
            "spread_exposure_reduction_pct": float(100.0 * (ref_exp - chal_exp) / ref_exp) if ref_exp else None,
        }

    by_regime = {}
    for label in ["normal", "high", "extreme"]:
        g = df[df[regime_col].astype(str) == label]
        if not g.empty:
            by_regime[label] = summarise(g)

    return {
        "metric_semantics": (
            "Price-conditioned forecast diagnostics. Historical spread exposure is "
            "|forecast MW error| × settlement hours × |system price - market reference price|. "
            "It is not realised trading P&L."
        ),
        "overall": summarise(df),
        "by_regime": by_regime,
    }


def audit_stress_population(
    frame: pd.DataFrame,
    *,
    regime_col: str = "spread_regime",
    price_present_col: str | None = None,
    gate: StressGate = StressGate(),
) -> dict:
    n = int(len(frame))
    if price_present_col is None:
        price_ok = pd.Series(True, index=frame.index)
    else:
        price_ok = frame[price_present_col].notna()
    coverage = float(price_ok.mean()) if n else 0.0
    stress = frame[regime_col].astype(str).isin(["high", "extreme"]) & price_ok
    n_stress = int(stress.sum())
    status = (
        "PASS"
        if n >= gate.minimum_rows
        and coverage >= gate.minimum_price_coverage
        and n_stress >= gate.minimum_stress_rows
        else "BLOCKED"
    )
    return {
        "status": status,
        "n_rows": n,
        "price_coverage": coverage,
        "n_high_or_extreme_rows": n_stress,
        "minimum_rows": gate.minimum_rows,
        "minimum_price_coverage": gate.minimum_price_coverage,
        "minimum_stress_rows": gate.minimum_stress_rows,
        "claim": (
            "price-conditioned final-test metrics enabled"
            if status == "PASS"
            else "price-conditioned final-test claim blocked"
        ),
    }


def daily_block_bootstrap_exposure_delta(
    frame: pd.DataFrame,
    *,
    reference_exposure_col: str,
    challenger_exposure_col: str,
    time_col: str = "target_start_utc",
    n_boot: int = 2000,
    seed: int = 17,
) -> dict:
    """Paired UTC-day block bootstrap for total exposure difference.

    Negative challenger-minus-reference difference favours the challenger.
    """
    df = frame[[time_col, reference_exposure_col, challenger_exposure_col]].dropna().copy()
    if df.empty:
        raise ValueError("no paired exposure rows")
    df[time_col] = pd.to_datetime(df[time_col], utc=True, errors="raise")
    df["day"] = df[time_col].dt.floor("D")
    daily = df.groupby("day")[[reference_exposure_col, challenger_exposure_col]].sum()
    rng = np.random.default_rng(seed)
    idx = np.arange(len(daily))
    draws = np.empty(n_boot, dtype=float)
    for i in range(n_boot):
        pick = rng.choice(idx, size=len(idx), replace=True)
        s = daily.iloc[pick]
        draws[i] = float(s[challenger_exposure_col].sum() - s[reference_exposure_col].sum())
    point = float(df[challenger_exposure_col].sum() - df[reference_exposure_col].sum())
    lo, hi = np.quantile(draws, [0.025, 0.975])
    return {
        "total_exposure_delta_gbp": point,
        "ci95_low_gbp": float(lo),
        "ci95_high_gbp": float(hi),
        "prob_challenger_lower_exposure": float((draws < 0).mean()),
        "n_rows": int(len(df)),
        "n_days": int(len(daily)),
        "interpretation": "negative challenger-minus-reference exposure favours challenger",
    }
