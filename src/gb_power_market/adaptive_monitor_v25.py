from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class AdaptiveMonitoringPolicy:
    """Outcome-independent monitoring thresholds for the fixed v0.25 candidate."""

    alert_min_rows: int = 48
    rolling_rows_6h: int = 12
    rolling_rows_24h: int = 48
    rolling_rows_3d: int = 144
    rolling_rows_7d: int = 336


def maturity_stage(rows: int) -> str:
    if rows < 24:
        return "EARLY_ONLY"
    if rows < 96:
        return "INTRADAY_TO_2DAY_MONITORING"
    if rows < 336:
        return "MULTIDAY_MONITORING"
    return "ONE_WEEK_PLUS_FORWARD"


def _metrics(rows: pd.DataFrame) -> dict:
    if rows.empty:
        return {"rows": 0}

    y = rows["realised_price_gbp_mwh"].to_numpy(float)
    frozen = rows["frozen_prediction_gbp_mwh"].to_numpy(float)
    adaptive = rows["adaptive_prediction_gbp_mwh"].to_numpy(float)
    reference = rows["previous_settlement_day_reference_gbp_mwh"].to_numpy(float)
    correction = rows["bias_correction_gbp_mwh"].to_numpy(float)

    frozen_abs = np.abs(frozen - y)
    adaptive_abs = np.abs(adaptive - y)
    reference_abs = np.abs(reference - y)
    frozen_mae = float(frozen_abs.mean())
    adaptive_mae = float(adaptive_abs.mean())
    reference_mae = float(reference_abs.mean())

    def improvement(base: float, candidate: float) -> float | None:
        return 100.0 * (base - candidate) / base if base else None

    target = pd.to_datetime(rows["target_start_utc"], utc=True, errors="raise")
    return {
        "rows": int(len(rows)),
        "start_utc": target.min().isoformat(),
        "end_exclusive_utc": (target.max() + pd.Timedelta(minutes=30)).isoformat(),
        "adaptive_mae_gbp_mwh": adaptive_mae,
        "frozen_mae_gbp_mwh": frozen_mae,
        "reference_mae_gbp_mwh": reference_mae,
        "adaptive_improvement_vs_reference_pct": improvement(reference_mae, adaptive_mae),
        "adaptive_improvement_vs_frozen_pct": improvement(frozen_mae, adaptive_mae),
        "adaptive_win_rate_vs_reference": float((adaptive_abs < reference_abs).mean()),
        "adaptive_win_rate_vs_frozen": float((adaptive_abs < frozen_abs).mean()),
        "adaptive_signed_bias_gbp_mwh": float((adaptive - y).mean()),
        "frozen_signed_bias_gbp_mwh": float((frozen - y).mean()),
        "reference_signed_bias_gbp_mwh": float((reference - y).mean()),
        "adaptive_p95_abs_error_gbp_mwh": float(np.quantile(adaptive_abs, 0.95)),
        "frozen_p95_abs_error_gbp_mwh": float(np.quantile(frozen_abs, 0.95)),
        "reference_p95_abs_error_gbp_mwh": float(np.quantile(reference_abs, 0.95)),
        "correction_mean_gbp_mwh": float(correction.mean()),
        "correction_std_gbp_mwh": float(correction.std(ddof=0)),
        "correction_min_gbp_mwh": float(correction.min()),
        "correction_max_gbp_mwh": float(correction.max()),
    }


def build_adaptive_monitor_state(
    corrected_rows: pd.DataFrame,
    *,
    forward_start_utc: str | pd.Timestamp,
    candidate_id: str,
    model_version: str = "0.25.0",
    previous_snapshot_sha256: str | None = None,
    policy: AdaptiveMonitoringPolicy = AdaptiveMonitoringPolicy(),
) -> dict:
    """Build cumulative/rolling state without changing the adaptive forecast rule."""

    required = {
        "target_start_utc",
        "realised_price_gbp_mwh",
        "frozen_prediction_gbp_mwh",
        "adaptive_prediction_gbp_mwh",
        "previous_settlement_day_reference_gbp_mwh",
        "bias_correction_gbp_mwh",
    }
    missing = sorted(required - set(corrected_rows.columns))
    if missing:
        raise ValueError(f"adaptive-monitor input missing columns: {missing}")

    x = corrected_rows.copy()
    x["target_start_utc"] = pd.to_datetime(x["target_start_utc"], utc=True, errors="raise")
    if x["target_start_utc"].duplicated().any():
        raise ValueError("adaptive-monitor input contains duplicate targets")
    x = x.sort_values("target_start_utc").reset_index(drop=True)

    start = pd.Timestamp(forward_start_utc)
    if start.tzinfo is None:
        raise ValueError("forward_start_utc must be timezone-aware")
    forward = x[x["target_start_utc"] >= start].copy()
    n = int(len(forward))

    windows: dict[str, dict] = {}
    for name, width in (
        ("last_6h", policy.rolling_rows_6h),
        ("last_24h", policy.rolling_rows_24h),
        ("last_3d", policy.rolling_rows_3d),
        ("last_7d", policy.rolling_rows_7d),
    ):
        windows[name] = _metrics(forward.tail(width)) if n >= width else {
            "rows": n,
            "status": f"INSUFFICIENT_ROWS_NEED_{width}",
        }

    alerts: list[str] = []
    if n < policy.alert_min_rows:
        alert_status = "INSUFFICIENT_SAMPLE_FOR_ALERTS"
    else:
        last24 = windows["last_24h"]
        if last24["adaptive_mae_gbp_mwh"] > last24["reference_mae_gbp_mwh"]:
            alerts.append("ADAPTIVE_TRAILS_REFERENCE_24H")
        if last24["adaptive_mae_gbp_mwh"] > last24["frozen_mae_gbp_mwh"]:
            alerts.append("ADAPTIVE_TRAILS_FROZEN_24H")
        if abs(last24["adaptive_signed_bias_gbp_mwh"]) > abs(last24["frozen_signed_bias_gbp_mwh"]):
            alerts.append("BIAS_CORRECTION_WORSENED_24H")
        alert_status = "ALERTS_PRESENT" if alerts else "NO_DEGRADATION_ALERTS"

    return {
        "version": model_version,
        "candidate": candidate_id,
        "forward_start_utc": start.isoformat(),
        "maturity_stage": maturity_stage(n),
        "policy": asdict(policy),
        "cumulative": _metrics(forward),
        "rolling": windows,
        "alert_status": alert_status,
        "alerts": alerts,
        "lineage": {
            "previous_snapshot_sha256": previous_snapshot_sha256,
            "append_only_contract": (
                "A later snapshot may extend this same unchanged candidate with later targets. "
                "If the forecasting or correction rule changes, create a new version and forward start."
            ),
        },
    }
