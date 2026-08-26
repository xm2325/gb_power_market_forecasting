import json
from pathlib import Path


SNAPSHOT = Path("reports/monitoring/V0_25_2H_ADAPTIVE_FORWARD_2026-08-21.json")


def test_v25_first_forward_snapshot_identity_and_boundary():
    p = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    assert p["version"] == "0.25.0"
    assert p["candidate"] == "2H_FROZEN_PLUS_CAUSAL_48H_RESIDUAL_MEAN"
    assert p["frozen_at_forward_boundary_utc"] == "2026-08-21T11:30:00Z"
    assert p["rule"]["lookback_hours"] == 48
    assert p["rule"]["outcome_delay_minutes"] == 30
    assert p["workflow_run"]["run_id"] == 32500771812
    assert p["workflow_run"]["artifact_id"] == 9453438684
    assert p["workflow_run"]["artifact_sha256"] == "64d30a6e18a2c3fa2243fa28ceb800afec1abc66f7dc0816515d96ff9faf885c"


def test_v25_first_forward_snapshot_metrics_are_not_rewritten():
    p = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    f = p["first_new_forward_segment"]
    assert f["rows"] == 6
    assert f["start_utc"] == "2026-08-21T11:30:00Z"
    assert f["end_exclusive_utc"] == "2026-08-21T14:30:00Z"
    assert abs(f["frozen_v20_mae_gbp_mwh"] - 13.18522396221401) < 1e-12
    assert abs(f["adaptive_v25_mae_gbp_mwh"] - 3.859476437369542) < 1e-12
    assert abs(f["previous_settlement_day_reference_mae_gbp_mwh"] - 9.226666666666668) < 1e-12
    assert f["evidence_strength"] == "EARLY_ONLY_6_HALF_HOURS_NO_HEADLINE_CLAIM"
