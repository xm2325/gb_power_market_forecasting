from __future__ import annotations

import pandas as pd
import pytest

from gb_power_market.adaptive_consensus_v26 import apply_causal_consensus_correction
from gb_power_market.forward_ledger_v26 import (
    build_v26_forward_ledger,
    verify_v26_ledger_chain,
    verify_v26_locked_prefix,
)


def _corrected(n: int = 140) -> pd.DataFrame:
    target = pd.date_range("2026-08-20T00:00:00Z", periods=n, freq="30min")
    rows = pd.DataFrame(
        {
            "target_start_utc": target,
            "decision_time_utc": target - pd.Timedelta(hours=2),
            "realised_price_gbp_mwh": 110.0,
            "frozen_prediction_gbp_mwh": 100.0,
            "previous_settlement_day_reference_gbp_mwh": 90.0,
        }
    )
    return apply_causal_consensus_correction(rows)


def test_v26_ledger_is_deterministic_and_chain_valid() -> None:
    corrected = _corrected()
    first = build_v26_forward_ledger(corrected, forward_start_utc="2026-08-22T20:30:00Z")
    second = build_v26_forward_ledger(corrected, forward_start_utc="2026-08-22T20:30:00Z")
    pd.testing.assert_frame_equal(first, second)
    verify_v26_ledger_chain(first)


def test_v26_locked_prefix_must_reproduce_exact_rows() -> None:
    corrected = _corrected()
    current = build_v26_forward_ledger(corrected, forward_start_utc="2026-08-22T20:30:00Z")
    locked = current.head(3).copy()
    check = verify_v26_locked_prefix(current, locked)
    assert check["status"] == "LOCKED_PREFIX_REPRODUCED"
    assert check["locked_rows"] == 3

    tampered = locked.copy()
    tampered.loc[1, "v26_prediction_gbp_mwh"] = "999.000000000"
    with pytest.raises(ValueError):
        verify_v26_locked_prefix(current, tampered)
