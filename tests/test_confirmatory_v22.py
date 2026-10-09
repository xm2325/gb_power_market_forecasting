from __future__ import annotations

import numpy as np
import pandas as pd

from gb_power_market.confirmatory_v22 import (
    CONFIRMATORY_END_EXCLUSIVE_UTC,
    CONFIRMATORY_START_UTC,
    ConfirmatoryProtocol,
    evaluate_blinded_confirmatory,
)
from gb_power_market.price_feature_families import HISTORY_FEATURES, LEVEL_FEATURES
from gb_power_market.prospective_v21 import LOCKED_EVIDENCE_ID


def _state(family: str = "PRICE_HISTORY_ONLY") -> dict:
    features = list(HISTORY_FEATURES)
    horizon = 30
    if family == "PRICE_PLUS_NESO_LEVELS":
        features += list(LEVEL_FEATURES)
        horizon = 120
    return {
        "schema": "gb-power-market-frozen-ridge-v1",
        "source_evidence_id_sha256": LOCKED_EVIDENCE_ID,
        "horizon_minutes": horizon,
        "selected_family": family,
        "features": features,
        "alpha": 1.0,
        "mean": [0.0] * len(features),
        "scale": [1.0] * len(features),
        "coef": [50.0] + [0.0] * len(features),
        "conformal_absolute_residual_quantile_gbp_mwh": 10.0,
    }


def _frame(n: int, *, family: str = "PRICE_HISTORY_ONLY") -> pd.DataFrame:
    t = pd.date_range(CONFIRMATORY_START_UTC, periods=n, freq="30min")
    horizon = 30 if family == "PRICE_HISTORY_ONLY" else 120
    out = pd.DataFrame({
        "target_start_utc": t,
        "decision_time_utc": t - pd.Timedelta(minutes=horizon),
        "reference_market_price_gbp_mwh": np.full(n, 50.0),
        "price_lag_1d_same_target": np.full(n, 70.0),
        "price_lag_last_completed": np.full(n, 49.0),
    })
    for i, c in enumerate(HISTORY_FEATURES):
        out[c] = 0.1 * (i + 1)
    if family == "PRICE_PLUS_NESO_LEVELS":
        for i, c in enumerate(LEVEL_FEATURES):
            out[c] = 100.0 + i
        out["neso_publish_time_utc"] = out["decision_time_utc"] - pd.Timedelta(minutes=15)
    return out


def test_pre_gate_output_is_blinded_and_label_value_invariant():
    frame = _frame(100)
    end = CONFIRMATORY_START_UTC + pd.Timedelta(minutes=30 * 100)
    a = evaluate_blinded_confirmatory(frame, frozen_state=_state(), available_end_exclusive_utc=end)
    mutated = frame.copy()
    mutated["reference_market_price_gbp_mwh"] = np.linspace(-5000.0, 5000.0, len(mutated))
    b = evaluate_blinded_confirmatory(mutated, frozen_state=_state(), available_end_exclusive_utc=end)
    assert a == b
    assert a["status"] == "BLINDED_ACCUMULATION"
    forbidden = {"reference", "frozen_model", "interval", "abstention", "daily_block_bootstrap", "classification"}
    assert forbidden.isdisjoint(a)


def test_reveal_is_fixed_to_exact_672_half_hours():
    frame = _frame(700)
    result = evaluate_blinded_confirmatory(
        frame,
        frozen_state=_state(),
        available_end_exclusive_utc=CONFIRMATORY_END_EXCLUSIVE_UTC + pd.Timedelta(days=3),
        protocol=ConfirmatoryProtocol(bootstrap_replicates=200),
    )
    assert result["status"] == "CONFIRMATORY_REVEALED"
    assert result["scored_window"]["prospective_window"]["rows"] == 672
    assert result["scored_window"]["prospective_window"]["end_exclusive_utc"] == CONFIRMATORY_END_EXCLUSIVE_UTC.isoformat()
    assert result["classification"]["status"] == "CONFIRMATORY_POSITIVE"


def test_future_neso_publication_blocks_without_revealing_performance():
    frame = _frame(40, family="PRICE_PLUS_NESO_LEVELS")
    frame.loc[5, "neso_publish_time_utc"] = frame.loc[5, "decision_time_utc"] + pd.Timedelta(minutes=1)
    end = CONFIRMATORY_START_UTC + pd.Timedelta(minutes=30 * 40)
    result = evaluate_blinded_confirmatory(
        frame,
        frozen_state=_state("PRICE_PLUS_NESO_LEVELS"),
        available_end_exclusive_utc=end,
    )
    assert result["status"] == "BLOCKED_EVIDENCE"
    assert result["information_audit"]["future_neso_publications"] == 1
    assert "frozen_model" not in result


def test_coverage_failure_stays_blinded():
    frame = _frame(100).drop(index=[10, 11, 12, 13, 14, 15]).reset_index(drop=True)
    end = CONFIRMATORY_START_UTC + pd.Timedelta(minutes=30 * 100)
    result = evaluate_blinded_confirmatory(frame, frozen_state=_state(), available_end_exclusive_utc=end)
    assert result["status"] == "BLOCKED_EVIDENCE"
    assert result["confirmatory_window"]["coverage_so_far"] < 0.95
    assert "classification" not in result
