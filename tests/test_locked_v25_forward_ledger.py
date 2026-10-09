import hashlib
from pathlib import Path

import pandas as pd

from gb_power_market.forward_ledger_v25 import verify_ledger_chain


LEDGER_PATH = Path("reports/monitoring/V0_25_FORWARD_LEDGER_FIRST6.csv")
EXPECTED_FILE_SHA256 = "e0fceb2d576a9f7e4e1e29bdaec4578af85d9a725ff05420f2e572d45e3d9657"
EXPECTED_CHAIN_TIP_SHA256 = "b27a99b21466c8a4cbf58d29ad9c980a174b278cee1a741582a978af747789f2"
EXPECTED_ROWS = 6
EXPECTED_FIRST_TARGET = "2026-08-21T11:30:00Z"
EXPECTED_LAST_TARGET = "2026-08-21T14:00:00Z"


def test_first_v25_forward_ledger_is_immutable():
    raw = LEDGER_PATH.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == EXPECTED_FILE_SHA256

    ledger = pd.read_csv(LEDGER_PATH, dtype=str, keep_default_na=False)
    verify_ledger_chain(ledger)
    assert len(ledger) == EXPECTED_ROWS
    assert ledger.iloc[0]["target_start_utc"] == EXPECTED_FIRST_TARGET
    assert ledger.iloc[-1]["target_start_utc"] == EXPECTED_LAST_TARGET
    assert ledger.iloc[-1]["chain_sha256"] == EXPECTED_CHAIN_TIP_SHA256
