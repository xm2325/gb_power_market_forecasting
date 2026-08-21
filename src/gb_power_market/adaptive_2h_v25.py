from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

import numpy as np
import pandas as pd


V25_FORWARD_START_UTC = pd.Timestamp("2026-08-21T11:30:00Z")
V24_SOURCE_ARTIFACT_SHA256 = "b79f86af22ea62a7c7e3fcccc3f0403353d0350f523ac432ed60d959e9abe6eb"
FROZEN_MODEL_STATE_SHA256 = "e9952aa88ca56b85f4d595bfe918cdc589ac0048d717d3fb3d9210361eb18918"


@dataclass(frozen=True)
class Adaptive2hGateConfig:
    """Causal trust gate for the unchanged v0.20 2h frozen model.

    The rule is deliberately simple: at each 2h decision time, look only at
    outcomes that have already completed. Use the frozen model when its mean
    absolute-error advantage over the previous-settlement-day reference across
    the latest 144 completed half-hours is positive; otherwise use the
    reference. No current/future target outcome is available to the gate.
    """

    horizon_minutes: int = 120
    lookback_completed_rows: int = 144
    minimum_history_rows: int = 48
    switch_threshold_model_minus_reference_gbp_mwh: float = 0.0
    insufficient_history_source: str = "FROZEN_MODEL"
    candidate_forward_start_utc: pd.Timestamp = V25_FORWARD_START_UTC


def _utc(value: str | pd.Timestamp) -> pd.Timestamp:
    out = pd.Timestamp(value)
    if out.tzinfo is None:
        raise ValueError("adaptive gate boundaries must be timezone-aware")
    return out.tz_convert("UTC")


def apply_adaptive_2h_gate(
    rows: pd.DataFrame,
    *,
    config: Adaptive2hGateConfig = Adaptive2hGateConfig(),
) -> pd.DataFrame:
    """Apply a strictly causal recent-performance gate to v0.24 row outputs."""

    required = {
        "target_start_utc",
        "decision_time_utc",
        "realised_price_gbp_mwh",
        "frozen_prediction_gbp_mwh",
        "previous_settlement_day_reference_gbp_mwh",
        "model_abs_error_gbp_mwh",
        "reference_abs_error_gbp_mwh",
    }
    missing = sorted(required.difference(rows.columns))
    if missing:
        raise ValueError(f"adaptive gate input missing columns: {missing}")
    if config.horizon_minutes != 120:
        raise ValueError("v0.25 adaptive gate is frozen for the 2h horizon only")
    if config.lookback_completed_rows <= 0 or config.minimum_history_rows <= 0:
        raise ValueError("adaptive gate history lengths must be positive")
    if config.minimum_history_rows > config.lookback_completed_rows:
        raise ValueError("minimum history cannot exceed lookback")
    if config.insufficient_history_source not in {"FROZEN_MODEL", "REFERENCE"}:
        raise ValueError("unsupported insufficient-history source")

    x = rows.copy()
    x["target_start_utc"] = pd.to_datetime(x["target_start_utc"], utc=True, errors="raise")
    x["decision_time_utc"] = pd.to_datetime(x["decision_time_utc"], utc=True, errors="raise")
    x = x.sort_values("target_start_utc").reset_index(drop=True)
    if x["target_start_utc"].duplicated().any():
        raise ValueError("duplicate target timestamps in adaptive gate input")

    outcome_available = x["target_start_utc"] + pd.Timedelta(minutes=30)
    historical_delta = (
        x["model_abs_error_gbp_mwh"].astype(float)
        - x["reference_abs_error_gbp_mwh"].astype(float)
    ).to_numpy()

    gate_score: list[float] = []
    history_rows: list[int] = []
    history_latest_available: list[pd.Timestamp | pd.NaT] = []
    selected_source: list[str] = []
    selected_prediction: list[float] = []

    for _, row in x.iterrows():
        decision = row["decision_time_utc"]
        eligible_idx = np.flatnonzero((outcome_available <= decision).to_numpy())
        if len(eligible_idx) > config.lookback_completed_rows:
            eligible_idx = eligible_idx[-config.lookback_completed_rows :]

        n_history = int(len(eligible_idx))
        history_rows.append(n_history)
        if n_history:
            latest = outcome_available.iloc[int(eligible_idx[-1])]
            if latest > decision:
                raise AssertionError("future outcome entered adaptive gate history")
            history_latest_available.append(latest)
            score = float(np.mean(historical_delta[eligible_idx]))
        else:
            history_latest_available.append(pd.NaT)
            score = float("nan")
        gate_score.append(score)

        if n_history < config.minimum_history_rows:
            source = config.insufficient_history_source
        else:
            source = (
                "FROZEN_MODEL"
                if score < config.switch_threshold_model_minus_reference_gbp_mwh
                else "REFERENCE"
            )
        selected_source.append(source)
        selected_prediction.append(
            float(row["frozen_prediction_gbp_mwh"])
            if source == "FROZEN_MODEL"
            else float(row["previous_settlement_day_reference_gbp_mwh"])
        )

    x["gate_history_rows"] = history_rows
    x["gate_latest_outcome_available_utc"] = history_latest_available
    x["gate_model_minus_reference_mae_gbp_mwh"] = gate_score
    x["adaptive_source"] = selected_source
    x["adaptive_prediction_gbp_mwh"] = selected_prediction
    x["adaptive_abs_error_gbp_mwh"] = np.abs(
        x["realised_price_gbp_mwh"].astype(float) - x["adaptive_prediction_gbp_mwh"]
    )
    x["adaptive_beats_reference"] = (
        x["adaptive_abs_error_gbp_mwh"] < x["reference_abs_error_gbp_mwh"].astype(float)
    )
    x["candidate_evidence_segment"] = np.where(
        x["target_start_utc"] < _utc(config.candidate_forward_start_utc),
        "RETROSPECTIVE_DEVELOPMENT_DIAGNOSTIC",
        "V0_25_FORWARD_SEGMENT",
    )
    return x


def adaptive_metrics(rows: pd.DataFrame) -> dict[str, Any]:
    if rows.empty:
        return {"rows": 0, "status": "NO_ROWS"}
    adaptive_mae = float(rows["adaptive_abs_error_gbp_mwh"].mean())
    frozen_mae = float(rows["model_abs_error_gbp_mwh"].mean())
    reference_mae = float(rows["reference_abs_error_gbp_mwh"].mean())
    improvement = (
        100.0 * (reference_mae - adaptive_mae) / reference_mae if reference_mae else None
    )
    return {
        "rows": int(len(rows)),
        "start_utc": pd.Timestamp(rows["target_start_utc"].min()).isoformat(),
        "end_exclusive_utc": (
            pd.Timestamp(rows["target_start_utc"].max()) + pd.Timedelta(minutes=30)
        ).isoformat(),
        "adaptive_mae_gbp_mwh": adaptive_mae,
        "frozen_model_mae_gbp_mwh": frozen_mae,
        "reference_mae_gbp_mwh": reference_mae,
        "adaptive_improvement_vs_reference_pct": (
            float(improvement) if improvement is not None else None
        ),
        "frozen_model_use_rate": float((rows["adaptive_source"] == "FROZEN_MODEL").mean()),
        "adaptive_win_rate_vs_reference": float(rows["adaptive_beats_reference"].mean()),
    }


def build_v25_report(
    gated_rows: pd.DataFrame,
    *,
    config: Adaptive2hGateConfig = Adaptive2hGateConfig(),
) -> dict[str, Any]:
    t = pd.to_datetime(gated_rows["target_start_utc"], utc=True)
    freeze = _utc(config.candidate_forward_start_utc)
    dev = gated_rows[t < freeze].copy()
    fresh = gated_rows[t >= freeze].copy()
    august = gated_rows[t >= pd.Timestamp("2026-08-01T00:00:00Z")].copy()
    post_lock = gated_rows[t >= pd.Timestamp("2026-08-15T07:30:00Z")].copy()
    return {
        "version": "0.25.0",
        "status": "ADAPTIVE_2H_GATE_EVALUATED",
        "source_v24_artifact_sha256": V24_SOURCE_ARTIFACT_SHA256,
        "frozen_model_state_sha256": FROZEN_MODEL_STATE_SHA256,
        "rule": asdict(config),
        "evidence_policy": {
            "development_rows_before_forward_start": (
                "already observed and permitted for candidate development/diagnosis only"
            ),
            "rows_at_or_after_forward_start": (
                "new versioned v0.25 forward segment; only rows not inspected before the candidate was frozen may support fresh evidence"
            ),
            "no_refit": (
                "the underlying v0.20 2h family, alpha, scaler, coefficients and conformal state are unchanged; v0.25 only switches between that prediction and the previous-settlement-day reference"
            ),
        },
        "segments": {
            "development_to_freeze": adaptive_metrics(dev),
            "august_1_to_latest": adaptive_metrics(august),
            "post_lock_to_latest": adaptive_metrics(post_lock),
            "fresh_v025_forward": adaptive_metrics(fresh),
        },
    }
