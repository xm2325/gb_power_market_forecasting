import hashlib
import json
from pathlib import Path

import pandas as pd
import pytest

from gb_power_market.forward_ledger_v26 import build_v26_forward_ledger
from scripts.lock_v26_forward_snapshot import EXPECTED_CANDIDATE, lock_snapshot


FORWARD_START = "2026-08-22T20:30:00Z"


def _rows(n: int) -> pd.DataFrame:
    target = pd.date_range(FORWARD_START, periods=n, freq="30min")
    return pd.DataFrame(
        {
            "target_start_utc": target,
            "decision_time_utc": target - pd.Timedelta(hours=2),
            "realised_price_gbp_mwh": [100.0 + i for i in range(n)],
            "frozen_prediction_gbp_mwh": [95.0 + i for i in range(n)],
            "previous_settlement_day_reference_gbp_mwh": [110.0 + i for i in range(n)],
            "v26_short_residual_mean_gbp_mwh": [2.0 for _ in range(n)],
            "v26_long_residual_mean_gbp_mwh": [3.0 for _ in range(n)],
            "v26_gate_reason": ["CONSENSUS_CLIPPED_CORRECTION" for _ in range(n)],
            "v26_correction_gbp_mwh": [2.0 for _ in range(n)],
            "v26_prediction_gbp_mwh": [97.0 + i for i in range(n)],
        }
    )


def _summary(rows: int, prior_ledger: pd.DataFrame) -> dict:
    end = pd.Timestamp(FORWARD_START) + pd.Timedelta(minutes=30 * rows)
    return {
        "version": "0.26.0",
        "candidate_spec": {
            "version": "0.26.0",
            "candidate": EXPECTED_CANDIDATE,
            "forward_start_utc": "2026-08-22T20:30:00+00:00",
        },
        "forward_segment": {
            "rows": rows,
            "start_utc": "2026-08-22T20:30:00+00:00",
            "end_exclusive_utc": end.isoformat(),
            "candidate_mae_gbp_mwh": 3.0,
            "frozen_mae_gbp_mwh": 5.0,
            "v25_mae_gbp_mwh": 4.0,
            "reference_mae_gbp_mwh": 10.0,
            "candidate_improvement_vs_frozen_pct": 40.0,
            "candidate_improvement_vs_reference_pct": 70.0,
        },
        "monitor": {
            "maturity_stage": "EARLY_ONLY",
            "alert_status": "INSUFFICIENT_SAMPLE_FOR_ALERTS",
            "alerts": [],
        },
        "ledger_integrity": {
            "status": "LOCKED_PREFIX_REPRODUCED",
            "locked_rows": len(prior_ledger),
            "locked_chain_tip_sha256": str(prior_ledger.iloc[-1]["chain_sha256"]),
            "current_rows": rows,
            "new_rows_after_locked_prefix": rows - len(prior_ledger),
        },
        "promotion_readiness": {
            "minimum_forward_rows": 336,
            "rows_observed": rows,
            "status": "NOT_ELIGIBLE",
            "automatic_promotion": False,
        },
    }


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fixture(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    monitoring = tmp_path / "reports" / "monitoring"
    docs = tmp_path / "docs"
    artifact = tmp_path / "artifact"
    monitoring.mkdir(parents=True)
    artifact.mkdir()

    prior_ledger = build_v26_forward_ledger(_rows(2), forward_start_utc=FORWARD_START)
    prior_path = monitoring / "prior.csv"
    prior_ledger.to_csv(prior_path, index=False, lineterminator="\n")
    prior_checkpoint = monitoring / "prior.json"
    prior_checkpoint.write_text(json.dumps({"rows": 2}, indent=2) + "\n", encoding="utf-8")

    registry = {
        "schema": "gb-power-market-v26-forward-snapshot-registry-v1",
        "candidate": EXPECTED_CANDIDATE,
        "forward_start_utc": FORWARD_START,
        "append_only": True,
        "snapshots": [
            {
                "sequence": 1,
                "end_exclusive_utc": "2026-08-22T21:30:00Z",
                "rows": 2,
                "new_rows": 2,
                "artifact_id": 1,
                "artifact_sha256": "a" * 64,
                "checkpoint_path": prior_checkpoint.as_posix(),
                "ledger_path": prior_path.as_posix(),
                "ledger_sha256": _sha(prior_path),
                "ledger_chain_tip_sha256": str(prior_ledger.iloc[-1]["chain_sha256"]),
                "maturity_stage": "EARLY_ONLY",
                "alert_status": "INSUFFICIENT_SAMPLE_FOR_ALERTS",
                "alerts": [],
            }
        ],
        "contract": "test",
    }
    registry_path = monitoring / "registry.json"
    registry_path.write_text(json.dumps(registry, indent=2) + "\n", encoding="utf-8")

    current_ledger = build_v26_forward_ledger(_rows(4), forward_start_utc=FORWARD_START)
    current_ledger.to_csv(artifact / "v26_forward_ledger.csv", index=False, lineterminator="\n")
    (artifact / "v26_summary.json").write_text(
        json.dumps(_summary(4, prior_ledger), indent=2) + "\n", encoding="utf-8"
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
    assert result["rows"] == 4
    assert result["new_rows"] == 2

    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    latest = registry["snapshots"][-1]
    assert latest["rows"] == 4
    assert latest["new_rows"] == 2
    assert latest["artifact_id"] == 42
    assert latest["run_id"] == 123
    assert Path(latest["checkpoint_path"]).read_bytes() == (artifact / "v26_summary.json").read_bytes()
    assert Path(latest["ledger_path"]).read_bytes() == (artifact / "v26_forward_ledger.csv").read_bytes()
    assert latest["checkpoint_sha256"] == _sha(Path(latest["checkpoint_path"]))
    assert latest["ledger_sha256"] == _sha(Path(latest["ledger_path"]))
    assert Path(result["doc_path"]).is_file()


def test_lock_snapshot_rejects_non_append(tmp_path: Path) -> None:
    artifact, registry_path, monitoring, docs = _fixture(tmp_path)
    prior = pd.read_csv(monitoring / "prior.csv", dtype=str, keep_default_na=False)
    prior.to_csv(artifact / "v26_forward_ledger.csv", index=False, lineterminator="\n")
    (artifact / "v26_summary.json").write_text(
        json.dumps(_summary(2, prior), indent=2) + "\n", encoding="utf-8"
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


def test_lock_snapshot_rejects_stale_locked_prefix(tmp_path: Path) -> None:
    artifact, registry_path, monitoring, docs = _fixture(tmp_path)
    summary = json.loads((artifact / "v26_summary.json").read_text(encoding="utf-8"))
    summary["ledger_integrity"]["locked_rows"] = 1
    (artifact / "v26_summary.json").write_text(json.dumps(summary), encoding="utf-8")
    with pytest.raises(ValueError, match="locked-prefix row count"):
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
    summary = json.loads((artifact / "v26_summary.json").read_text(encoding="utf-8"))
    summary["candidate_spec"]["candidate"] = "CHANGED"
    (artifact / "v26_summary.json").write_text(json.dumps(summary), encoding="utf-8")
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
