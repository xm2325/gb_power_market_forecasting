from __future__ import annotations

import hashlib
import json
from pathlib import Path

from gb_power_market.forward_ledger_v25 import load_locked_ledger, verify_ledger_chain
from scripts.run_v25_2h_adaptive_candidate import _registry_latest


ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "reports/monitoring/V0_25_FORWARD_SNAPSHOT_REGISTRY.json"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_latest_registry_snapshot_is_13_row_append() -> None:
    latest = _registry_latest(REGISTRY)
    assert latest["sequence"] == 3
    assert latest["rows"] == 13
    assert latest["new_rows"] == 4
    assert latest["end_exclusive_utc"] == "2026-08-21T18:00:00Z"
    assert latest["ledger_chain_tip_sha256"] == (
        "5852d70b1a18acc0ff9ae46de71c372fc9d8878e8e2ecab8d2b2427dae997745"
    )


def test_latest_registered_files_match_digests_and_chain() -> None:
    latest = _registry_latest(REGISTRY)
    monitor = ROOT / latest["monitor_path"]
    ledger_path = ROOT / latest["ledger_path"]
    assert _sha256(monitor) == latest["monitor_sha256"]
    assert _sha256(ledger_path) == latest["ledger_sha256"]

    ledger = load_locked_ledger(ledger_path)
    verify_ledger_chain(ledger)
    assert len(ledger) == latest["rows"]
    assert ledger.iloc[-1]["chain_sha256"] == latest["ledger_chain_tip_sha256"]


def test_snapshot_registry_is_monotone_and_append_only() -> None:
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    assert registry["append_only"] is True
    snapshots = registry["snapshots"]
    assert [x["sequence"] for x in snapshots] == list(range(1, len(snapshots) + 1))
    assert [x["rows"] for x in snapshots] == sorted(x["rows"] for x in snapshots)
    assert all(b["rows"] > a["rows"] for a, b in zip(snapshots, snapshots[1:]))
    assert all(
        b["end_exclusive_utc"] > a["end_exclusive_utc"]
        for a, b in zip(snapshots, snapshots[1:])
    )
