import hashlib
import json
from pathlib import Path

import pandas as pd

from gb_power_market.forward_ledger_v25 import verify_ledger_chain


REGISTRY = Path("reports/monitoring/V0_25_FORWARD_SNAPSHOT_REGISTRY.json")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_v25_snapshot_registry_is_monotonic_and_content_addressed():
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    assert registry["schema"] == "gb-power-market-v25-forward-snapshot-registry-v1"
    assert registry["append_only"] is True
    snapshots = registry["snapshots"]
    assert len(snapshots) >= 2

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

        monitor_path = Path(snap["monitor_path"])
        ledger_path = Path(snap["ledger_path"])
        assert _sha256(monitor_path) == snap["monitor_sha256"]
        assert _sha256(ledger_path) == snap["ledger_sha256"]

        monitor = json.loads(monitor_path.read_text(encoding="utf-8"))
        assert monitor["maturity_stage"] == snap["maturity_stage"]
        monitor_rows = monitor.get("cumulative", {}).get("rows")
        if monitor_rows is None:
            monitor_rows = monitor["first_new_forward_segment"]["rows"]
        assert monitor_rows == snap["rows"]

        ledger = pd.read_csv(ledger_path, dtype=str, keep_default_na=False)
        verify_ledger_chain(ledger)
        assert len(ledger) == snap["rows"]
        assert ledger.iloc[-1]["chain_sha256"] == snap["ledger_chain_tip_sha256"]

        if previous_ledger is not None:
            assert len(ledger) > len(previous_ledger)
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
