import pandas as pd
import pytest

from scripts.download_elexon_mid_exact_window import (
    chunk_windows,
    query_params,
    validate_payload_window,
)


def test_exact_window_uses_datetime_filters_without_settlement_period_parameters() -> None:
    start = pd.Timestamp("2026-08-24T00:00:00Z")
    end = pd.Timestamp("2026-08-24T22:00:00Z")
    params = query_params(start, end)

    assert params == {
        "from": "2026-08-24T00:00:00Z",
        "to": "2026-08-24T21:30:00Z",
        "format": "json",
    }
    assert "settlementPeriodFrom" not in params
    assert "settlementPeriodTo" not in params


def test_chunk_windows_preserve_exact_final_cutoff() -> None:
    start = pd.Timestamp("2026-08-23T00:00:00Z")
    end = pd.Timestamp("2026-08-24T22:00:00Z")
    chunks = chunk_windows(start, end)

    assert chunks[-1] == (
        pd.Timestamp("2026-08-24T00:00:00Z"),
        pd.Timestamp("2026-08-24T22:00:00Z"),
    )
    assert query_params(*chunks[-1])["to"] == "2026-08-24T21:30:00Z"


def test_payload_rejects_any_row_at_or_after_sealed_end() -> None:
    start = pd.Timestamp("2026-08-24T00:00:00Z")
    end = pd.Timestamp("2026-08-24T22:00:00Z")
    valid = {"data": [{"startTime": "2026-08-24T21:30:00Z"}]}
    invalid = {"data": [{"startTime": "2026-08-24T22:00:00Z"}]}

    assert validate_payload_window(valid, start=start, end_exclusive=end) == 1
    with pytest.raises(ValueError, match="escaped sealed window"):
        validate_payload_window(invalid, start=start, end_exclusive=end)


def test_exact_boundaries_must_be_half_hour_aligned() -> None:
    with pytest.raises(ValueError, match="30-minute UTC grid"):
        chunk_windows(
            pd.Timestamp("2026-08-24T00:05:00Z"),
            pd.Timestamp("2026-08-24T22:00:00Z"),
        )
