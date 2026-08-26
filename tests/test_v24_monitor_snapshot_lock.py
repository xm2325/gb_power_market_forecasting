from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
V20 = ROOT / "reports" / "locked" / "V0_20_REAL_BENCHMARK_LOCK.json"
V24 = ROOT / "reports" / "monitoring" / "V0_24_CONTINUOUS_FORWARD_2026-08-21.json"


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_v24_snapshot_is_tied_to_successful_run_and_frozen_model():
    p = _load(V24)
    assert p["status"] == "CONTINUOUS_FORWARD_MONITOR_SNAPSHOT"
    assert p["workflow_run"]["run_id"] == 32485905691
    assert p["workflow_run"]["artifact_sha256"] == "b79f86af22ea62a7c7e3fcccc3f0403353d0350f523ac432ed60d959e9abe6eb"
    assert p["frozen_model_state"]["sha256"] == "e9952aa88ca56b85f4d595bfe918cdc589ac0048d717d3fb3d9210361eb18918"
    assert p["frozen_model_state"]["model_changed"] is False


def test_v24_reproduces_the_locked_v20_final_before_extending_forward():
    old = _load(V20)["price_benchmark_final"]
    new = _load(V24)["segments"]
    for horizon in ("30m", "2h", "6h", "12h"):
        locked = new[horizon]["locked_final_full"]
        assert locked["rows"] == 1623
        assert abs(locked["frozen_model_mae_gbp_mwh"] - old[horizon]["deployed_mae_gbp_mwh"]) < 1e-9
        assert abs(locked["reference_mae_gbp_mwh"] - old[horizon]["reference_mae_gbp_mwh"]) < 1e-9
        assert abs(locked["improvement_pct"] - old[horizon]["improvement_pct"]) < 1e-9


def test_v24_information_gate_is_complete_and_asof_safe():
    p = _load(V24)
    assert p["monitor_window"]["expected_rows_each_horizon"] == 1919
    assert p["monitor_window"]["coverage_each_horizon"] == 1.0
    assert p["monitor_window"]["future_neso_publications_each_horizon"] == 0
    assert p["source_snapshot"]["neso_raw_clock_mismatch_rows"] == 0


def test_v24_evidence_roles_do_not_relabel_monitoring_as_new_locked_test():
    p = _load(V24)["segments"]
    for horizon in p:
        assert p[horizon]["locked_final_full"]["evidence_role"] == "LOCKED_HISTORICAL_OOS"
        assert p[horizon]["post_lock_to_latest"]["evidence_role"] == "POST_LOCK_FORWARD_MONITORING"
        assert p[horizon]["latest_7d"]["evidence_role"] == "ROLLING_MONITORING_ONLY"


def test_v24_core_monitoring_interpretation_is_preserved():
    p = _load(V24)["segments"]
    assert p["30m"]["post_lock_to_latest"]["improvement_pct"] > 40.0
    assert p["2h"]["post_lock_to_latest"]["improvement_pct"] < 0.0
    assert p["6h"]["post_lock_to_latest"]["improvement_pct"] < -100.0
    assert p["12h"]["post_lock_to_latest"]["model_win_rate"] < 0.01
