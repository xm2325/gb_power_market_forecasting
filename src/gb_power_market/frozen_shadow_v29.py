"""Independent forward shadow of locked v0.20 two-hour ridge coefficients.

The 90-minute input delay changes the predictor interpretation from the old
v0.20 training pipeline. Accordingly these are NEW v0.29 forecasts with
unchanged ridge weights, not a replication of the original v0.20 benchmark.
"""
from __future__ import annotations

from datetime import timedelta
import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from gb_power_market.prospective_v21 import model_from_frozen_state
from gb_power_market.prospective_v28 import (
    canonical_reference, iso, market_end_for_decision, target_after, utc,
    _settlement_key, _previous_day_lookup, _previous_day_price,
)

PREDICTION_SCHEMA = "gb-power-v29-frozen-ridge-shadow-v1"
SCORE_SCHEMA = "gb-power-v29-scored-frozen-shadow-v1"
LOCKED_STATE_SHA256 = "e9952aa88ca56b85f4d595bfe918cdc589ac0048d717d3fb3d9210361eb18918"
MODELS = ("previous_day", "ridge_delay_safe", "ridge_consensus", "ridge_direction_veto")


def load_unchanged_state(path: Path) -> dict[str, Any]:
    if hashlib.sha256(path.read_bytes()).hexdigest() != LOCKED_STATE_SHA256:
        raise ValueError("frozen ridge state bytes do not match v0.21 lock")
    bundle = json.loads(path.read_text(encoding="utf-8"))
    if bundle.get("status") != "FROZEN_MODEL_STATE_EXPORTED":
        raise ValueError("model state is not locked")
    state = bundle["states"]["2h"]
    if state["selected_family"] != "PRICE_PLUS_NESO_LEVELS" or state["horizon_minutes"] != 120:
        raise ValueError("unexpected frozen ridge family or horizon")
    return state


def _asof_price_features(
    history: pd.DataFrame, target: pd.Timestamp, state: dict[str, Any],
) -> dict[str, float]:
    """Historical observed values only; late data may not enter the input."""
    key = _settlement_key(target)
    lookup = _previous_day_lookup(history)
    yesterday = _previous_day_price(lookup, *key)
    week_ago = lookup.get((
        (pd.Timestamp(key[0]) - pd.Timedelta(days=7)).date().isoformat(), key[1]
    ))
    if yesterday is None or week_ago is None:
        raise ValueError("missing GB settlement-key previous day/week feature")
    history = history.sort_values("target_start_utc")
    last = history["reference_market_price_gbp_mwh"].to_numpy(float)
    if len(last) < 48:
        raise ValueError("insufficient observed historical price context")
    local = target.tz_convert("Europe/London")
    hour = local.hour + local.minute / 60
    dow = local.dayofweek
    return {
        "price_lag_last_completed": float(last[-1]),
        "price_lag_2_completed": float(last[-2]),
        "price_lag_1d_same_target": float(yesterday),
        "price_lag_7d_same_target": float(week_ago),
        "price_roll_3h_mean": float(np.mean(last[-6:])),
        "price_roll_24h_median": float(np.median(last[-48:])),
        "hour_sin": float(np.sin(2 * np.pi * hour / 24)),
        "hour_cos": float(np.cos(2 * np.pi * hour / 24)),
        "dow_sin": float(np.sin(2 * np.pi * dow / 7)),
        "dow_cos": float(np.cos(2 * np.pi * dow / 7)),
    }


def _neso_vintage(
    neso: pd.DataFrame, *, target: pd.Timestamp, forecast_created_at: pd.Timestamp,
) -> dict[str, Any]:
    required = {
        "target_end_utc", "publish_time_utc", "wind_mw", "solar_mw",
        "wind_capacity_mw", "solar_capacity_mw",
    }
    if required - set(neso.columns):
        raise ValueError("NESO forecast input missing columns")
    df = neso.copy()
    df["target_end_utc"] = pd.to_datetime(df["target_end_utc"], utc=True, errors="raise")
    df["publish_time_utc"] = pd.to_datetime(df["publish_time_utc"], utc=True, errors="raise")
    relevant = df[(df["target_end_utc"] == target + pd.Timedelta(minutes=30)) &
                  (df["publish_time_utc"] <= forecast_created_at)].copy()
    if relevant.empty:
        raise ValueError("no actually retrieved NESO vintage published before decision")
    relevant = relevant.sort_values("publish_time_utc")
    record = relevant.iloc[-1]
    numerical = ["wind_mw", "solar_mw", "wind_capacity_mw", "solar_capacity_mw"]
    if not np.isfinite(record[numerical].astype(float)).all():
        raise ValueError("non-finite NESO future vintage features")
    if record["publish_time_utc"] > forecast_created_at:
        raise ValueError("NESO feature publication later than forecast")
    return {
        "publication": iso(record["publish_time_utc"]),
        "age_minutes": float((forecast_created_at - record["publish_time_utc"]).total_seconds() / 60),
        "wind_mw": float(record["wind_mw"]),
        "solar_mw": float(record["solar_mw"]),
        "wind_capacity_mw": float(record["wind_capacity_mw"]),
        "solar_capacity_mw": float(record["solar_capacity_mw"]),
    }


def _residual_adjustment(
    scores: list[dict[str, Any]], *,
    now: pd.Timestamp, current_ridge: float,
) -> dict[str, Any]:
    """Only outcomes from already scored, pretarget Git predictions are eligible."""
    history = []
    for score in scores:
        if score.get("schema") != SCORE_SCHEMA or not score.get("prediction_verified_pretarget"):
            continue
        s = utc(score["target_start_utc"])
        if s + pd.Timedelta(minutes=120) > now:  # 30m settlement + 90m buffer
            continue
        if utc(score["scored_at_utc"]) > now:
            continue
        predicted = float(score["forecast_gbp_mwh"]["ridge_delay_safe"])
        observed = float(score["realised_price_gbp_mwh"])
        history.append((s, observed - predicted, predicted))
    history.sort(key=lambda x: x[0])
    if len({s for s, _, _ in history}) != len(history):
        raise ValueError("duplicate historical scored ridge target")
    short = [x for x in history if now - pd.Timedelta(hours=6) < x[0] + pd.Timedelta(minutes=120) <= now]
    long = [x for x in history if now - pd.Timedelta(hours=48) < x[0] + pd.Timedelta(minutes=120) <= now]
    proposal = 0.0
    short_mean, long_mean = None, None
    reason = "WAIT_FOR_GENUINE_PRETARGET_SCORES"
    if len(short) >= 8 and len(long) >= 24:
        short_mean = float(np.mean([x[1] for x in short]))
        long_mean = float(np.mean([x[1] for x in long]))
        if short_mean and long_mean and np.sign(short_mean) == np.sign(long_mean):
            proposal = float(np.sign(short_mean) * min(abs(short_mean), abs(long_mean)))
            reason = "SAME_SIGN_RESIDUALS"
        else:
            reason = "DISAGREEMENT_FALLBACK_RIDGE"
    veto = proposal
    anchor_delta = None
    if proposal:
        anchor_delta = float(current_ridge - long[-1][2])
        if anchor_delta == 0.0 or np.sign(anchor_delta) != np.sign(proposal):
            veto = 0.0
            reason = "FROZEN_RIDGE_DIRECTION_VETO"
    return {
        "consensus_adjustment": proposal,
        "veto_adjustment": veto,
        "short_mean": short_mean,
        "long_mean": long_mean,
        "short_n": len(short),
        "long_n": len(long),
        "anchor_delta": anchor_delta,
        "reason": reason,
    }


def predict_frozen_shadow(
    reference: pd.DataFrame, neso: pd.DataFrame, state: dict[str, Any],
    *, decision: Any, input_end_exclusive: Any,
    scored_history: list[dict[str, Any]] | None = None,
    delay_minutes: int = 90,
) -> dict[str, Any]:
    d = utc(decision)
    cutoff = utc(input_end_exclusive)
    if delay_minutes < 90 or cutoff > market_end_for_decision(d, delay_minutes=delay_minutes):
        raise ValueError("price history exceeds conservative 90-minute availability rule")
    ref = canonical_reference(reference)
    if ref.empty or ref["target_start_utc"].max() != cutoff - pd.Timedelta(minutes=30):
        raise ValueError("price history latest target does not match safe cutoff")
    if (ref["target_start_utc"] >= cutoff).any():
        raise ValueError("price target or future label appears in input")
    expected = pd.date_range(cutoff - pd.Timedelta(days=9), cutoff, freq="30min", inclusive="left")
    if len(expected.difference(pd.DatetimeIndex(ref["target_start_utc"]))):
        raise ValueError("required historical price grid has missing rows")
    target = target_after(d, minimum_lead_minutes=120)
    if target <= d + pd.Timedelta(minutes=119, seconds=59):
        raise ValueError("target does not have at least 120-minute real lead")
    p = _asof_price_features(ref, target, state)
    vintage = _neso_vintage(neso, target=target, forecast_created_at=d)
    p.update({
        "neso_embedded_wind_forecast_mw": vintage["wind_mw"],
        "neso_embedded_solar_forecast_mw": vintage["solar_mw"],
        "neso_embedded_wind_capacity_mw": vintage["wind_capacity_mw"],
        "neso_embedded_solar_capacity_mw": vintage["solar_capacity_mw"],
        "neso_forecast_age_minutes": vintage["age_minutes"],
    })
    features = state["features"]
    if set(p) != set(features):
        raise ValueError("frozen ridge feature names do not match as-of data")
    model = model_from_frozen_state(state)
    yhat = float(model.predict(np.asarray([[p[name] for name in features]], dtype=float))[0])
    if not np.isfinite(yhat):
        raise ValueError("non-finite frozen ridge prediction")
    adapt = _residual_adjustment(scored_history or [], now=d, current_ridge=yhat)
    forecasts = {
        "previous_day": p["price_lag_1d_same_target"],
        "ridge_delay_safe": yhat,
        "ridge_consensus": yhat + adapt["consensus_adjustment"],
        "ridge_direction_veto": yhat + adapt["veto_adjustment"],
    }
    return {
        "schema": PREDICTION_SCHEMA,
        "evidence_class": "LIVE_FORWARD_FROZEN_WEIGHTS_DELAY_SAFE_FEATURES",
        "target_start_utc": iso(target),
        "decision_time_utc": iso(d),
        "effective_lead_minutes": float((target - d).total_seconds() / 60),
        "input_end_exclusive_utc": iso(cutoff),
        "assumed_price_availability_delay_after_period_end_minutes": delay_minutes,
        "frozen_v20_model_state_sha256": LOCKED_STATE_SHA256,
        "model_weights_changed": False,
        "price_feature_semantics_changed_for_availability": True,
        "nominal_model_horizon_minutes": 120,
        "neso_selected_publication_utc": vintage["publication"],
        "neso_forecast_age_minutes": vintage["age_minutes"],
        "forecast_gbp_mwh": {k: float(v) for k, v in forecasts.items()},
        "adjustment": adapt,
        "target_outcome_accessed": False,
        "promotion_eligible": False,
        "claim_boundary": (
            "Original 2h frozen coefficients with conservative delayed price features; "
            "not an exact replay of v0.20/v0.27. Forward labels not used to issue this forecast."
        ),
    }


def score_frozen_shadow(
    prediction: dict[str, Any], *, price: float, scoring_at: Any,
    minimum_delay_minutes: int = 90,
) -> dict[str, Any]:
    target, now = utc(prediction["target_start_utc"]), utc(scoring_at)
    if now < target + pd.Timedelta(minutes=30 + minimum_delay_minutes):
        raise ValueError("outcome not mature")
    if prediction.get("schema") != PREDICTION_SCHEMA or prediction.get("target_outcome_accessed") is not False:
        raise ValueError("not a pretarget frozen-ridge prediction")
    if not np.isfinite(price) or set(prediction["forecast_gbp_mwh"]) != set(MODELS):
        raise ValueError("invalid price or forecast collection")
    errors = {model: abs(prediction["forecast_gbp_mwh"][model] - float(price)) for model in MODELS}
    return {
        "schema": SCORE_SCHEMA,
        "evidence_class": "SCORED_LIVE_FORWARD_WITH_DELAY_SAFE_FEATURES",
        "target_start_utc": iso(target),
        "scored_at_utc": iso(now),
        "realised_price_gbp_mwh": float(price),
        "forecast_gbp_mwh": prediction["forecast_gbp_mwh"],
        "absolute_error_gbp_mwh": errors,
        "signed_error_gbp_mwh": {
            model: prediction["forecast_gbp_mwh"][model] - float(price) for model in MODELS
        },
        "paired_gain_vs_previous_day_gbp_mwh": {
            model: errors["previous_day"] - errors[model] for model in MODELS if model != "previous_day"
        },
        "automatic_promotion": False,
    }


def summary(scores: list[dict[str, Any]]) -> dict[str, Any]:
    ordered = sorted(scores, key=lambda x: x["target_start_utc"])
    if len({x["target_start_utc"] for x in ordered}) != len(ordered):
        raise ValueError("duplicate scored target")
    return {
        "schema": PREDICTION_SCHEMA,
        "rows": len(ordered),
        "mae_gbp_mwh": {
            m: float(np.mean([r["absolute_error_gbp_mwh"][m] for r in ordered]))
            if ordered else None for m in MODELS
        },
        "p95_abs_error_gbp_mwh": {
            m: float(np.quantile([r["absolute_error_gbp_mwh"][m] for r in ordered], 0.95))
            if ordered else None for m in MODELS
        },
        "signed_bias_gbp_mwh": {
            m: float(np.mean([r["signed_error_gbp_mwh"][m] for r in ordered]))
            if ordered else None for m in MODELS
        },
        "latest_target_utc": ordered[-1]["target_start_utc"] if ordered else None,
        "minimum_review_rows": 336,
        "review_mature": len(ordered) >= 336,
        "automatic_promotion": False,
    }
