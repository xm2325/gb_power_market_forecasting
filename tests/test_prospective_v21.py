from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from gb_power_market.price_feature_families import HISTORY_FEATURES, LEVEL_FEATURES
from gb_power_market.price_forecasting import NumpyRidge
from gb_power_market.prospective_v21 import (
    LOCKED_EVIDENCE_ID,
    ProspectiveGate,
    model_from_frozen_state,
    score_prospective_shadow,
)


def _state(family: str = "PRICE_HISTORY_ONLY") -> dict:
    features = list(HISTORY_FEATURES)
    if family == "PRICE_PLUS_NESO_LEVELS":
        features += list(LEVEL_FEATURES)
    return {
        "schema": "gb-power-market-frozen-ridge-v1",
        "source_evidence_id_sha256": LOCKED_EVIDENCE_ID,
        "horizon_minutes": 30 if family == "PRICE_HISTORY_ONLY" else 120,
        "selected_family": family,
        "features": features,
        "alpha": 1.0,
        "mean": [0.0] * len(features),
        "scale": [1.0] * len(features),
        "coef": [50.0] + [0.0] * len(features),
        "conformal_absolute_residual_quantile_gbp_mwh": 10.0,
    }


def _frame(n: int, *, family: str = "PRICE_HISTORY_ONLY", start: str = "2026-08-15T07:30:00Z") -> pd.DataFrame:
    t = pd.date_range(start, periods=n, freq="30min")
    out = pd.DataFrame({
        "target_start_utc": t,
        "decision_time_utc": t - pd.Timedelta(minutes=30 if family == "PRICE_HISTORY_ONLY" else 120),
        "reference_market_price_gbp_mwh": np.linspace(45.0, 55.0, n),
        "price_lag_1d_same_target": np.full(n, 52.0),
        "price_lag_last_completed": np.full(n, 49.0),
    })
    features = list(HISTORY_FEATURES)
    for i, c in enumerate(features):
        out[c] = 0.1 * (i + 1)
    if family == "PRICE_PLUS_NESO_LEVELS":
        for i, c in enumerate(LEVEL_FEATURES):
            out[c] = 100.0 + i
        out["neso_publish_time_utc"] = out["decision_time_utc"] - pd.Timedelta(minutes=15)
    return out


def test_frozen_state_roundtrip_prediction():
    rng = np.random.default_rng(7)
    x = rng.normal(size=(50, len(HISTORY_FEATURES)))
    y = 20.0 + x[:, 0] * 3.0 - x[:, 1] * 2.0
    fitted = NumpyRidge(10.0).fit(x, y)
    state = _state()
    state["mean"] = fitted.mean_.tolist()
    state["scale"] = fitted.scale_.tolist()
    state["coef"] = fitted.coef_.tolist()
    restored = model_from_frozen_state(state)
    assert np.allclose(fitted.predict(x), restored.predict(x))


def test_prospective_shadow_refuses_locked_window_start():
    frame = _frame(10, start="2026-08-15T07:30:00Z")
    with pytest.raises(ValueError, match="locked v0.20 final window"):
        score_prospective_shadow(
            frame,
            frozen_state=_state(),
            start_utc="2026-08-15T07:00:00Z",
            end_exclusive_utc="2026-08-15T12:30:00Z",
        )


def test_short_prospective_window_is_shadow_only():
    frame = _frame(100)
    result = score_prospective_shadow(
        frame,
        frozen_state=_state(),
        end_exclusive_utc="2026-08-17T09:30:00Z",
    )
    assert result["status"] == "SHADOW_ONLY"
    assert result["prospective_window"]["rows"] == 100
    assert result["prospective_window"]["coverage"] == 1.0


def test_future_neso_publication_blocks_levels_shadow():
    frame = _frame(20, family="PRICE_PLUS_NESO_LEVELS")
    frame.loc[3, "neso_publish_time_utc"] = frame.loc[3, "decision_time_utc"] + pd.Timedelta(minutes=1)
    result = score_prospective_shadow(
        frame,
        frozen_state=_state("PRICE_PLUS_NESO_LEVELS"),
        end_exclusive_utc="2026-08-15T17:30:00Z",
        gate=ProspectiveGate(minimum_rows=1),
    )
    assert result["status"] == "BLOCKED_EVIDENCE"
    assert result["information_audit"]["future_neso_publications"] == 1


def test_daily_block_bootstrap_unlocks_only_after_predeclared_days():
    # Start at UTC midnight so exactly seven complete UTC blocks are available.
    frame = _frame(7 * 48, start="2026-08-16T00:00:00Z")
    result = score_prospective_shadow(
        frame,
        frozen_state=_state(),
        start_utc="2026-08-16T00:00:00Z",
        end_exclusive_utc="2026-08-23T00:00:00Z",
        gate=ProspectiveGate(minimum_rows=1, bootstrap_replicates=200),
    )
    assert result["status"] == "PROSPECTIVE_EVIDENCE_READY"
    assert result["daily_block_bootstrap"]["status"] == "PASS"
    assert result["daily_block_bootstrap"]["complete_utc_days"] == 7
