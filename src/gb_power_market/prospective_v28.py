"""v0.28 live shadow experiment: conservative, time-stamped GB price forecasts.

This does NOT replay the frozen v0.20-v0.27 models or claim that a historical
snapshot proves point-in-time availability. Only a source snapshot fetched
before the future target, with the input cutoff recorded, is live evidence.
"""
from __future__ import annotations

from datetime import timedelta
import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from gb_power_market.elexon_v19 import expected_settlement_keys


SCHEMA = "gb-power-v28-shadow-1"
MIN_FORWARD_ROWS_FOR_REVIEW = 336
METHODS = ("previous_day", "consensus", "direction_veto")


def utc(value: Any) -> pd.Timestamp:
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None:
        raise ValueError("time must be timezone-aware")
    return timestamp.tz_convert("UTC")


def iso(value: Any) -> str:
    return utc(value).isoformat()


def target_after(decision: Any, *, minimum_lead_minutes: int = 120) -> pd.Timestamp:
    if minimum_lead_minutes < 120:
        raise ValueError("minimum prospective lead must be at least 120 minutes")
    minimum = utc(decision) + pd.Timedelta(minutes=minimum_lead_minutes)
    return minimum.ceil("30min")


def market_end_for_decision(decision: Any, *, delay_minutes: int = 90) -> pd.Timestamp:
    """End-exclusive target-start cutoff; observed settlement period ends 30m later.

    A source row starting at s is eligible only if s + 30m + delay <= decision.
    At a given decision, all allowed rows have start < this cutoff.
    """
    if delay_minutes < 30:
        raise ValueError("minimum post-period delay is 30 minutes")
    return (utc(decision) - pd.Timedelta(minutes=30 + delay_minutes)).floor("30min") + pd.Timedelta(minutes=30)


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_reference(frame: pd.DataFrame) -> pd.DataFrame:
    required = {"target_start_utc", "settlement_date", "settlement_period",
                "reference_market_price_gbp_mwh"}
    if required - set(frame.columns):
        raise ValueError(f"missing Elexon reference columns: {sorted(required - set(frame.columns))}")
    out = frame[list(required)].copy()
    out["target_start_utc"] = pd.to_datetime(out["target_start_utc"], utc=True, errors="raise")
    out["settlement_date"] = pd.to_datetime(out["settlement_date"]).dt.date.astype(str)
    out["settlement_period"] = pd.to_numeric(out["settlement_period"], errors="raise").astype(int)
    out["reference_market_price_gbp_mwh"] = pd.to_numeric(
        out["reference_market_price_gbp_mwh"], errors="raise"
    ).astype(float)
    out = out.sort_values("target_start_utc").reset_index(drop=True)
    if out["target_start_utc"].duplicated().any() or out.duplicated(
        ["settlement_date", "settlement_period"]
    ).any():
        raise ValueError("duplicate GB settlement keys")
    if not np.isfinite(out["reference_market_price_gbp_mwh"].to_numpy()).all():
        raise ValueError("non-finite price")
    return out


def _settlement_key(target: pd.Timestamp) -> tuple[str, int]:
    local_date = target.tz_convert("Europe/London").date()
    keys = expected_settlement_keys(
        (local_date - timedelta(days=1)).isoformat(),
        (local_date + timedelta(days=2)).isoformat(),
    )
    matching = keys[pd.to_datetime(keys["target_start_utc"], utc=True) == target]
    if len(matching) != 1:
        raise ValueError("target is not exactly one GB settlement period")
    row = matching.iloc[0]
    return str(row["settlement_date"]), int(row["settlement_period"])


def _previous_day_lookup(rows: pd.DataFrame) -> dict[tuple[str, int], float]:
    return {(str(row.settlement_date), int(row.settlement_period)): float(row.reference_market_price_gbp_mwh)
            for row in rows.itertuples(index=False)}


def _previous_day_price(lookup: dict[tuple[str, int], float],
                        settlement_date: str, settlement_period: int) -> float | None:
    previous = (pd.Timestamp(settlement_date) - pd.Timedelta(days=1)).date().isoformat()
    return lookup.get((previous, settlement_period))


def _history(frame: pd.DataFrame, lookup: dict[tuple[str, int], float],
             decision: pd.Timestamp, delay_minutes: int) -> pd.DataFrame:
    recent = frame[frame["target_start_utc"] >= decision - pd.Timedelta(days=4)].copy()
    recent["available_utc"] = recent["target_start_utc"] + pd.Timedelta(minutes=30 + delay_minutes)
    recent = recent[recent["available_utc"] <= decision].copy()
    recent["previous_day"] = [
        _previous_day_price(lookup, date, period)
        for date, period in zip(recent["settlement_date"], recent["settlement_period"])
    ]
    recent = recent.dropna(subset=["previous_day"]).copy()
    recent["residual"] = recent["reference_market_price_gbp_mwh"] - recent["previous_day"]
    return recent.sort_values("target_start_utc").reset_index(drop=True)


def predict_shadow(
    frame: pd.DataFrame,
    *,
    decision: Any,
    input_end_exclusive: Any,
    delay_minutes: int = 90,
    minimum_lead_minutes: int = 120,
) -> dict[str, Any]:
    """Produce the 3 precommitted v0.28 methods from data already retrieved.

    Current/future target outcomes cannot enter this function; the target must
    be beyond the decision time and beyond the latest source target timestamp.
    """
    d = utc(decision)
    cutoff = utc(input_end_exclusive)
    if cutoff > market_end_for_decision(d, delay_minutes=delay_minutes):
        raise ValueError("price input cutoff exceeds conservative availability boundary")
    frame = canonical_reference(frame)
    if frame.empty or frame["target_start_utc"].max() >= cutoff:
        raise ValueError("price snapshot contains data at/after input cutoff, or is empty")
    if frame["target_start_utc"].max() != cutoff - pd.Timedelta(minutes=30):
        raise ValueError("latest conservative source settlement period is missing")
    # Prevent a silent incomplete-historical-feature replay.
    expected = pd.date_range(cutoff - pd.Timedelta(days=9), cutoff, freq="30min", inclusive="left")
    actual = pd.DatetimeIndex(frame["target_start_utc"])
    if len(expected.difference(actual)):
        raise ValueError("price snapshot has gaps within required nine-day context")

    target = target_after(d, minimum_lead_minutes=minimum_lead_minutes)
    if target <= frame["target_start_utc"].max():
        raise ValueError("target price already present in input")
    settlement_date, period = _settlement_key(target)
    lookup = _previous_day_lookup(frame)
    baseline = _previous_day_price(lookup, settlement_date, period)
    if baseline is None:
        raise ValueError("previous settlement day price for future target is absent")

    hist = _history(frame, lookup, d, delay_minutes)
    short = hist[(hist["available_utc"] > d - pd.Timedelta(hours=6)) &
                 (hist["available_utc"] <= d)]
    long = hist[(hist["available_utc"] > d - pd.Timedelta(hours=48)) &
                (hist["available_utc"] <= d)]
    proposal = 0.0
    reason = "INSUFFICIENT_CAUSAL_HISTORY"
    short_mean = None
    long_mean = None
    if len(short) >= 8 and len(long) >= 24:
        short_mean = float(short["residual"].mean())
        long_mean = float(long["residual"].mean())
        if short_mean and long_mean and np.sign(short_mean) == np.sign(long_mean):
            proposal = float(np.sign(short_mean) * min(abs(short_mean), abs(long_mean)))
            reason = "SAME_SIGN_CLIPPED_CORRECTION"
        else:
            reason = "RESIDUAL_SIGN_DISAGREEMENT"
    veto_correction = proposal
    anchor_delta = None
    veto_reason = reason
    if proposal:
        anchor = long.iloc[-1] if len(long) else None
        if anchor is None:
            veto_correction = 0.0
            veto_reason = "NO_CAUSAL_ANCHOR"
        else:
            anchor_delta = float(baseline - anchor["previous_day"])
            if not anchor_delta or np.sign(anchor_delta) != np.sign(proposal):
                veto_correction = 0.0
                veto_reason = "BASE_DIRECTION_VETO"
            else:
                veto_reason = "DIRECTION_ALIGNED_CORRECTION"

    lead_minutes = (target - d).total_seconds() / 60.0
    return {
        "schema": SCHEMA,
        "evidence_class": "PRETARGET_SHADOW_FORECAST_NO_REALIZED_TARGET",
        "decision_time_utc": iso(d),
        "target_start_utc": iso(target),
        "effective_lead_minutes": lead_minutes,
        "minimum_lead_minutes": minimum_lead_minutes,
        "settlement_date": settlement_date,
        "settlement_period": period,
        "price_input_end_exclusive_utc": iso(cutoff),
        "assumed_min_post_period_delay_minutes": delay_minutes,
        "forecast_gbp_mwh": {
            "previous_day": float(baseline),
            "consensus": float(baseline + proposal),
            "direction_veto": float(baseline + veto_correction),
        },
        "diagnostic": {
            "short_history_rows": int(len(short)),
            "long_history_rows": int(len(long)),
            "short_residual_mean_gbp_mwh": short_mean,
            "long_residual_mean_gbp_mwh": long_mean,
            "consensus_correction_gbp_mwh": proposal,
            "direction_anchor_delta_gbp_mwh": anchor_delta,
            "direction_veto_correction_gbp_mwh": veto_correction,
            "consensus_reason": reason,
            "veto_reason": veto_reason,
        },
        "target_outcome_accessed": False,
        "automatic_promotion": False,
    }


def score_shadow(
    prediction: dict[str, Any],
    *,
    observed_price: float,
    scored_at: Any,
    scoring_delay_minutes: int = 90,
) -> dict[str, Any]:
    target = utc(prediction["target_start_utc"])
    now = utc(scored_at)
    if now < target + pd.Timedelta(minutes=30 + scoring_delay_minutes):
        raise ValueError("target has not reached conservative score maturity")
    if prediction.get("schema") != SCHEMA or prediction.get("target_outcome_accessed") is not False:
        raise ValueError("not an unchanged pretarget v0.28 prediction")
    if not np.isfinite(observed_price):
        raise ValueError("non-finite observed price")
    forecasts = prediction["forecast_gbp_mwh"]
    if set(forecasts) != set(METHODS):
        raise ValueError("unexpected forecast methods")
    errors = {key: abs(float(forecasts[key]) - observed_price) for key in METHODS}
    return {
        "schema": SCHEMA,
        "evidence_class": "SCORED_GENUINE_PRETARGET_SHADOW",
        "target_start_utc": iso(target),
        "score_time_utc": iso(now),
        "realised_price_gbp_mwh": float(observed_price),
        "absolute_error_gbp_mwh": errors,
        "signed_error_gbp_mwh": {
            method: float(forecasts[method]) - observed_price for method in METHODS
        },
        "effective_lead_minutes": float(prediction["effective_lead_minutes"]),
        "paired_gain_vs_previous_day_gbp_mwh": {
            method: errors["previous_day"] - errors[method]
            for method in METHODS if method != "previous_day"
        },
        "automatic_promotion": False,
    }


def _paired_daily_bootstrap(
    scores: list[dict[str, Any]], method: str, *, n_resamples: int = 2000
) -> dict[str, Any] | None:
    """Paired day-block uncertainty, not an untouched confirmatory experiment."""
    if len(scores) < 672:
        return None
    day_gains: dict[str, list[float]] = {}
    for score in scores:
        date = utc(score["target_start_utc"]).date().isoformat()
        day_gains.setdefault(date, []).append(
            score["paired_gain_vs_previous_day_gbp_mwh"][method]
        )
    if len(day_gains) < 14:
        return None
    gains_sum = np.array([sum(values) for values in day_gains.values()], dtype=float)
    gains_count = np.array([len(values) for values in day_gains.values()], dtype=float)
    rng = np.random.default_rng(202628)
    sampled_days = rng.integers(0, len(gains_sum), size=(n_resamples, len(gains_sum)))
    draws = gains_sum[sampled_days].sum(axis=1) / gains_count[sampled_days].sum(axis=1)
    lower, upper = np.quantile(draws, [0.025, 0.975])
    return {
        "method": "paired_UTC_day_block_bootstrap",
        "blocks": len(gains_sum),
        "resamples": n_resamples,
        "seed": 202628,
        "paired_gain_positive_means_challenger_better": True,
        "interval95_gbp_mwh": [float(lower), float(upper)],
        "includes_zero": bool(lower <= 0 <= upper),
        "evidence_class": "DESCRIPTIVE_PROSPECTIVE_UNCERTAINTY",
    }


def summarise_scores(scores: list[dict[str, Any]]) -> dict[str, Any]:
    ordered = sorted(scores, key=lambda x: x["target_start_utc"])
    targets = [x["target_start_utc"] for x in ordered]
    if len(targets) != len(set(targets)):
        raise ValueError("duplicate scored target")

    def summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "rows": len(rows),
            "mae_gbp_mwh": {
                method: float(np.mean([x["absolute_error_gbp_mwh"][method] for x in rows]))
                if rows else None for method in METHODS
            },
            "p95_abs_error_gbp_mwh": {
                method: float(np.quantile([x["absolute_error_gbp_mwh"][method] for x in rows], 0.95))
                if rows else None for method in METHODS
            },
            "signed_bias_gbp_mwh": {
                method: float(np.mean([x["signed_error_gbp_mwh"][method] for x in rows]))
                if rows else None for method in METHODS
            },
            "mean_paired_gain_vs_previous_day_gbp_mwh": {
                method: float(np.mean([
                    x["paired_gain_vs_previous_day_gbp_mwh"][method] for x in rows
                ])) if rows else None for method in METHODS if method != "previous_day"
            },
            "win_rate_vs_previous_day": {
                method: float(np.mean([
                    x["absolute_error_gbp_mwh"][method] <
                    x["absolute_error_gbp_mwh"]["previous_day"]
                    for x in rows
                ])) if rows else None for method in METHODS if method != "previous_day"
            },
        }

    all_result = summary(ordered)
    last48 = summary(ordered[-48:])
    alerts = []
    if last48["rows"] == 48:
        reference = last48["mae_gbp_mwh"]["previous_day"]
        for name in METHODS[1:]:
            if last48["mae_gbp_mwh"][name] > reference:
                alerts.append(f"{name.upper()}_TRAILS_PREVIOUS_DAY_48_ROWS")
    return {
        "schema": SCHEMA,
        "evidence_class": "GITHUB_FROZEN_FORWARD_SCORE_ONLY",
        "all": all_result,
        "last_48_scored": last48,
        "first_target_utc": targets[0] if targets else None,
        "latest_target_utc": targets[-1] if targets else None,
        "review_maturity_rows": MIN_FORWARD_ROWS_FOR_REVIEW,
        "review_mature": len(ordered) >= MIN_FORWARD_ROWS_FOR_REVIEW,
        "daily_block_uncertainty": {
            method: _paired_daily_bootstrap(ordered, method)
            for method in METHODS if method != "previous_day"
        },
        "alerts": alerts,
        "automatic_promotion": False,
        "claim_boundary": "Prospective scores only if prediction Git commit preceded target. This report is not a trading-PnL claim.",
    }


def write_json_new(path: Path, value: dict[str, Any]) -> None:
    if path.exists():
        raise FileExistsError(f"immutable evidence already exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
