from __future__ import annotations

import json
import numpy as np
import pandas as pd
import pytest

from gb_power_market.elexon_v19 import expected_settlement_keys
from gb_power_market.prospective_v28 import (
    market_end_for_decision, predict_shadow, score_shadow, summarise_scores,
    target_after, write_json_new,
)


def _fixture(now: str = "2026-08-13T13:11:00Z", days: int = 14):
    decision = pd.Timestamp(now)
    cutoff = market_end_for_decision(decision)
    local_first = (cutoff - pd.Timedelta(days=days)).date().isoformat()
    local_last = (cutoff + pd.Timedelta(days=2)).date().isoformat()
    keys = expected_settlement_keys(local_first, local_last)
    keys["target_start_utc"] = pd.to_datetime(keys["target_start_utc"], utc=True)
    frame = keys[keys["target_start_utc"] < cutoff].copy()
    i = np.arange(len(frame))
    frame["reference_market_price_gbp_mwh"] = 60.0 + 0.03 * i + 5.0 * np.cos(i * np.pi / 24)
    return frame, decision, cutoff


def test_cutoff_uses_settlement_end_plus_buffer():
    now = pd.Timestamp("2026-08-13T13:11:00Z")
    cutoff = market_end_for_decision(now)
    assert cutoff == pd.Timestamp("2026-08-13T11:30:00Z")
    assert cutoff - pd.Timedelta(minutes=30) + pd.Timedelta(minutes=120) <= now
    with pytest.raises(ValueError):
        market_end_for_decision(now, delay_minutes=15)


def test_target_real_lead_is_not_misrepresented_as_exact_2h():
    decision = pd.Timestamp("2026-08-13T13:11:00Z")
    target = target_after(decision)
    assert target == pd.Timestamp("2026-08-13T15:30:00Z")
    assert (target - decision).total_seconds() / 60 == 139


def test_shadow_prediction_is_label_free_and_has_three_comparators():
    frame, now, cutoff = _fixture()
    result = predict_shadow(frame, decision=now, input_end_exclusive=cutoff)
    assert result["evidence_class"] == "PRETARGET_SHADOW_FORECAST_NO_REALIZED_TARGET"
    assert result["target_outcome_accessed"] is False
    assert set(result["forecast_gbp_mwh"]) == {"previous_day", "consensus", "direction_veto"}
    assert result["effective_lead_minutes"] >= 120
    assert "realised_price_gbp_mwh" not in result
    assert result["diagnostic"]["long_history_rows"] >= 24


def test_future_label_mutation_cannot_change_prediction():
    frame, now, cutoff = _fixture()
    a = predict_shadow(frame, decision=now, input_end_exclusive=cutoff)
    extra = frame.iloc[-1:].copy()
    future = pd.Timestamp(a["target_start_utc"])
    extra["target_start_utc"] = future
    future_keys = expected_settlement_keys("2026-08-13", "2026-08-15")
    actual_key = future_keys[pd.to_datetime(future_keys["target_start_utc"], utc=True) == future].iloc[0]
    extra["settlement_date"] = actual_key["settlement_date"]
    extra["settlement_period"] = actual_key["settlement_period"]
    extra["reference_market_price_gbp_mwh"] = 100000.0
    with pytest.raises(ValueError, match="cutoff"):
        predict_shadow(pd.concat([frame, extra]), decision=now, input_end_exclusive=cutoff)
    b = predict_shadow(frame.copy(), decision=now, input_end_exclusive=cutoff)
    assert a["forecast_gbp_mwh"] == b["forecast_gbp_mwh"]


def test_missing_source_grid_row_fails_closed():
    frame, now, cutoff = _fixture()
    lost = frame[frame["target_start_utc"] != cutoff - pd.Timedelta(hours=4)]
    with pytest.raises(ValueError, match="gaps"):
        predict_shadow(lost, decision=now, input_end_exclusive=cutoff)


def test_too_recent_source_cutoff_fails_closed():
    frame, now, cutoff = _fixture()
    with pytest.raises(ValueError, match="cutoff"):
        predict_shadow(frame, decision=now,
                       input_end_exclusive=cutoff + pd.Timedelta(minutes=30))


def test_scoring_requires_mature_outcome_and_never_promotes():
    frame, now, cutoff = _fixture()
    forecast = predict_shadow(frame, decision=now, input_end_exclusive=cutoff)
    target = pd.Timestamp(forecast["target_start_utc"])
    with pytest.raises(ValueError, match="maturity"):
        score_shadow(forecast, observed_price=100., scored_at=target)
    result = score_shadow(
        forecast, observed_price=100.,
        scored_at=target + pd.Timedelta(minutes=120),
    )
    assert result["automatic_promotion"] is False
    assert result["absolute_error_gbp_mwh"]["previous_day"] >= 0
    summary = summarise_scores([result])
    assert summary["review_mature"] is False
    assert summary["all"]["rows"] == 1
    assert not summary["alerts"]


def test_immutable_prediction_and_score_files(tmp_path):
    path = tmp_path / "predictions" / "once.json"
    write_json_new(path, {"version": 1})
    with pytest.raises(FileExistsError):
        write_json_new(path, {"version": 2})
    assert json.loads(path.read_text()) == {"version": 1}


def test_duplicate_scoring_rejected():
    frame, now, cutoff = _fixture()
    forecast = predict_shadow(frame, decision=now, input_end_exclusive=cutoff)
    target = pd.Timestamp(forecast["target_start_utc"])
    score = score_shadow(forecast, observed_price=100., scored_at=target + pd.Timedelta(hours=3))
    with pytest.raises(ValueError, match="duplicate"):
        summarise_scores([score, score])


def test_extended_metrics_and_day_block_uncertainty():
    frame, now, cutoff = _fixture()
    forecast = predict_shadow(frame, decision=now, input_end_exclusive=cutoff)
    target = pd.Timestamp(forecast["target_start_utc"])
    initial = score_shadow(
        forecast, observed_price=100.,
        scored_at=target + pd.Timedelta(hours=3),
    )
    assert "signed_error_gbp_mwh" in initial
    single = summarise_scores([initial])
    assert single["all"]["p95_abs_error_gbp_mwh"]["previous_day"] >= 0
    assert "signed_bias_gbp_mwh" in single["all"]
    assert single["daily_block_uncertainty"]["consensus"] is None

    # Deterministic synthetic unit-test scores, not a reported market result.
    sample = []
    for i in range(672):
        row = dict(initial)
        row["target_start_utc"] = (target + pd.Timedelta(minutes=30 * i)).isoformat()
        sample.append(row)
    summary = summarise_scores(sample)
    assert summary["review_mature"] is True
    assert summary["all"]["rows"] == 672
    assert summary["daily_block_uncertainty"]["consensus"]["blocks"] >= 14
    assert len(summary["daily_block_uncertainty"]["direction_veto"]["interval95_gbp_mwh"]) == 2
    assert summary["automatic_promotion"] is False
