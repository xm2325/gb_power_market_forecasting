"""Synthetic contract tests only: these results are never market evidence."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from pathlib import Path

from gb_power_market.elexon_v19 import expected_settlement_keys
from gb_power_market.frozen_shadow_v29 import (
    LOCKED_STATE_SHA256, SCORE_SCHEMA, load_unchanged_state,
    predict_frozen_shadow, score_frozen_shadow, summary,
)
from gb_power_market.prospective_v28 import market_end_for_decision, target_after


ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / "reports/locked/V0_21_FROZEN_MODEL_STATE.json"


def fixture(decision: str = "2026-10-09T21:51:15Z"):
    now = pd.Timestamp(decision)
    cutoff = market_end_for_decision(now)
    begin = (cutoff - pd.Timedelta(days=14)).date().isoformat()
    finish = (cutoff + pd.Timedelta(days=3)).date().isoformat()
    ref = expected_settlement_keys(begin, finish)
    ref["target_start_utc"] = pd.to_datetime(ref["target_start_utc"], utc=True)
    ref = ref[ref["target_start_utc"] < cutoff].copy().reset_index(drop=True)
    k = np.arange(len(ref), dtype=float)
    ref["reference_market_price_gbp_mwh"] = 70 + 6 * np.sin(k * np.pi / 24) + k * 0.01
    target = target_after(now)
    neso = pd.DataFrame({
        "target_end_utc": [target + pd.Timedelta(minutes=30)],
        "publish_time_utc": [now - pd.Timedelta(minutes=20)],
        "wind_mw": [2700.],
        "solar_mw": [1400.],
        "wind_capacity_mw": [6600.],
        "solar_capacity_mw": [21900.],
    })
    return ref, neso, now, cutoff


def test_frozen_model_is_byte_locked():
    state = load_unchanged_state(STATE)
    assert state["horizon_minutes"] == 120
    assert state["selected_family"] == "PRICE_PLUS_NESO_LEVELS"
    assert LOCKED_STATE_SHA256 == "e9952aa88ca56b85f4d595bfe918cdc589ac0048d717d3fb3d9210361eb18918"


def test_frozen_weights_shadow_uses_only_conservative_snapshot():
    ref, neso, now, cutoff = fixture()
    state = load_unchanged_state(STATE)
    result = predict_frozen_shadow(
        ref, neso, state, decision=now, input_end_exclusive=cutoff,
    )
    assert set(result["forecast_gbp_mwh"]) == {
        "previous_day", "ridge_delay_safe", "ridge_consensus", "ridge_direction_veto"
    }
    assert result["target_outcome_accessed"] is False
    assert result["price_feature_semantics_changed_for_availability"] is True
    assert result["model_weights_changed"] is False
    assert result["effective_lead_minutes"] >= 120
    assert result["neso_selected_publication_utc"] <= result["decision_time_utc"]
    assert result["adjustment"]["consensus_adjustment"] == 0
    assert result["adjustment"]["reason"] == "WAIT_FOR_GENUINE_PRETARGET_SCORES"
    assert "realised_price_gbp_mwh" not in result


def test_future_price_cannot_enter_inference():
    ref, neso, now, cutoff = fixture()
    state = load_unchanged_state(STATE)
    a = predict_frozen_shadow(ref, neso, state, decision=now, input_end_exclusive=cutoff)
    modified = ref.copy()
    # Mutating a target future to the prediction is blocked before model inference.
    future = expected_settlement_keys("2026-10-10", "2026-10-11")
    future["target_start_utc"] = pd.to_datetime(future["target_start_utc"], utc=True)
    row = future[future["target_start_utc"] == pd.Timestamp(a["target_start_utc"])].iloc[0].copy()
    row["reference_market_price_gbp_mwh"] = 100000.
    with pytest.raises(ValueError, match="cutoff|future|price history"):
        predict_frozen_shadow(
            pd.concat([ref, pd.DataFrame([row])], ignore_index=True),
            neso, state, decision=now, input_end_exclusive=cutoff,
        )
    b = predict_frozen_shadow(ref.copy(), neso, state, decision=now, input_end_exclusive=cutoff)
    assert a["forecast_gbp_mwh"] == b["forecast_gbp_mwh"]


def test_neso_future_vintage_rejected():
    ref, neso, now, cutoff = fixture()
    state = load_unchanged_state(STATE)
    neso["publish_time_utc"] = now + pd.Timedelta(hours=1)
    with pytest.raises(ValueError, match="no actually retrieved NESO vintage"):
        predict_frozen_shadow(ref, neso, state, decision=now, input_end_exclusive=cutoff)


def test_gaps_and_too_recent_price_cutoff_fail_closed():
    ref, neso, now, cutoff = fixture()
    state = load_unchanged_state(STATE)
    with pytest.raises(ValueError, match="availability"):
        predict_frozen_shadow(
            ref, neso, state, decision=now,
            input_end_exclusive=cutoff + pd.Timedelta(minutes=30),
        )
    row_time = cutoff - pd.Timedelta(hours=2)
    with pytest.raises(ValueError, match="missing rows"):
        predict_frozen_shadow(
            ref[ref["target_start_utc"] != row_time], neso, state,
            decision=now, input_end_exclusive=cutoff,
        )


def test_only_matured_scores_and_no_automatic_promotion():
    ref, neso, now, cutoff = fixture()
    state = load_unchanged_state(STATE)
    prediction = predict_frozen_shadow(
        ref, neso, state, decision=now, input_end_exclusive=cutoff,
    )
    target = pd.Timestamp(prediction["target_start_utc"])
    with pytest.raises(ValueError, match="outcome not mature"):
        score_frozen_shadow(prediction, price=84.0, scoring_at=target)
    scored = score_frozen_shadow(
        prediction, price=84.0, scoring_at=target + pd.Timedelta(hours=2),
    )
    assert scored["schema"] == SCORE_SCHEMA
    assert scored["absolute_error_gbp_mwh"]["ridge_delay_safe"] >= 0
    result = summary([scored])
    assert result["rows"] == 1
    assert result["automatic_promotion"] is False


def test_online_correction_uses_scored_prospective_history_only():
    ref, neso, now, cutoff = fixture()
    state = load_unchanged_state(STATE)
    forecast = predict_frozen_shadow(
        ref, neso, state, decision=now, input_end_exclusive=cutoff,
    )
    # These synthetic rows exercise timing / gating; they are not historical evidence.
    scores = []
    for i in range(48):
        target = now - pd.Timedelta(hours=27) + pd.Timedelta(minutes=30 * i)
        scores.append({
            "schema": SCORE_SCHEMA,
            "target_start_utc": target.isoformat(),
            "scored_at_utc": (target + pd.Timedelta(minutes=120)).isoformat(),
            "prediction_verified_pretarget": True,
            "forecast_gbp_mwh": {"ridge_delay_safe": 50.0},
            "realised_price_gbp_mwh": 60.0,
        })
    result = predict_frozen_shadow(
        ref, neso, state, decision=now, input_end_exclusive=cutoff,
        scored_history=scores,
    )
    assert result["adjustment"]["short_n"] >= 8
    assert result["adjustment"]["long_n"] >= 24
    assert result["adjustment"]["consensus_adjustment"] == 10.0
    assert result["forecast_gbp_mwh"]["ridge_consensus"] == pytest.approx(
        forecast["forecast_gbp_mwh"]["ridge_delay_safe"] + 10,
    )
