from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from gb_power_market.confirmatory_v23 import (
    SEALED_CONFIRMATORY_END_EXCLUSIVE_UTC,
    SEALED_CONFIRMATORY_START_UTC,
    SealedConfirmatoryProtocol,
    assert_pre_reveal_payload_safe,
    evaluate_sealed_confirmatory,
    sealed_target_grid,
    sealed_target_grid_sha256,
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
    t = pd.date_range(SEALED_CONFIRMATORY_START_UTC, periods=n, freq="30min")
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


def test_sealed_grid_is_exactly_672_half_hours_and_hash_is_stable():
    grid = sealed_target_grid()
    assert len(grid) == 672
    assert grid[0] == SEALED_CONFIRMATORY_START_UTC
    assert grid[-1] + pd.Timedelta(minutes=30) == SEALED_CONFIRMATORY_END_EXCLUSIVE_UTC
    assert sealed_target_grid_sha256() == sealed_target_grid_sha256()


def test_pre_gate_output_is_label_value_invariant_and_recursive_safe():
    frame = _frame(100)
    end = SEALED_CONFIRMATORY_START_UTC + pd.Timedelta(minutes=30 * 100)
    a = evaluate_sealed_confirmatory(frame, frozen_state=_state(), available_end_exclusive_utc=end)
    mutated = frame.copy()
    mutated["reference_market_price_gbp_mwh"] = np.linspace(-5000.0, 5000.0, len(mutated))
    b = evaluate_sealed_confirmatory(mutated, frozen_state=_state(), available_end_exclusive_utc=end)
    assert a == b
    assert a["status"] == "SEALED_ACCUMULATION"
    assert a["sealed_window"]["complete_rows_so_far"] == 100
    assert a["grid_audit"]["missing_expected_rows"] == 0
    assert_pre_reveal_payload_safe(a)


def test_recursive_safety_rejects_nested_performance_key():
    with pytest.raises(ValueError, match="forbidden performance keys"):
        assert_pre_reveal_payload_safe({
            "status": "SEALED_ACCUMULATION",
            "safe": {"nested": {"model_mae_gbp_mwh": 1.0}},
        })


def test_duplicate_target_blocks_and_cannot_inflate_coverage():
    frame = _frame(20)
    frame = pd.concat([frame, frame.iloc[[5]]], ignore_index=True)
    end = SEALED_CONFIRMATORY_START_UTC + pd.Timedelta(minutes=30 * 20)
    result = evaluate_sealed_confirmatory(frame, frozen_state=_state(), available_end_exclusive_utc=end)
    assert result["status"] == "BLOCKED_EVIDENCE"
    assert result["grid_audit"]["duplicate_complete_rows"] == 2
    assert result["sealed_window"]["complete_rows_so_far"] == 20
    assert result["sealed_window"]["coverage_so_far"] == 1.0


def test_missing_target_uses_expected_grid_denominator():
    frame = _frame(100).drop(index=list(range(10))).reset_index(drop=True)
    end = SEALED_CONFIRMATORY_START_UTC + pd.Timedelta(minutes=30 * 100)
    result = evaluate_sealed_confirmatory(frame, frozen_state=_state(), available_end_exclusive_utc=end)
    assert result["status"] == "BLOCKED_EVIDENCE"
    assert result["grid_audit"]["missing_expected_rows"] == 10
    assert result["sealed_window"]["coverage_so_far"] == 0.9


def test_future_neso_publication_blocks_without_reveal():
    frame = _frame(40, family="PRICE_PLUS_NESO_LEVELS")
    frame.loc[5, "neso_publish_time_utc"] = frame.loc[5, "decision_time_utc"] + pd.Timedelta(minutes=1)
    end = SEALED_CONFIRMATORY_START_UTC + pd.Timedelta(minutes=30 * 40)
    result = evaluate_sealed_confirmatory(
        frame,
        frozen_state=_state("PRICE_PLUS_NESO_LEVELS"),
        available_end_exclusive_utc=end,
    )
    assert result["status"] == "BLOCKED_EVIDENCE"
    assert result["information_audit"]["future_neso_publications"] == 1
    assert "classification" not in result


def test_reveal_scores_only_fixed_672_row_grid():
    frame = _frame(700)
    result = evaluate_sealed_confirmatory(
        frame,
        frozen_state=_state(),
        available_end_exclusive_utc=SEALED_CONFIRMATORY_END_EXCLUSIVE_UTC + pd.Timedelta(days=2),
        protocol=SealedConfirmatoryProtocol(bootstrap_replicates=200),
    )
    assert result["status"] == "SEALED_CONFIRMATORY_REVEALED"
    assert result["scored_window"]["prospective_window"]["rows"] == 672
    assert result["scored_window"]["prospective_window"]["end_exclusive_utc"] == SEALED_CONFIRMATORY_END_EXCLUSIVE_UTC.isoformat()
    assert result["classification"]["status"] == "CONFIRMATORY_POSITIVE"
