from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

import numpy as np
import pandas as pd

from .fixed_market_experiment import FixedMarketWindows
from .price_feature_families import HISTORY_FEATURES, LEVEL_FEATURES, REVISION_FEATURES
from .price_forecasting import NumpyRidge, price_metrics
from .probabilistic_price import (
    abstention_metrics,
    finite_sample_conformal_quantile,
    interval_metrics,
)

LOCKED_EVIDENCE_ID = "7c5f78b98c8ed877ab4c5cefa8a40b3068abb74cb2062ecf677f319d74a14661"
PROSPECTIVE_START_UTC = pd.Timestamp("2026-08-15T07:30:00Z")

FAMILY_FEATURES = {
    "PRICE_HISTORY_ONLY": list(HISTORY_FEATURES),
    "PRICE_PLUS_NESO_LEVELS": list(HISTORY_FEATURES) + list(LEVEL_FEATURES),
}
ALL_V20_SELECTION_FEATURES = list(HISTORY_FEATURES) + list(LEVEL_FEATURES) + list(REVISION_FEATURES)


@dataclass(frozen=True)
class ProspectiveGate:
    minimum_rows: int = 672  # 14 complete UTC days of half-hour targets
    minimum_target_coverage: float = 0.95
    future_neso_publications_allowed: int = 0
    minimum_complete_utc_days_for_block_bootstrap: int = 7
    bootstrap_replicates: int = 2000
    bootstrap_seed: int = 20260821


def _purge_for_next(block: pd.DataFrame, next_block: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    if block.empty or next_block.empty:
        raise ValueError("frozen development block is empty")
    first_next_decision = pd.to_datetime(next_block["decision_time_utc"], utc=True).min()
    available = pd.to_datetime(block["target_start_utc"], utc=True) + pd.Timedelta(minutes=30)
    keep = available <= first_next_decision
    return block.loc[keep].copy(), {
        "raw_rows": int(len(block)),
        "kept_rows": int(keep.sum()),
        "purged_rows": int((~keep).sum()),
        "next_first_decision_time_utc": first_next_decision.isoformat(),
    }


def _feature_columns(selected_family: str) -> list[str]:
    try:
        return list(FAMILY_FEATURES[selected_family])
    except KeyError as exc:
        raise ValueError(f"unsupported frozen family: {selected_family}") from exc


def fit_frozen_replay_state(
    frame: pd.DataFrame,
    *,
    horizon_minutes: int,
    selected_family: str,
    alpha: float,
    locked_conformal_q_gbp_mwh: float,
    target_col: str = "reference_market_price_gbp_mwh",
    windows: FixedMarketWindows = FixedMarketWindows(),
    conformal_tolerance_gbp_mwh: float = 1e-8,
) -> dict[str, Any]:
    """Reconstruct the exact pre-final v0.20 ridge state.

    v0.20 selected all feature families on one common complete-row intersection.
    The replay export therefore preserves that same row population even when the
    winning family is price-history-only. Point coefficients are fitted only on
    the purged train + selection blocks. Calibration is used only to reproduce
    the locked conformal residual quantile. Locked-final labels are never fitted.
    """
    features = _feature_columns(selected_family)
    required = [
        "target_start_utc",
        "decision_time_utc",
        "neso_publish_time_utc",
        target_col,
        "price_lag_1d_same_target",
        "price_lag_last_completed",
        *ALL_V20_SELECTION_FEATURES,
    ]
    df = frame.dropna(subset=list(dict.fromkeys(required))).copy()
    df["target_start_utc"] = pd.to_datetime(df["target_start_utc"], utc=True, errors="raise")
    df["decision_time_utc"] = pd.to_datetime(df["decision_time_utc"], utc=True, errors="raise")
    df = df.sort_values("target_start_utc").reset_index(drop=True)

    w = windows.parsed()
    df = df[(df["target_start_utc"] >= w["train_start_utc"]) & (df["target_start_utc"] < w["final_end_exclusive_utc"])].copy()
    raw_train = df[(df["target_start_utc"] >= w["train_start_utc"]) & (df["target_start_utc"] < w["selection_start_utc"])].copy()
    raw_selection = df[(df["target_start_utc"] >= w["selection_start_utc"]) & (df["target_start_utc"] < w["calibration_start_utc"])].copy()
    raw_calibration = df[(df["target_start_utc"] >= w["calibration_start_utc"]) & (df["target_start_utc"] < w["final_start_utc"])].copy()
    raw_locked_final = df[(df["target_start_utc"] >= w["final_start_utc"]) & (df["target_start_utc"] < w["final_end_exclusive_utc"])].copy()

    train, purge_train = _purge_for_next(raw_train, raw_selection)
    selection, purge_selection = _purge_for_next(raw_selection, raw_calibration)
    calibration, purge_calibration = _purge_for_next(raw_calibration, raw_locked_final)

    point_fit = pd.concat([train, selection], ignore_index=True)
    model = NumpyRidge(alpha).fit(
        point_fit[features].to_numpy(float),
        point_fit[target_col].to_numpy(float),
    )
    cal_pred = model.predict(calibration[features].to_numpy(float))
    cal_scores = np.abs(calibration[target_col].to_numpy(float) - cal_pred)
    recomputed_q = finite_sample_conformal_quantile(cal_scores, 0.90)
    if abs(float(recomputed_q) - float(locked_conformal_q_gbp_mwh)) > conformal_tolerance_gbp_mwh:
        raise ValueError(
            "frozen conformal quantile does not reproduce locked evidence: "
            f"locked={locked_conformal_q_gbp_mwh:.12f}, recomputed={float(recomputed_q):.12f}"
        )

    if model.mean_ is None or model.scale_ is None or model.coef_ is None:
        raise AssertionError("frozen ridge fit produced incomplete state")

    return {
        "schema": "gb-power-market-frozen-ridge-v1",
        "source_evidence_id_sha256": LOCKED_EVIDENCE_ID,
        "horizon_minutes": int(horizon_minutes),
        "selected_family": selected_family,
        "features": features,
        "training_row_contract": "same all-family complete-row intersection used by v0.20 selection",
        "alpha": float(alpha),
        "mean": model.mean_.astype(float).tolist(),
        "scale": model.scale_.astype(float).tolist(),
        "coef": model.coef_.astype(float).tolist(),
        "conformal_absolute_residual_quantile_gbp_mwh": float(recomputed_q),
        "point_fit_rows": int(len(point_fit)),
        "calibration_rows": int(len(calibration)),
        "fit_boundary": "purged train + selection only; locked final labels excluded",
        "calibration_boundary": "purged calibration only; locked final labels excluded",
        "purge": {
            "train": purge_train,
            "selection": purge_selection,
            "calibration": purge_calibration,
        },
    }


def model_from_frozen_state(state: dict[str, Any]) -> NumpyRidge:
    if state.get("schema") != "gb-power-market-frozen-ridge-v1":
        raise ValueError("unsupported frozen model-state schema")
    if state.get("source_evidence_id_sha256") != LOCKED_EVIDENCE_ID:
        raise ValueError("frozen model state is not tied to the locked v0.20 evidence")
    features = list(state["features"])
    if features != _feature_columns(str(state["selected_family"])):
        raise ValueError("frozen feature order does not match family contract")
    mean = np.asarray(state["mean"], dtype=float)
    scale = np.asarray(state["scale"], dtype=float)
    coef = np.asarray(state["coef"], dtype=float)
    if len(mean) != len(features) or len(scale) != len(features) or len(coef) != len(features) + 1:
        raise ValueError("invalid frozen ridge state dimensions")
    if not np.isfinite(mean).all() or not np.isfinite(scale).all() or not np.isfinite(coef).all():
        raise ValueError("non-finite frozen ridge state")
    if (scale <= 0).any():
        raise ValueError("frozen ridge scale must be positive")
    model = NumpyRidge(float(state["alpha"]))
    model.mean_ = mean
    model.scale_ = scale
    model.coef_ = coef
    return model


def _complete_utc_days(frame: pd.DataFrame) -> list[str]:
    if frame.empty:
        return []
    t = pd.to_datetime(frame["target_start_utc"], utc=True)
    day = t.dt.strftime("%Y-%m-%d")
    counts = day.value_counts()
    return sorted(counts[counts == 48].index.astype(str).tolist())


def _daily_block_bootstrap(
    frame: pd.DataFrame,
    *,
    gate: ProspectiveGate,
) -> dict[str, Any]:
    complete_days = _complete_utc_days(frame)
    if len(complete_days) < gate.minimum_complete_utc_days_for_block_bootstrap:
        return {
            "status": "INSUFFICIENT_DAYS",
            "complete_utc_days": len(complete_days),
            "minimum_complete_utc_days": gate.minimum_complete_utc_days_for_block_bootstrap,
        }
    x = frame.copy()
    x["utc_day"] = pd.to_datetime(x["target_start_utc"], utc=True).dt.strftime("%Y-%m-%d")
    x = x[x["utc_day"].isin(complete_days)].copy()
    by_day = {
        d: float(g["model_minus_reference_abs_error_gbp_mwh"].mean())
        for d, g in x.groupby("utc_day", sort=True)
    }
    values = np.asarray([by_day[d] for d in complete_days], dtype=float)
    rng = np.random.default_rng(gate.bootstrap_seed)
    draws = rng.choice(values, size=(gate.bootstrap_replicates, len(values)), replace=True).mean(axis=1)
    lo, hi = np.quantile(draws, [0.025, 0.975])
    return {
        "status": "PASS",
        "complete_utc_days": int(len(values)),
        "replicates": int(gate.bootstrap_replicates),
        "seed": int(gate.bootstrap_seed),
        "mean_model_minus_reference_mae_gbp_mwh": float(values.mean()),
        "ci95_low_gbp_mwh": float(lo),
        "ci95_high_gbp_mwh": float(hi),
        "interpretation": "negative values favour the frozen model; days are the resampling blocks",
    }


def score_prospective_shadow(
    frame: pd.DataFrame,
    *,
    frozen_state: dict[str, Any],
    end_exclusive_utc: str | pd.Timestamp,
    target_col: str = "reference_market_price_gbp_mwh",
    start_utc: str | pd.Timestamp = PROSPECTIVE_START_UTC,
    gate: ProspectiveGate = ProspectiveGate(),
) -> dict[str, Any]:
    """Score an unchanged frozen v0.20 model on later labels.

    This function performs inference only. It does not refit coefficients,
    reselect a family/alpha, or recalibrate intervals on prospective outcomes.
    """
    model = model_from_frozen_state(frozen_state)
    features = list(frozen_state["features"])
    required = [
        "target_start_utc",
        "decision_time_utc",
        target_col,
        "price_lag_1d_same_target",
        "price_lag_last_completed",
        *features,
    ]
    df = frame.dropna(subset=list(dict.fromkeys(required))).copy()
    df["target_start_utc"] = pd.to_datetime(df["target_start_utc"], utc=True, errors="raise")
    df["decision_time_utc"] = pd.to_datetime(df["decision_time_utc"], utc=True, errors="raise")
    start = pd.Timestamp(start_utc)
    end = pd.Timestamp(end_exclusive_utc)
    if start.tzinfo is None or end.tzinfo is None:
        raise ValueError("prospective boundaries must be timezone-aware")
    if start < PROSPECTIVE_START_UTC:
        raise ValueError("prospective scoring cannot start inside the locked v0.20 final window")
    if end <= start:
        raise ValueError("prospective end must be after start")
    df = df[(df["target_start_utc"] >= start) & (df["target_start_utc"] < end)].sort_values("target_start_utc").copy()

    expected_rows = len(pd.date_range(start, end, freq="30min", inclusive="left"))
    coverage = float(len(df) / expected_rows) if expected_rows else 0.0
    future_neso = 0
    if str(frozen_state["selected_family"]) == "PRICE_PLUS_NESO_LEVELS":
        if "neso_publish_time_utc" not in df.columns:
            raise ValueError("NESO-level frozen model requires neso_publish_time_utc")
        pub = pd.to_datetime(df["neso_publish_time_utc"], utc=True, errors="coerce")
        future_neso = int((pub.notna() & (pub > df["decision_time_utc"])).sum())

    if df.empty:
        return {
            "status": "BLOCKED_EVIDENCE",
            "reason": "no complete prospective rows",
            "rows": 0,
            "expected_rows": int(expected_rows),
            "coverage": coverage,
        }

    y = df[target_col].to_numpy(float)
    pred = model.predict(df[features].to_numpy(float))
    baseline = df["price_lag_1d_same_target"].to_numpy(float)
    last = df["price_lag_last_completed"].to_numpy(float)
    q = float(frozen_state["conformal_absolute_residual_quantile_gbp_mwh"])
    lower = pred - q
    upper = pred + q
    model_metrics = price_metrics(y, pred, last)
    reference_metrics = price_metrics(y, baseline, last)
    improvement = (
        100.0 * (reference_metrics["mae_gbp_mwh"] - model_metrics["mae_gbp_mwh"]) / reference_metrics["mae_gbp_mwh"]
        if reference_metrics["mae_gbp_mwh"] else None
    )

    row = pd.DataFrame({
        "target_start_utc": df["target_start_utc"].astype(str),
        "model_minus_reference_abs_error_gbp_mwh": np.abs(y - pred) - np.abs(y - baseline),
    })
    bootstrap = _daily_block_bootstrap(row, gate=gate)

    if coverage < gate.minimum_target_coverage or future_neso > gate.future_neso_publications_allowed:
        status = "BLOCKED_EVIDENCE"
    elif len(df) < gate.minimum_rows:
        status = "SHADOW_ONLY"
    else:
        status = "PROSPECTIVE_EVIDENCE_READY"

    return {
        "version": "0.21.0",
        "status": status,
        "source_evidence_id_sha256": LOCKED_EVIDENCE_ID,
        "horizon_minutes": int(frozen_state["horizon_minutes"]),
        "selected_family": str(frozen_state["selected_family"]),
        "alpha": float(frozen_state["alpha"]),
        "model_state_schema": str(frozen_state["schema"]),
        "prospective_window": {
            "start_utc": start.isoformat(),
            "end_exclusive_utc": end.isoformat(),
            "rows": int(len(df)),
            "expected_rows": int(expected_rows),
            "coverage": coverage,
        },
        "information_audit": {
            "future_neso_publications": int(future_neso),
            "allowed": int(gate.future_neso_publications_allowed),
        },
        "reference": reference_metrics,
        "frozen_model": model_metrics,
        "improvement_vs_previous_settlement_day_pct": float(improvement) if improvement is not None else None,
        "interval": interval_metrics(y, lower, upper, 0.90),
        "abstention": abstention_metrics(y, pred, lower, upper, last),
        "daily_block_bootstrap": bootstrap,
        "gate": asdict(gate),
        "claim_boundary": (
            "SHADOW_ONLY is diagnostic and must not become a CV headline. "
            "PROSPECTIVE_EVIDENCE_READY means the predeclared sample/coverage gate has been met; "
            "a separate evidence lock is still required before any new public numerical claim."
        ),
    }
