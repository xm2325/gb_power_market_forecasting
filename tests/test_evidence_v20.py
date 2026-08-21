from __future__ import annotations

import json
from pathlib import Path

from gb_power_market.evidence_v20 import build_evidence_bundle


def _write(p: Path, obj):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj), encoding="utf-8")


def _real_result(*, ref=100.0, dep=80.0, promoted=True, source="PRICE_PLUS_NESO_LEVELS", gate="PASS_REAL"):
    return {
        "claim_gate": {"status": gate},
        "selection": {"promoted": promoted, "deployed_source": source},
        "rows": {"final": 1600, "expected_final": 1623, "final_coverage": 1600/1623},
        "information_audit": {"future_neso_publications": 0},
        "final_test": {
            "previous_settlement_day_reference": {"mae_gbp_mwh": ref},
            "deployed": {"mae_gbp_mwh": dep, "p95_abs_error_gbp_mwh": 200.0},
            "interval": {"empirical_coverage": 0.9},
            "abstention": {"action_rate": 0.4},
        },
    }


def _base_tree(tmp_path: Path):
    r = tmp_path / "reports" / "v19_real_market"
    _write(r / "elexon_coverage_audit.json", {"status": "PASS_REAL"})
    _write(r / "neso_download_manifest.json", {"status": "PASS"})
    _write(r / "neso_materialise_manifest.json", {"status": "PASS"})
    _write(r / "elexon_download_manifest.json", {"status": "PASS"})
    _write(r / "neso_physical_benchmark" / "real_neso_asof_benchmark.json", {"results": [{"horizon": h, "claim_gate": "PASS_REAL", "end_to_end_coverage": 0.99} for h in ("30m","2h","6h","12h")]})
    return r


def test_positive_negative_and_fallback_are_separated(tmp_path):
    r = _base_tree(tmp_path)
    payload = {
        "horizons": {
            "30m": _real_result(ref=100, dep=80),
            "2h": _real_result(ref=100, dep=120),
            "6h": _real_result(ref=100, dep=100, promoted=False, source="PREVIOUS_SETTLEMENT_DAY_FALLBACK"),
            "12h": _real_result(gate="BLOCKED"),
        }
    }
    _write(r / "real_price_benchmark_all.json", payload)
    out = tmp_path / "out"
    result = build_evidence_bundle(tmp_path, r, out, generated_at_utc="2026-08-21T00:00:00+00:00")
    assert result["horizons"]["30m"]["claim_class"] == "REAL_CLAIMABLE_POSITIVE"
    assert result["horizons"]["2h"]["claim_class"] == "REAL_NEGATIVE_RESULT"
    assert result["horizons"]["6h"]["claim_class"] == "REAL_FALLBACK_RESULT"
    assert result["horizons"]["12h"]["claim_class"] == "BLOCKED_EVIDENCE"
    cv = (out / "V0_20_CV_SAFE_SUMMARY.md").read_text()
    assert "30m" in cv and "2h" not in cv.split("## Claim boundary")[0]


def test_missing_provenance_globally_blocks_numbers(tmp_path):
    r = _base_tree(tmp_path)
    (r / "elexon_download_manifest.json").unlink()
    _write(r / "real_price_benchmark_all.json", {"horizons": {h: _real_result() for h in ("30m","2h","6h","12h")}})
    result = build_evidence_bundle(tmp_path, r, tmp_path / "out")
    assert result["global_blockers"]
    assert all(v["claim_class"] == "BLOCKED_EVIDENCE" for v in result["horizons"].values())


def test_source_hash_changes_when_source_changes(tmp_path):
    r = _base_tree(tmp_path)
    _write(r / "real_price_benchmark_all.json", {"horizons": {h: _real_result() for h in ("30m","2h","6h","12h")}})
    a = build_evidence_bundle(tmp_path, r, tmp_path / "out1", generated_at_utc="x")
    before = next(s["sha256"] for s in a["sources"] if s["logical_name"] == "elexon_coverage_audit")
    _write(r / "elexon_coverage_audit.json", {"status": "PASS_REAL", "extra": 1})
    b = build_evidence_bundle(tmp_path, r, tmp_path / "out2", generated_at_utc="x")
    after = next(s["sha256"] for s in b["sources"] if s["logical_name"] == "elexon_coverage_audit")
    assert before != after


def test_evidence_id_depends_on_sources_not_generation_time(tmp_path):
    r = _base_tree(tmp_path)
    _write(r / "real_price_benchmark_all.json", {"horizons": {h: _real_result() for h in ("30m","2h","6h","12h")}})
    a = build_evidence_bundle(tmp_path, r, tmp_path / "out1", generated_at_utc="2026-08-21T00:00:00+00:00")
    b = build_evidence_bundle(tmp_path, r, tmp_path / "out2", generated_at_utc="2026-08-22T00:00:00+00:00")
    assert a["evidence_id_sha256"] == b["evidence_id_sha256"]
    _write(r / "elexon_download_manifest.json", {"status": "PASS", "snapshot": 2})
    c = build_evidence_bundle(tmp_path, r, tmp_path / "out3", generated_at_utc="2026-08-22T00:00:00+00:00")
    assert c["evidence_id_sha256"] != a["evidence_id_sha256"]
