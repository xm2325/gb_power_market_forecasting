from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from gb_power_market.adaptive_consensus_v26 import (
    V26_CANDIDATE_ID,
    V26_FORWARD_START_UTC,
    apply_causal_consensus_correction,
    candidate_spec,
)


def _rows(n: int = 180) -> pd.DataFrame:
    target = pd.date_range("2026-07-20T00:00:00Z", periods=n, freq="30min")
    frozen = np.full(n, 100.0)
    realised = np.full(n, 110.0)
    return pd.DataFrame(
        {
            "target_start_utc": target,
            "decision_time_utc": target - pd.Timedelta(minutes=120),
            "realised_price_gbp_mwh": realised,
            "frozen_prediction_gbp_mwh": frozen,
            "previous_settlement_day_reference_gbp_mwh": np.full(n, 95.0),
            "interval_lower_gbp_mwh": np.full(n, 80.0),
            "interval_upper_gbp_mwh": np.full(n, 120.0),
        }
    )


def test_v26_candidate_identity_and_forward_boundary_are_frozen() -> None:
    spec = candidate_spec()
    assert spec["version"] == "0.26.0"
    assert spec["candidate"] == V26_CANDIDATE_ID
    assert spec["forward_start_utc"] == V26_FORWARD_START_UTC.isoformat()
    assert spec["rule"]["short_lookback_hours"] == 6
    assert spec["rule"]["long_lookback_hours"] == 48


def test_v26_current_and_unavailable_labels_cannot_change_own_correction() -> None:
    rows = _rows()
    i = 150
    first = apply_causal_consensus_correction(rows)
    decision = pd.Timestamp(rows.loc[i, "decision_time_utc"])

    attacked = rows.copy()
    target = pd.to_datetime(attacked["target_start_utc"], utc=True)
    unavailable = target + pd.Timedelta(minutes=30) > decision
    attacked.loc[unavailable, "realised_price_gbp_mwh"] += 5000.0
    second = apply_causal_consensus_correction(attacked)

    assert first.loc[i, "v26_correction_gbp_mwh"] == pytest.approx(
        second.loc[i, "v26_correction_gbp_mwh"]
    )
    assert first.loc[i, "v26_prediction_gbp_mwh"] == pytest.approx(
        second.loc[i, "v26_prediction_gbp_mwh"]
    )
    assert first.loc[i, "v26_history_latest_target_utc"] == second.loc[
        i, "v26_history_latest_target_utc"
    ]


def test_v26_regime_sign_disagreement_falls_back_to_frozen() -> None:
    rows = _rows()
    i = 150
    # For target i, the eligible 6h residual window is i-16 .. i-5 inclusive.
    rows.loc[i - 16 : i - 5, "realised_price_gbp_mwh"] = 95.0
    out = apply_causal_consensus_correction(rows)

    assert out.loc[i, "v26_short_residual_mean_gbp_mwh"] < 0
    assert out.loc[i, "v26_long_residual_mean_gbp_mwh"] > 0
    assert out.loc[i, "v26_gate_reason"] == "REGIME_DISAGREEMENT_FALLBACK_FROZEN"
    assert out.loc[i, "v26_correction_gbp_mwh"] == pytest.approx(0.0)
    assert out.loc[i, "v26_prediction_gbp_mwh"] == pytest.approx(
        out.loc[i, "frozen_prediction_gbp_mwh"]
    )


def test_v26_consensus_correction_is_clipped_to_smaller_residual_mean() -> None:
    rows = _rows()
    i = 150
    rows.loc[i - 16 : i - 5, "realised_price_gbp_mwh"] = 102.0
    out = apply_causal_consensus_correction(rows)

    short = float(out.loc[i, "v26_short_residual_mean_gbp_mwh"])
    long = float(out.loc[i, "v26_long_residual_mean_gbp_mwh"])
    correction = float(out.loc[i, "v26_correction_gbp_mwh"])
    assert short > 0 and long > 0
    assert out.loc[i, "v26_gate_reason"] == "CONSENSUS_CLIPPED_CORRECTION"
    assert correction == pytest.approx(min(abs(short), abs(long)))
    assert correction <= abs(long) + 1e-12
    assert correction <= abs(short) + 1e-12


def test_v26_translates_frozen_interval_without_changing_width() -> None:
    out = apply_causal_consensus_correction(_rows())
    mature = out[out["v26_gate_reason"] == "CONSENSUS_CLIPPED_CORRECTION"].iloc[-1]
    assert mature["v26_interval_width_gbp_mwh"] == pytest.approx(40.0)
    assert (
        mature["v26_interval_upper_gbp_mwh"] - mature["v26_interval_lower_gbp_mwh"]
    ) == pytest.approx(40.0)
    assert mature["v26_interval_lower_gbp_mwh"] == pytest.approx(
        mature["interval_lower_gbp_mwh"] + mature["v26_correction_gbp_mwh"]
    )
