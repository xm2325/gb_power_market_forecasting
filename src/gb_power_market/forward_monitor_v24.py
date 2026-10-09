from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from .price_forecasting import price_metrics
from .prospective_v21 import model_from_frozen_state

LOCKED_FINAL_START_UTC = pd.Timestamp("2026-07-12T12:00:00Z")
AUGUST_MONITOR_START_UTC = pd.Timestamp("2026-08-01T00:00:00Z")
POST_LOCK_START_UTC = pd.Timestamp("2026-08-15T07:30:00Z")


@dataclass(frozen=True)
class ForwardMonitorConfig:
    monitor_start_utc: pd.Timestamp = LOCKED_FINAL_START_UTC
    recent_regime_start_utc: pd.Timestamp = AUGUST_MONITOR_START_UTC
    post_lock_start_utc: pd.Timestamp = POST_LOCK_START_UTC
    minimum_coverage: float = 0.95
    rolling_windows: tuple[str, ...] = ("24h", "72h", "168h")


def _utc(value: str | pd.Timestamp) -> pd.Timestamp:
    out = pd.Timestamp(value)
    if out.tzinfo is None:
        raise ValueError("monitoring boundaries must be timezone-aware")
    return out.tz_convert("UTC")


def score_frozen_forward_rows(
    frame: pd.DataFrame,
    *,
    frozen_state: dict[str, Any],
    start_utc: str | pd.Timestamp,
    end_exclusive_utc: str | pd.Timestamp,
    target_col: str = "reference_market_price_gbp_mwh",
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Run one unchanged frozen model over an arbitrary later OOS/forward window.

    This is monitoring, not model selection: no family, alpha, coefficient,
    scaler or conformal quantile is fitted or changed here.
    """
    start = _utc(start_utc)
    end = _utc(end_exclusive_utc)
    if end <= start:
        raise ValueError("monitor end must be after start")

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
    df = frame.copy()
    df["target_start_utc"] = pd.to_datetime(df["target_start_utc"], utc=True, errors="raise")
    df["decision_time_utc"] = pd.to_datetime(df["decision_time_utc"], utc=True, errors="raise")
    df = df[(df["target_start_utc"] >= start) & (df["target_start_utc"] < end)].copy()
    complete = df.dropna(subset=list(dict.fromkeys(required))).sort_values("target_start_utc").copy()

    duplicate_rows = int(complete["target_start_utc"].duplicated(keep=False).sum())
    if duplicate_rows:
        raise ValueError(f"duplicate complete target timestamps in forward monitor: {duplicate_rows}")

    expected_grid = pd.date_range(start, end, freq="30min", inclusive="left")
    on_grid = complete["target_start_utc"].isin(expected_grid)
    off_grid_rows = int((~on_grid).sum())
    if off_grid_rows:
        raise ValueError(f"off-grid complete target timestamps in forward monitor: {off_grid_rows}")
    complete = complete.loc[on_grid].copy()
    missing_rows = int(len(expected_grid.difference(pd.DatetimeIndex(complete["target_start_utc"]))))
    coverage = float(len(complete) / len(expected_grid)) if len(expected_grid) else 0.0

    future_neso = 0
    if str(frozen_state["selected_family"]) == "PRICE_PLUS_NESO_LEVELS":
        if "neso_publish_time_utc" not in complete.columns:
            raise ValueError("NESO-level frozen model requires neso_publish_time_utc")
        pub = pd.to_datetime(complete["neso_publish_time_utc"], utc=True, errors="coerce")
        future_neso = int((pub.notna() & (pub > complete["decision_time_utc"])).sum())
        if future_neso:
            raise ValueError(f"future NESO publications entered forward monitor: {future_neso}")

    if complete.empty:
        raise ValueError("no complete rows in forward monitoring window")

    y = complete[target_col].to_numpy(float)
    pred = model.predict(complete[features].to_numpy(float))
    reference = complete["price_lag_1d_same_target"].to_numpy(float)
    last = complete["price_lag_last_completed"].to_numpy(float)
    q = float(frozen_state["conformal_absolute_residual_quantile_gbp_mwh"])

    rows = pd.DataFrame({
        "target_start_utc": complete["target_start_utc"].to_numpy(),
        "decision_time_utc": complete["decision_time_utc"].to_numpy(),
        "realised_price_gbp_mwh": y,
        "frozen_prediction_gbp_mwh": pred,
        "previous_settlement_day_reference_gbp_mwh": reference,
        "last_completed_price_gbp_mwh": last,
        "model_abs_error_gbp_mwh": np.abs(y - pred),
        "reference_abs_error_gbp_mwh": np.abs(y - reference),
        "model_minus_reference_abs_error_gbp_mwh": np.abs(y - pred) - np.abs(y - reference),
        "reference_minus_model_abs_error_gbp_mwh": np.abs(y - reference) - np.abs(y - pred),
        "interval_lower_gbp_mwh": pred - q,
        "interval_upper_gbp_mwh": pred + q,
    })
    rows["interval_covered"] = (
        (rows["realised_price_gbp_mwh"] >= rows["interval_lower_gbp_mwh"])
        & (rows["realised_price_gbp_mwh"] <= rows["interval_upper_gbp_mwh"])
    )
    rows["model_beats_reference"] = rows["model_abs_error_gbp_mwh"] < rows["reference_abs_error_gbp_mwh"]
    rows["evidence_segment"] = np.where(
        rows["target_start_utc"] < POST_LOCK_START_UTC,
        "LOCKED_HISTORICAL_OOS",
        "POST_LOCK_FORWARD_MONITORING",
    )

    n = np.arange(1, len(rows) + 1, dtype=float)
    rows["cumulative_model_mae_gbp_mwh"] = rows["model_abs_error_gbp_mwh"].cumsum() / n
    rows["cumulative_reference_mae_gbp_mwh"] = rows["reference_abs_error_gbp_mwh"].cumsum() / n
    rows["cumulative_error_advantage_gbp_mwh"] = rows["reference_minus_model_abs_error_gbp_mwh"].cumsum()
    denom = rows["cumulative_reference_mae_gbp_mwh"].replace(0.0, np.nan)
    rows["cumulative_improvement_pct"] = (
        100.0 * (rows["cumulative_reference_mae_gbp_mwh"] - rows["cumulative_model_mae_gbp_mwh"]) / denom
    )

    indexed = rows.set_index("target_start_utc")
    for window in ("24h", "72h", "168h"):
        label = {"24h": "24h", "72h": "3d", "168h": "7d"}[window]
        model_roll = indexed["model_abs_error_gbp_mwh"].rolling(window, min_periods=1).mean()
        ref_roll = indexed["reference_abs_error_gbp_mwh"].rolling(window, min_periods=1).mean()
        indexed[f"rolling_{label}_model_mae_gbp_mwh"] = model_roll
        indexed[f"rolling_{label}_reference_mae_gbp_mwh"] = ref_roll
        indexed[f"rolling_{label}_improvement_pct"] = 100.0 * (ref_roll - model_roll) / ref_roll.replace(0.0, np.nan)
    rows = indexed.reset_index()

    audit = {
        "start_utc": start.isoformat(),
        "end_exclusive_utc": end.isoformat(),
        "expected_rows": int(len(expected_grid)),
        "complete_rows": int(len(rows)),
        "coverage": coverage,
        "missing_expected_rows": missing_rows,
        "duplicate_complete_rows": duplicate_rows,
        "off_grid_complete_rows": off_grid_rows,
        "future_neso_publications": int(future_neso),
        "selected_family": str(frozen_state["selected_family"]),
        "horizon_minutes": int(frozen_state["horizon_minutes"]),
    }
    return rows, audit


def _metrics(rows: pd.DataFrame) -> dict[str, Any]:
    if rows.empty:
        return {"rows": 0, "status": "NO_ROWS"}
    y = rows["realised_price_gbp_mwh"].to_numpy(float)
    pred = rows["frozen_prediction_gbp_mwh"].to_numpy(float)
    reference = rows["previous_settlement_day_reference_gbp_mwh"].to_numpy(float)
    last = rows["last_completed_price_gbp_mwh"].to_numpy(float)
    model = price_metrics(y, pred, last)
    ref = price_metrics(y, reference, last)
    improvement = (
        100.0 * (ref["mae_gbp_mwh"] - model["mae_gbp_mwh"]) / ref["mae_gbp_mwh"]
        if ref["mae_gbp_mwh"]
        else None
    )
    return {
        "rows": int(len(rows)),
        "start_utc": pd.Timestamp(rows["target_start_utc"].min()).isoformat(),
        "end_exclusive_utc": (pd.Timestamp(rows["target_start_utc"].max()) + pd.Timedelta(minutes=30)).isoformat(),
        "frozen_model_mae_gbp_mwh": float(model["mae_gbp_mwh"]),
        "reference_mae_gbp_mwh": float(ref["mae_gbp_mwh"]),
        "improvement_pct": float(improvement) if improvement is not None else None,
        "frozen_model_p95_abs_error_gbp_mwh": float(model["p95_abs_error_gbp_mwh"]),
        "reference_p95_abs_error_gbp_mwh": float(ref["p95_abs_error_gbp_mwh"]),
        "direction_accuracy": float(model["direction_accuracy"]),
        "reference_direction_accuracy": float(ref["direction_accuracy"]),
        "interval_coverage": float(rows["interval_covered"].mean()),
        "model_win_rate": float(rows["model_beats_reference"].mean()),
        "cumulative_error_advantage_gbp_mwh": float(rows["reference_minus_model_abs_error_gbp_mwh"].sum()),
    }


def segment_metrics(
    rows: pd.DataFrame,
    *,
    monitor_end_exclusive_utc: str | pd.Timestamp,
    config: ForwardMonitorConfig = ForwardMonitorConfig(),
) -> dict[str, dict[str, Any]]:
    end = _utc(monitor_end_exclusive_utc)
    segments = {
        "locked_final_full": (config.monitor_start_utc, min(config.post_lock_start_utc, end), "LOCKED_HISTORICAL_OOS"),
        "august_1_to_latest": (config.recent_regime_start_utc, end, "MIXED_HISTORICAL_AND_FORWARD_MONITORING"),
        "post_lock_to_latest": (config.post_lock_start_utc, end, "POST_LOCK_FORWARD_MONITORING"),
        "latest_24h": (max(config.monitor_start_utc, end - pd.Timedelta(hours=24)), end, "ROLLING_MONITORING_ONLY"),
        "latest_3d": (max(config.monitor_start_utc, end - pd.Timedelta(days=3)), end, "ROLLING_MONITORING_ONLY"),
        "latest_7d": (max(config.monitor_start_utc, end - pd.Timedelta(days=7)), end, "ROLLING_MONITORING_ONLY"),
    }
    out: dict[str, dict[str, Any]] = {}
    t = pd.to_datetime(rows["target_start_utc"], utc=True)
    for name, (start, stop, role) in segments.items():
        block = rows[(t >= start) & (t < stop)].copy() if stop > start else rows.iloc[0:0].copy()
        metrics = _metrics(block)
        metrics["evidence_role"] = role
        metrics["requested_start_utc"] = start.isoformat()
        metrics["requested_end_exclusive_utc"] = stop.isoformat()
        out[name] = metrics
    return out


def daily_metrics(rows: pd.DataFrame) -> pd.DataFrame:
    x = rows.copy()
    x["utc_day"] = pd.to_datetime(x["target_start_utc"], utc=True).dt.strftime("%Y-%m-%d")
    records: list[dict[str, Any]] = []
    for day, block in x.groupby("utc_day", sort=True):
        m = _metrics(block)
        records.append({"utc_day": day, **m})
    return pd.DataFrame(records)
