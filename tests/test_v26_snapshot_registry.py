import hashlib
import json
from pathlib import Path

import pandas as pd

from gb_power_market.forward_ledger_v26 import verify_v26_ledger_chain


REGISTRY = Path("reports/monitoring/V0_26_FORWARD_SNAPSHOT_REGISTRY.json")
GENESIS_ROWS = 2
GENESIS_CHAIN_TIP = "49cc9148d1756ff1fce3bdcac5f8f9405850cf516b0c701215e81121a7677f9d"
CANDIDATE = "2H_FROZEN_PLUS_CAUSAL_6H_48H_CONSENSUS_CLIPPED_RESIDUAL"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_v26_snapshot_registry_is_monotonic_and_content_addressed() -> None:
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    assert registry["schema"] == "gb-power-market-v26-forward-snapshot-registry-v1"
    assert registry["candidate"] == CANDIDATE
    assert registry["forward_start_utc"] == "2026-08-22T20:30:00Z"
    assert registry["append_only"] is True

    snapshots = registry["snapshots"]
    assert snapshots
    previous_ledger = None
    previous_rows = 0
    previous_end = None

    for expected_sequence, snap in enumerate(snapshots, start=1):
        assert snap["sequence"] == expected_sequence
        assert snap["rows"] > previous_rows
        assert snap["new_rows"] == snap["rows"] - previous_rows

        end = pd.Timestamp(snap["end_exclusive_utc"])
        assert end.tzinfo is not None
        if previous_end is not None:
            assert end > previous_end

        ledger_path = Path(snap["ledger_path"])
        checkpoint_path = Path(snap["checkpoint_path"])
        assert checkpoint_path.exists()
        assert _sha256(ledger_path) == snap["ledger_sha256"]

        ledger = pd.read_csv(ledger_path, dtype=str, keep_default_na=False)
        verify_v26_ledger_chain(ledger)
        assert len(ledger) == snap["rows"]
        assert ledger.iloc[-1]["chain_sha256"] == snap["ledger_chain_tip_sha256"]

        if previous_ledger is not None:
            assert (
                ledger.iloc[: len(previous_ledger)]["row_sha256"].reset_index(drop=True)
                == previous_ledger["row_sha256"].reset_index(drop=True)
            ).all()
            assert (
                ledger.iloc[: len(previous_ledger)]["chain_sha256"].reset_index(drop=True)
                == previous_ledger["chain_sha256"].reset_index(drop=True)
            ).all()

        previous_ledger = ledger
        previous_rows = snap["rows"]
        previous_end = end

    genesis = pd.read_csv(snapshots[0]["ledger_path"], dtype=str, keep_default_na=False)
    assert len(genesis) == GENESIS_ROWS
    assert genesis.iloc[-1]["chain_sha256"] == GENESIS_CHAIN_TIP
