import hashlib
import json
from pathlib import Path

import pandas as pd
import pytest

from gb_power_market.forward_ledger_v25 import build_forward_ledger
from scripts.lock_v25_forward_snapshot import EXPECTED_CANDIDATE, lock_snapshot


def _corrected_rows(n: int) -> pd.DataFrame:
    target = pd.date_range("2026-08-21T11:30:00Z", periods=n, freq="30min")
    return pd.DataFrame(
        {
            "target_start_utc": target,
            "decision_time_utc": target - pd.Timedelta(hours=2),
            "realised_price_gbp_mwh": [100.0 + i for i in range(n)],
            "frozen_prediction_gbp_mwh": [95.0 + i for i in range(n)],
            "previous_settlement_day_reference_gbp_mwh": [110.0 + i for i in range(n)],
            "bias_correction_gbp_mwh": [2.0 for _ in range(n)],
            "bias_history_rows": [48 for _ in range(n)],
            "bias_history_latest_target_utc": target - pd.Timedelta(hours=2, minutes=30),
            "adaptive_prediction_gbp_mwh": [97.0 + i for i in range(n)],
        }
    )


def _monitor(rows: int) -> dict:
    end = pd.Timestamp("2026-08-21T11:30:00Z") + pd.Timedelta(minutes=30 * rows)
    return {
        "version": "0.25.0",
        "candidate": EXPECTED_CANDIDATE,
        "maturity_stage": "EARLY_ONLY",
        "alert_status": "INSUFFICIENT_SAMPLE_FOR_ALERTS",
        "alerts": [],
        "cumulative": {
            "rows": rows,
            "end_exclusive_utc": end.isoformat(),
            "adaptive_mae_gbp_mwh": 3.0,
            "frozen_mae_gbp_mwh": 5.0,
            "reference_mae_gbp_mwh": 10.0,
            "adaptive_improvement_vs_reference_pct": 70.0,
            "adaptive_improvement_vs_frozen_pct": 40.0,
        },
        "rolling": {
            "last_24h": {"rows": rows, "status": "INSUFFICIENT_ROWS_NEED_48"}
        },
        "promotion_readiness": {"status": "NOT_ELIGIBLE_INSUFFICIENT_ROWS"},
    }


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fixture(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    monitoring = tmp_path / "reports" / "monitoring"
    docs = tmp_path / "docs"
    artifact = tmp_path / "artifact"
    monitoring.mkdir(parents=True)
    artifact.mkdir()

    prior_ledger = build_forward_ledger(
        _corrected_rows(1), forward_start_utc="2026-08-21T11:30:00Z"
    )
    prior_path = monitoring / "prior.csv"
    prior_ledger.to_csv(prior_path, index=False, lineterminator="\n")
    prior_monitor = monitoring / "prior.json"
    prior_monitor.write_text(json.dumps(_monitor(1), indent=2) + "\n", encoding="utf-8")

    registry = {
        "schema": "gb-power-market-v25-forward-snapshot-registry-v1",
        "candidate": EXPECTED_CANDIDATE,
        "forward_start_utc": "2026-08-21T11:30:00Z",
        "append_only": True,
        "snapshots": [
            {
                "sequence": 1,
                "end_exclusive_utc": "2026-08-21T12:00:00Z",
                "rows": 1,
                "new_rows": 1,
                "artifact_id": 1,
                "artifact_sha256": "a" * 64,
                "monitor_path": prior_monitor.as_posix(),
                "monitor_sha256": _sha(prior_monitor),
                "ledger_path": prior_path.as_posix(),
                "ledger_sha256": _sha(prior_path),
                "ledger_chain_tip_sha256": str(prior_ledger.iloc[-1]["chain_sha256"]),
                "maturity_stage": "EARLY_ONLY",
            }
        ],
        "contract": "test",
    }
    registry_path = monitoring / "registry.json"
    registry_path.write_text(json.dumps(registry, indent=2) + "\n", encoding="utf-8")

    current_ledger = build_forward_ledger(
        _corrected_rows(3), forward_start_utc="2026-08-21T11:30:00Z"
    )
    current_ledger.to_csv(artifact / "forward_ledger_2h.csv", index=False, lineterminator="\n")
    (artifact / "v25_monitor_state.json").write_text(
        json.dumps(_monitor(3), indent=2) + "\n", encoding="utf-8"
    )
    return artifact, registry_path, monitoring, docs


def test_lock_snapshot_appends_exact_content_and_registry(tmp_path: Path) -> None:
    artifact, registry_path, monitoring, docs = _fixture(tmp_path)
    result = lock_snapshot(
        artifact_dir=artifact,
        registry_path=registry_path,
        monitoring_dir=monitoring,
        docs_dir=docs,
        artifact_id=42,
        artifact_sha256="b" * 64,
        run_id=123,
    )
    assert result["status"] == "SNAPSHOT_LOCKED"
    assert result["sequence"] == 2
    assert result["rows"] == 3
    assert result["new_rows"] == 2

    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    latest = registry["snapshots"][-1]
    assert latest["rows"] == 3
    assert latest["new_rows"] == 2
    assert latest["artifact_id"] == 42
    assert latest["run_id"] == 123
    assert Path(latest["monitor_path"]).read_bytes() == (artifact / "v25_monitor_state.json").read_bytes()
    assert Path(latest["ledger_path"]).read_bytes() == (artifact / "forward_ledger_2h.csv").read_bytes()
    assert latest["monitor_sha256"] == _sha(Path(latest["monitor_path"]))
    assert latest["ledger_sha256"] == _sha(Path(latest["ledger_path"]))
    assert Path(result["doc_path"]).is_file()


def test_lock_snapshot_rejects_non_append(tmp_path: Path) -> None:
    artifact, registry_path, monitoring, docs = _fixture(tmp_path)
    # Replace the current artifact with the already-registered one-row prefix.
    prior = pd.read_csv(monitoring / "prior.csv", dtype=str, keep_default_na=False)
    prior.to_csv(artifact / "forward_ledger_2h.csv", index=False, lineterminator="\n")
    (artifact / "v25_monitor_state.json").write_text(
        json.dumps(_monitor(1), indent=2) + "\n", encoding="utf-8"
    )
    with pytest.raises(ValueError, match="not an append"):
        lock_snapshot(
            artifact_dir=artifact,
            registry_path=registry_path,
            monitoring_dir=monitoring,
            docs_dir=docs,
            artifact_id=42,
            artifact_sha256="b" * 64,
            run_id=123,
        )


def test_lock_snapshot_rejects_candidate_change(tmp_path: Path) -> None:
    artifact, registry_path, monitoring, docs = _fixture(tmp_path)
    monitor = json.loads((artifact / "v25_monitor_state.json").read_text(encoding="utf-8"))
    monitor["candidate"] = "CHANGED"
    (artifact / "v25_monitor_state.json").write_text(json.dumps(monitor), encoding="utf-8")
    with pytest.raises(ValueError, match="candidate identity changed"):
        lock_snapshot(
            artifact_dir=artifact,
            registry_path=registry_path,
            monitoring_dir=monitoring,
            docs_dir=docs,
            artifact_id=42,
            artifact_sha256="b" * 64,
            run_id=123,
        )
