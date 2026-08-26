from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd

from gb_power_market.forward_ledger_v25 import load_locked_ledger, verify_ledger_chain
from scripts.run_v25_2h_adaptive_candidate import _registry_latest


ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "reports/monitoring/V0_25_FORWARD_SNAPSHOT_REGISTRY.json"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_latest_registry_snapshot_strictly_extends_predecessor() -> None:
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    snapshots = registry["snapshots"]
    assert len(snapshots) >= 2
    previous, latest = snapshots[-2], snapshots[-1]

    assert latest["sequence"] == previous["sequence"] + 1
    assert latest["rows"] > previous["rows"]
    assert latest["new_rows"] == latest["rows"] - previous["rows"]
    assert pd.Timestamp(latest["end_exclusive_utc"]) > pd.Timestamp(previous["end_exclusive_utc"])

    previous_ledger = load_locked_ledger(ROOT / previous["ledger_path"])
    latest_ledger = load_locked_ledger(ROOT / latest["ledger_path"])
    verify_ledger_chain(previous_ledger)
    verify_ledger_chain(latest_ledger)
    assert len(previous_ledger) == previous["rows"]
    assert len(latest_ledger) == latest["rows"]
    assert (
        latest_ledger.iloc[: len(previous_ledger)]["row_sha256"].reset_index(drop=True)
        == previous_ledger["row_sha256"].reset_index(drop=True)
    ).all()
    assert (
        latest_ledger.iloc[: len(previous_ledger)]["chain_sha256"].reset_index(drop=True)
        == previous_ledger["chain_sha256"].reset_index(drop=True)
    ).all()


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
    assert all(b["rows"] > a["rows"] for a, b in zip(snapshots, snapshots[1:]))
    assert all(
        pd.Timestamp(b["end_exclusive_utc"]) > pd.Timestamp(a["end_exclusive_utc"])
        for a, b in zip(snapshots, snapshots[1:])
    )
