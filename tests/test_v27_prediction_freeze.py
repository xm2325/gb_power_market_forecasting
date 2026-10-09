import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from gb_power_market.elexon_v19 import expected_settlement_keys
from gb_power_market.v27_prediction_freeze import (
    build_first_frozen_target_row,
    freeze_first_prediction,
    verify_freeze_window,
)


def _lock(target: str = "2026-08-19T02:30:00Z") -> dict:
    target_ts = pd.Timestamp(target)
    decision = target_ts - pd.Timedelta(hours=2)
    return {
        "schema": "gb-power-market-v27-forward-implementation-lock-v1",
        "status": "FRESH_FORWARD_CANDIDATE_LOCKED_NOT_YET_EVALUATED",
        "version": "0.27.0",
        "candidate": "2H_FROZEN_PLUS_CAUSAL_6H_48H_CONSENSUS_WITH_FROZEN_DIRECTION_VETO",
        "candidate_source": {"git_blob_sha1": "3c361dbb0e1665bbbad2e1097b8580ce062a203f"},
        "first_forward_decision_time_utc": decision.isoformat(),
        "forward_start_utc": target_ts.isoformat(),
        "forward_evidence_rows_at_lock": 0,
    }


def test_freeze_window_opens_at_decision_and_closes_at_target() -> None:
    lock = _lock()
    with pytest.raises(RuntimeError, match="FIRST_DECISION_NOT_REACHED"):
        verify_freeze_window(implementation_lock=lock, now_utc="2026-08-19T00:29:59Z")
    opened = verify_freeze_window(implementation_lock=lock, now_utc="2026-08-19T00:30:00Z")
    assert opened["decision_time_utc"] == "2026-08-19T00:30:00+00:00"
    with pytest.raises(RuntimeError, match="FIRST_TARGET_ALREADY_STARTED"):
        verify_freeze_window(implementation_lock=lock, now_utc="2026-08-19T02:30:00Z")


def test_build_first_frozen_target_row_uses_only_causal_price_and_neso_history() -> None:
    lock = _lock()
    keys = expected_settlement_keys("2026-08-10", "2026-08-20")
    keys["target_start_utc"] = pd.to_datetime(keys["target_start_utc"], utc=True)
    end = pd.Timestamp("2026-08-19T00:00:00Z")
    ref = keys[keys["target_start_utc"] <= end][
        ["target_start_utc", "settlement_date", "settlement_period"]
    ].copy()
    idx = np.arange(len(ref), dtype=float)
    ref["reference_market_price_gbp_mwh"] = 70.0 + 5.0 * np.sin(idx / 7.0) + idx * 0.002

    target_end = pd.Timestamp(lock["forward_start_utc"]) + pd.Timedelta(minutes=30)
    neso = pd.DataFrame(
        [
            {
                "target_end_utc": target_end,
                "publish_time_utc": pd.Timestamp("2026-08-19T00:10:00Z"),
                "wind_mw": 2100.0,
                "wind_capacity_mw": 6600.0,
                "solar_mw": 500.0,
                "solar_capacity_mw": 22000.0,
                "source_regime": "current",
            },
            {
                "target_end_utc": target_end,
                "publish_time_utc": pd.Timestamp("2026-08-19T00:45:00Z"),
                "wind_mw": 9999.0,
                "wind_capacity_mw": 9999.0,
                "solar_mw": 9999.0,
                "solar_capacity_mw": 9999.0,
                "source_regime": "future_should_be_excluded",
            },
        ]
    )
    model_bundle = json.loads(Path("reports/locked/V0_21_FROZEN_MODEL_STATE.json").read_text())
    row = build_first_frozen_target_row(
        reference_history=ref,
        neso_current=neso,
        model_bundle=model_bundle,
        implementation_lock=lock,
    )

    assert row["target_start_utc"] == "2026-08-19T02:30:00+00:00"
    assert row["decision_time_utc"] == "2026-08-19T00:30:00+00:00"
    assert pd.isna(row["realised_price_gbp_mwh"])
    assert row["neso_publish_time_utc"] == "2026-08-19T00:10:00+00:00"
    assert np.isfinite(row["frozen_prediction_gbp_mwh"])
    assert np.isfinite(row["previous_settlement_day_reference_gbp_mwh"])


def test_first_prediction_record_contains_no_realised_target() -> None:
    lock = _lock()
    target = pd.Timestamp(lock["forward_start_utc"])
    times = pd.date_range(target - pd.Timedelta(hours=50), target - pd.Timedelta(hours=2, minutes=30), freq="30min")
    frozen = 80.0 + np.linspace(-3.0, 3.0, len(times))
    realised = frozen + 2.0
    history = pd.DataFrame(
        {
            "target_start_utc": times,
            "decision_time_utc": times - pd.Timedelta(hours=2),
            "realised_price_gbp_mwh": realised,
            "frozen_prediction_gbp_mwh": frozen,
            "previous_settlement_day_reference_gbp_mwh": frozen - 1.0,
            "last_completed_price_gbp_mwh": frozen - 0.5,
            "interval_lower_gbp_mwh": frozen - 20.0,
            "interval_upper_gbp_mwh": frozen + 20.0,
        }
    )
    first = {
        "target_start_utc": target.isoformat(),
        "decision_time_utc": (target - pd.Timedelta(hours=2)).isoformat(),
        "realised_price_gbp_mwh": np.nan,
        "frozen_prediction_gbp_mwh": 84.0,
        "previous_settlement_day_reference_gbp_mwh": 79.0,
        "last_completed_price_gbp_mwh": 82.0,
        "interval_lower_gbp_mwh": 64.0,
        "interval_upper_gbp_mwh": 104.0,
        "neso_publish_time_utc": "2026-08-19T00:10:00+00:00",
        "neso_forecast_age_minutes": 20.0,
    }
    record = freeze_first_prediction(
        historical_frozen_rows=history,
        first_target_row=first,
        implementation_lock=lock,
    )
    assert record["status"] == "PREDICTION_FROZEN_BEFORE_TARGET_OUTCOME"
    assert record["target_label_status"] == "UNOBSERVED_NOT_ACCESSED"
    assert record["realised_price_in_prediction_record"] is False
    assert "realised_price_gbp_mwh" not in record
    assert np.isfinite(record["v27_prediction_gbp_mwh"])
