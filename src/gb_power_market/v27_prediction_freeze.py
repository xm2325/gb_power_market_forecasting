from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .adaptive_direction_v27_candidate import apply_causal_direction_veto_candidate
from .elexon_v19 import build_information_safe_market_frame, expected_settlement_keys
from .prospective_v21 import model_from_frozen_state


IMPLEMENTATION_LOCK_SCHEMA = "gb-power-market-v27-forward-implementation-lock-v1"
IMPLEMENTATION_LOCK_STATUS = "FRESH_FORWARD_CANDIDATE_LOCKED_NOT_YET_EVALUATED"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _utc(value: str | pd.Timestamp) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    if ts.tzinfo is None:
        raise ValueError("prediction-freeze timestamp must be timezone-aware")
    return ts.tz_convert("UTC")


def _utc_series(values: pd.Series) -> pd.Series:
    """Normalise equivalent CSV/ISO timestamp spellings without changing instants."""
    try:
        return pd.to_datetime(values, utc=True, errors="raise", format="mixed")
    except TypeError:
        # Compatibility fallback for older pandas versions that do not expose
        # format='mixed'. Parsing item-by-item preserves the exact UTC instants.
        return values.map(lambda value: _utc(value))


def verify_freeze_window(*, implementation_lock: dict[str, Any], now_utc: str | pd.Timestamp) -> dict[str, str]:
    if implementation_lock.get("schema") != IMPLEMENTATION_LOCK_SCHEMA:
        raise ValueError("unsupported v0.27 implementation lock")
    if implementation_lock.get("status") != IMPLEMENTATION_LOCK_STATUS:
        raise ValueError("v0.27 implementation lock is not in zero-outcome forward state")
    if implementation_lock.get("forward_evidence_rows_at_lock") != 0:
        raise ValueError("v0.27 implementation lock already contains forward outcomes")
    decision = _utc(implementation_lock["first_forward_decision_time_utc"])
    target = _utc(implementation_lock["forward_start_utc"])
    now = _utc(now_utc)
    if now < decision:
        raise RuntimeError("V27_FIRST_DECISION_NOT_REACHED: prediction freeze cannot run before the locked decision time")
    if now >= target:
        raise RuntimeError("V27_FIRST_TARGET_ALREADY_STARTED: refusing retrospective first-prediction freeze")
    return {
        "now_utc": now.isoformat(),
        "decision_time_utc": decision.isoformat(),
        "target_start_utc": target.isoformat(),
    }


def _append_unknown_future_grid(reference: pd.DataFrame, *, target_start_utc: pd.Timestamp) -> pd.DataFrame:
    required = {
        "target_start_utc",
        "settlement_date",
        "settlement_period",
        "reference_market_price_gbp_mwh",
    }
    missing = sorted(required - set(reference.columns))
    if missing:
        raise ValueError(f"reference history missing columns: {missing}")
    ref = reference.copy()
    ref["target_start_utc"] = pd.to_datetime(ref["target_start_utc"], utc=True, errors="raise")
    ref = ref.sort_values("target_start_utc").reset_index(drop=True)
    if ref.empty:
        raise ValueError("empty reference history")
    last = ref["target_start_utc"].iloc[-1]
    if last >= target_start_utc:
        raise ValueError("reference history already contains the first v0.27 target")

    start_date = pd.Timestamp(last).tz_convert("Europe/London").date().isoformat()
    end_date = (pd.Timestamp(target_start_utc).tz_convert("Europe/London").date() + pd.Timedelta(days=1)).isoformat()
    keys = expected_settlement_keys(start_date, end_date)
    keys["target_start_utc"] = pd.to_datetime(keys["target_start_utc"], utc=True, errors="raise")
    future = keys[(keys["target_start_utc"] > last) & (keys["target_start_utc"] <= target_start_utc)][
        ["target_start_utc", "settlement_date", "settlement_period"]
    ].copy()
    expected = pd.date_range(last + pd.Timedelta(minutes=30), target_start_utc, freq="30min")
    if list(future["target_start_utc"]) != list(expected):
        raise ValueError("could not construct a complete unknown future settlement grid")
    future["reference_market_price_gbp_mwh"] = np.nan
    combined = pd.concat(
        [
            ref[["target_start_utc", "settlement_date", "settlement_period", "reference_market_price_gbp_mwh"]],
            future,
        ],
        ignore_index=True,
    )
    return combined


def build_first_frozen_target_row(
    *,
    reference_history: pd.DataFrame,
    neso_current: pd.DataFrame,
    model_bundle: dict[str, Any],
    implementation_lock: dict[str, Any],
) -> dict[str, Any]:
    target = _utc(implementation_lock["forward_start_utc"])
    decision = _utc(implementation_lock["first_forward_decision_time_utc"])
    if target - decision != pd.Timedelta(minutes=120):
        raise ValueError("v0.27 first target is not exactly a 2h horizon from its locked decision")

    state = model_bundle["states"]["2h"]
    if int(state["horizon_minutes"]) != 120 or state["selected_family"] != "PRICE_PLUS_NESO_LEVELS":
        raise ValueError("unexpected frozen 2h model state")

    ref = reference_history.copy()
    ref["target_start_utc"] = pd.to_datetime(ref["target_start_utc"], utc=True, errors="raise")
    ref = ref.sort_values("target_start_utc").reset_index(drop=True)
    required_latest = decision - pd.Timedelta(minutes=30)
    if ref["target_start_utc"].iloc[-1] != required_latest:
        raise ValueError(
            f"reference history must end exactly at the latest outcome available by decision: {required_latest.isoformat()}"
        )
    future_safe = _append_unknown_future_grid(ref, target_start_utc=target)
    frame = build_information_safe_market_frame(future_safe, horizon_minutes=120)
    target_frame = frame[frame["target_start_utc"] == target].copy()
    if len(target_frame) != 1:
        raise ValueError("expected exactly one first-target market feature row")

    neso = neso_current.copy()
    neso["target_end_utc"] = pd.to_datetime(neso["target_end_utc"], utc=True, errors="raise")
    neso["publish_time_utc"] = pd.to_datetime(neso["publish_time_utc"], utc=True, errors="raise")
    target_end = target + pd.Timedelta(minutes=30)
    eligible = neso[(neso["target_end_utc"] == target_end) & (neso["publish_time_utc"] <= decision)].copy()
    if eligible.empty:
        raise ValueError("no causal NESO vintage available for the first v0.27 target")
    selected = eligible.sort_values("publish_time_utc").iloc[-1]
    if pd.Timestamp(selected["publish_time_utc"]) > decision:
        raise ValueError("future NESO publication entered first v0.27 prediction")

    target_frame["neso_publish_time_utc"] = pd.Timestamp(selected["publish_time_utc"])
    target_frame["neso_source_regime"] = str(selected["source_regime"])
    target_frame["neso_forecast_age_minutes"] = (
        decision - pd.Timestamp(selected["publish_time_utc"])
    ).total_seconds() / 60.0
    target_frame["neso_embedded_wind_forecast_mw"] = float(selected["wind_mw"])
    target_frame["neso_embedded_wind_capacity_mw"] = float(selected["wind_capacity_mw"])
    target_frame["neso_embedded_solar_forecast_mw"] = float(selected["solar_mw"])
    target_frame["neso_embedded_solar_capacity_mw"] = float(selected["solar_capacity_mw"])

    features = list(state["features"])
    if target_frame[features].isna().any(axis=None):
        bad = target_frame[features].columns[target_frame[features].isna().any()].tolist()
        raise ValueError(f"first v0.27 target has incomplete frozen features: {bad}")
    model = model_from_frozen_state(state)
    frozen_prediction = float(model.predict(target_frame[features].to_numpy(float))[0])
    q = float(state["conformal_absolute_residual_quantile_gbp_mwh"])
    row = target_frame.iloc[0]
    return {
        "target_start_utc": target.isoformat(),
        "decision_time_utc": decision.isoformat(),
        "realised_price_gbp_mwh": np.nan,
        "frozen_prediction_gbp_mwh": frozen_prediction,
        "previous_settlement_day_reference_gbp_mwh": float(row["price_lag_1d_same_target"]),
        "last_completed_price_gbp_mwh": float(row["price_lag_last_completed"]),
        "interval_lower_gbp_mwh": frozen_prediction - q,
        "interval_upper_gbp_mwh": frozen_prediction + q,
        "neso_publish_time_utc": pd.Timestamp(selected["publish_time_utc"]).isoformat(),
        "neso_forecast_age_minutes": float(target_frame.iloc[0]["neso_forecast_age_minutes"]),
    }


def freeze_first_prediction(
    *,
    historical_frozen_rows: pd.DataFrame,
    first_target_row: dict[str, Any],
    implementation_lock: dict[str, Any],
) -> dict[str, Any]:
    history = historical_frozen_rows.copy()
    history["target_start_utc"] = _utc_series(history["target_start_utc"])
    history["decision_time_utc"] = _utc_series(history["decision_time_utc"])
    decision = _utc(implementation_lock["first_forward_decision_time_utc"])
    target = _utc(implementation_lock["forward_start_utc"])
    latest_allowed = decision - pd.Timedelta(minutes=30)
    if history.empty or history["target_start_utc"].max() != latest_allowed:
        raise ValueError("historical frozen rows do not end at the latest causally available target")
    if (history["target_start_utc"] >= target).any():
        raise ValueError("historical frozen rows leaked the first v0.27 target or later")

    first = pd.DataFrame([first_target_row])
    first["target_start_utc"] = _utc_series(first["target_start_utc"])
    first["decision_time_utc"] = _utc_series(first["decision_time_utc"])
    combined = pd.concat([history, first], ignore_index=True, sort=False)
    scored = apply_causal_direction_veto_candidate(combined)
    scored["target_start_utc"] = pd.to_datetime(scored["target_start_utc"], utc=True, errors="raise")
    row = scored[scored["target_start_utc"] == target]
    if len(row) != 1:
        raise ValueError("v0.27 candidate did not produce exactly one first-target prediction")
    r = row.iloc[0]
    if not pd.isna(r["realised_price_gbp_mwh"]):
        raise ValueError("first v0.27 target label was present during prediction freeze")
    if pd.Timestamp(r["decision_time_utc"]) != decision:
        raise ValueError("first v0.27 prediction decision time changed")

    return {
        "schema": "gb-power-market-v27-first-forward-prediction-v1",
        "status": "PREDICTION_FROZEN_BEFORE_TARGET_OUTCOME",
        "version": "0.27.0",
        "candidate": implementation_lock["candidate"],
        "target_start_utc": target.isoformat(),
        "decision_time_utc": decision.isoformat(),
        "frozen_prediction_gbp_mwh": float(r["frozen_prediction_gbp_mwh"]),
        "v27_prediction_gbp_mwh": float(r["v27_prediction_gbp_mwh"]),
        "v27_correction_gbp_mwh": float(r["v27_correction_gbp_mwh"]),
        "v27_base_v26_correction_gbp_mwh": float(r["v27_base_v26_correction_gbp_mwh"]),
        "v27_gate_reason": str(r["v27_gate_reason"]),
        "v26_short_residual_mean_gbp_mwh": float(r["v26_short_residual_mean_gbp_mwh"]),
        "v26_long_residual_mean_gbp_mwh": float(r["v26_long_residual_mean_gbp_mwh"]),
        "v26_short_history_rows": int(r["v26_short_history_rows"]),
        "v26_long_history_rows": int(r["v26_long_history_rows"]),
        "v26_history_latest_target_utc": str(r["v26_history_latest_target_utc"]),
        "v27_direction_anchor_frozen_prediction_gbp_mwh": (
            None if pd.isna(r["v27_direction_anchor_frozen_prediction_gbp_mwh"]) else float(r["v27_direction_anchor_frozen_prediction_gbp_mwh"])
        ),
        "v27_frozen_direction_delta_gbp_mwh": (
            None if pd.isna(r["v27_frozen_direction_delta_gbp_mwh"]) else float(r["v27_frozen_direction_delta_gbp_mwh"])
        ),
        "interval_lower_gbp_mwh": float(r["interval_lower_gbp_mwh"] + r["v27_correction_gbp_mwh"]),
        "interval_upper_gbp_mwh": float(r["interval_upper_gbp_mwh"] + r["v27_correction_gbp_mwh"]),
        "previous_settlement_day_reference_gbp_mwh": float(r["previous_settlement_day_reference_gbp_mwh"]),
        "neso_publish_time_utc": str(first_target_row["neso_publish_time_utc"]),
        "neso_forecast_age_minutes": float(first_target_row["neso_forecast_age_minutes"]),
        "target_label_status": "UNOBSERVED_NOT_ACCESSED",
        "realised_price_in_prediction_record": False,
        "implementation_lock_sha256": sha256_file(Path("reports/locked/V0_27_IMPLEMENTATION_LOCK.json")),
        "predictive_source_git_blob_sha1": implementation_lock["candidate_source"]["git_blob_sha1"],
        "claim_boundary": (
            "This record freezes a prediction before the target period begins. It contains no realised target price "
            "and is not a performance result; later scoring must join the outcome in a separately versioned evidence step."
        ),
    }
