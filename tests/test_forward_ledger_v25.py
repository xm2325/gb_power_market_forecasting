import pandas as pd

from gb_power_market.forward_ledger_v25 import (
    LEDGER_SEED_SHA256,
    build_forward_ledger,
    verify_ledger_chain,
    verify_locked_prefix,
)


def _rows(n: int = 8) -> pd.DataFrame:
    target = pd.date_range("2026-08-21T11:30:00Z", periods=n, freq="30min")
    return pd.DataFrame({
        "target_start_utc": target,
        "decision_time_utc": target - pd.Timedelta(minutes=120),
        "realised_price_gbp_mwh": [100.0 + i for i in range(n)],
        "frozen_prediction_gbp_mwh": [90.0 + i for i in range(n)],
        "previous_settlement_day_reference_gbp_mwh": [98.0 + i for i in range(n)],
        "bias_correction_gbp_mwh": [8.5 for _ in range(n)],
        "bias_history_rows": [96 for _ in range(n)],
        "bias_history_latest_target_utc": target - pd.Timedelta(minutes=150),
        "adaptive_prediction_gbp_mwh": [98.5 + i for i in range(n)],
    })


def test_forward_ledger_is_deterministic_and_chained():
    a = build_forward_ledger(_rows(), forward_start_utc="2026-08-21T11:30:00Z")
    b = build_forward_ledger(_rows(), forward_start_utc="2026-08-21T11:30:00Z")
    pd.testing.assert_frame_equal(a, b)
    assert len(a) == 8
    assert a.iloc[0]["chain_sha256"] != LEDGER_SEED_SHA256
    verify_ledger_chain(a)


def test_appended_rows_preserve_locked_prefix():
    full = build_forward_ledger(_rows(10), forward_start_utc="2026-08-21T11:30:00Z")
    locked = full.iloc[:6].copy()
    result = verify_locked_prefix(full, locked)
    assert result["status"] == "LOCKED_PREFIX_REPRODUCED"
    assert result["locked_rows"] == 6
    assert result["current_rows"] == 10
    assert result["new_rows_after_locked_prefix"] == 4


def test_changed_historical_value_fails_prefix_check():
    locked = build_forward_ledger(_rows(6), forward_start_utc="2026-08-21T11:30:00Z")
    changed = _rows(8)
    changed.loc[2, "realised_price_gbp_mwh"] = 999.0
    current = build_forward_ledger(changed, forward_start_utc="2026-08-21T11:30:00Z")
    try:
        verify_locked_prefix(current, locked)
    except ValueError as exc:
        assert "changed locked forward row" in str(exc)
    else:
        raise AssertionError("expected changed historical row to fail closed")


def test_tampered_locked_digest_fails_chain_validation():
    locked = build_forward_ledger(_rows(6), forward_start_utc="2026-08-21T11:30:00Z")
    locked.loc[1, "frozen_prediction_gbp_mwh"] = "123.000000000"
    try:
        verify_ledger_chain(locked)
    except ValueError as exc:
        assert "row digest mismatch" in str(exc)
    else:
        raise AssertionError("expected tampered ledger to fail")


def test_shorter_replay_fails_closed():
    locked = build_forward_ledger(_rows(6), forward_start_utc="2026-08-21T11:30:00Z")
    current = build_forward_ledger(_rows(5), forward_start_utc="2026-08-21T11:30:00Z")
    try:
        verify_locked_prefix(current, locked)
    except ValueError as exc:
        assert "shorter than locked prefix" in str(exc)
    else:
        raise AssertionError("expected shorter replay to fail")
