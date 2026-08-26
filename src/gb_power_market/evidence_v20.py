from __future__ import annotations

import csv
import hashlib
import json
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

HORIZONS = ("30m", "2h", "6h", "12h")


@dataclass(frozen=True)
class EvidenceSource:
    logical_name: str
    path: str
    exists: bool
    sha256: str | None
    bytes: int | None


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def read_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def source_record(logical_name: str, path: Path, root: Path) -> EvidenceSource:
    if not path.exists():
        return EvidenceSource(logical_name, str(path.relative_to(root)), False, None, None)
    return EvidenceSource(
        logical_name,
        str(path.relative_to(root)),
        True,
        sha256_file(path),
        path.stat().st_size,
    )


def _price_horizon_classification(result: dict[str, Any] | None) -> dict[str, Any]:
    if not result:
        return {
            "claim_class": "BLOCKED_EVIDENCE",
            "numerical_use": "DO_NOT_USE",
            "reason": "missing horizon result",
        }
    gate = result.get("claim_gate", {}).get("status")
    if gate != "PASS_REAL":
        return {
            "claim_class": "BLOCKED_EVIDENCE",
            "numerical_use": "DO_NOT_USE",
            "reason": f"real-data claim gate={gate or 'missing'}",
        }

    ref = result.get("final_test", {}).get("previous_settlement_day_reference", {}).get("mae_gbp_mwh")
    dep = result.get("final_test", {}).get("deployed", {}).get("mae_gbp_mwh")
    deployed_source = result.get("selection", {}).get("deployed_source")
    promoted = bool(result.get("selection", {}).get("promoted"))
    if ref is None or dep is None or not isinstance(ref, (int, float)) or not isinstance(dep, (int, float)):
        return {
            "claim_class": "BLOCKED_EVIDENCE",
            "numerical_use": "DO_NOT_USE",
            "reason": "PASS_REAL gate but final MAE fields missing",
        }
    improvement = None if ref == 0 else 100.0 * (float(ref) - float(dep)) / float(ref)
    if deployed_source == "PREVIOUS_SETTLEMENT_DAY_FALLBACK" or not promoted:
        claim_class = "REAL_FALLBACK_RESULT"
        cv = "DO_NOT_USE_AS_POSITIVE_CV_METRIC"
    elif improvement is not None and improvement > 0:
        claim_class = "REAL_CLAIMABLE_POSITIVE"
        cv = "CV_NUMERICALLY_ELIGIBLE"
    else:
        claim_class = "REAL_NEGATIVE_RESULT"
        cv = "INTERVIEW_ONLY_OR_NEGATIVE_RESULT"
    return {
        "claim_class": claim_class,
        "numerical_use": cv,
        "reason": "real-data gate passed",
        "reference_mae_gbp_mwh": float(ref),
        "deployed_mae_gbp_mwh": float(dep),
        "final_improvement_pct": improvement,
        "deployed_source": deployed_source,
        "promoted": promoted,
        "final_rows": result.get("rows", {}).get("final"),
        "expected_final_rows": result.get("rows", {}).get("expected_final"),
        "final_coverage": result.get("rows", {}).get("final_coverage"),
        "future_neso_publications": result.get("information_audit", {}).get("future_neso_publications"),
        "p95_abs_error_gbp_mwh": result.get("final_test", {}).get("deployed", {}).get("p95_abs_error_gbp_mwh"),
        "interval_coverage": result.get("final_test", {}).get("interval", {}).get("empirical_coverage"),
        "action_rate": result.get("final_test", {}).get("abstention", {}).get("action_rate"),
    }


def _neso_horizon_map(payload: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    if not payload:
        return {}
    out = {}
    for row in payload.get("results", []):
        if isinstance(row, dict) and row.get("horizon"):
            out[str(row["horizon"])] = row
    return out


def build_evidence_bundle(project_root: Path, report_dir: Path, out_dir: Path, *, generated_at_utc: str | None = None) -> dict[str, Any]:
    project_root = project_root.resolve()
    report_dir = report_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    price_all_path = report_dir / "real_price_benchmark_all.json"
    elexon_audit_path = report_dir / "elexon_coverage_audit.json"
    neso_benchmark_path = report_dir / "neso_physical_benchmark" / "real_neso_asof_benchmark.json"
    neso_download_path = report_dir / "neso_download_manifest.json"
    neso_materialise_path = report_dir / "neso_materialise_manifest.json"
    elexon_download_path = report_dir / "elexon_download_manifest.json"

    inputs = {
        "real_price_benchmark": price_all_path,
        "elexon_coverage_audit": elexon_audit_path,
        "neso_physical_benchmark": neso_benchmark_path,
        "neso_download_manifest": neso_download_path,
        "neso_materialise_manifest": neso_materialise_path,
        "elexon_download_manifest": elexon_download_path,
    }
    sources = [source_record(k, p, project_root) for k, p in inputs.items()]

    price_all = read_json(price_all_path)
    elexon = read_json(elexon_audit_path)
    neso = read_json(neso_benchmark_path)
    neso_map = _neso_horizon_map(neso)

    global_blockers: list[str] = []
    if not elexon or elexon.get("status") != "PASS_REAL":
        global_blockers.append("Elexon coverage audit is missing or not PASS_REAL")
    for name in ("neso_download_manifest", "neso_materialise_manifest", "elexon_download_manifest"):
        rec = next(x for x in sources if x.logical_name == name)
        if not rec.exists:
            global_blockers.append(f"missing provenance source: {name}")
    if not price_all:
        global_blockers.append("missing real_price_benchmark_all.json")

    horizons: dict[str, Any] = {}
    for h in HORIZONS:
        raw = (price_all or {}).get("horizons", {}).get(h)
        c = _price_horizon_classification(raw)
        neso_row = neso_map.get(h)
        c["neso_physical_claim_gate"] = neso_row.get("claim_gate") if neso_row else None
        c["neso_physical_end_to_end_coverage"] = neso_row.get("end_to_end_coverage") if neso_row else None
        if global_blockers and c["claim_class"] != "BLOCKED_EVIDENCE":
            c["claim_class"] = "BLOCKED_EVIDENCE"
            c["numerical_use"] = "DO_NOT_USE"
            c["reason"] = "; ".join(global_blockers)
        horizons[h] = c

    generated = generated_at_utc or datetime.now(timezone.utc).isoformat()
    fingerprint_payload = {
        "version": "0.20.0",
        "sources": [
            {"logical_name": x.logical_name, "exists": x.exists, "sha256": x.sha256, "bytes": x.bytes}
            for x in sorted(sources, key=lambda z: z.logical_name)
        ],
    }
    evidence_id = hashlib.sha256(json.dumps(fingerprint_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    cv_eligible = [h for h, c in horizons.items() if c["claim_class"] == "REAL_CLAIMABLE_POSITIVE"]
    real_negative = [h for h, c in horizons.items() if c["claim_class"] in {"REAL_NEGATIVE_RESULT", "REAL_FALLBACK_RESULT"}]
    blocked = [h for h, c in horizons.items() if c["claim_class"] == "BLOCKED_EVIDENCE"]

    payload = {
        "version": "0.20.0",
        "generated_at_utc": generated,
        "evidence_id_sha256": evidence_id,
        "evidence_policy": {
            "cv_numeric_rule": "Only REAL_CLAIMABLE_POSITIVE horizons may supply new positive numerical CV claims.",
            "interview_rule": "REAL_NEGATIVE_RESULT and REAL_FALLBACK_RESULT are numerically discussable as real held-out evidence, but must not be reframed as positive model wins.",
            "blocked_rule": "BLOCKED_EVIDENCE values are not usable numerically in CV, cover letter or interview claims.",
            "pnl_rule": "No public-data metric is Volcore trading P&L.",
        },
        "global_blockers": global_blockers,
        "sources": [asdict(x) for x in sources],
        "horizons": horizons,
        "summary": {
            "cv_eligible_positive_horizons": cv_eligible,
            "real_negative_or_fallback_horizons": real_negative,
            "blocked_horizons": blocked,
        },
    }
    bundle_path = out_dir / "V0_20_EVIDENCE_BUNDLE.json"
    bundle_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    (out_dir / "V0_20_EVIDENCE_BUNDLE.sha256").write_text(f"{sha256_file(bundle_path)}  {bundle_path.name}\n", encoding="utf-8")

    with (out_dir / "V0_20_CLAIM_DECISION_MATRIX.csv").open("w", newline="", encoding="utf-8") as f:
        cols = ["horizon", "claim_class", "numerical_use", "deployed_source", "promoted", "final_rows", "expected_final_rows", "final_coverage", "reference_mae_gbp_mwh", "deployed_mae_gbp_mwh", "final_improvement_pct", "p95_abs_error_gbp_mwh", "interval_coverage", "action_rate", "future_neso_publications", "neso_physical_claim_gate", "reason"]
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for h in HORIZONS:
            row = {"horizon": h, **{k: horizons[h].get(k) for k in cols if k != "horizon"}}
            w.writerow(row)

    cv_path = out_dir / "V0_20_CV_SAFE_SUMMARY.md"
    interview_path = out_dir / "V0_20_INTERVIEW_SAFE_SUMMARY.md"
    failure_path = out_dir / "V0_20_FAILURE_DIAGNOSTIC.md"
    _write_cv_summary(cv_path, payload)
    _write_interview_summary(interview_path, payload)
    _write_failure_diagnostic(failure_path, payload)

    # Stable aliases always point at the evidence generated by this run.
    # This prevents stale *_CURRENT files from an earlier blocked run from
    # being mistaken for the latest artifact evidence.
    (out_dir / "EVIDENCE_BUNDLE_CURRENT.json").write_bytes(bundle_path.read_bytes())
    (out_dir / "CV_SAFE_SUMMARY_CURRENT.md").write_bytes(cv_path.read_bytes())
    (out_dir / "INTERVIEW_SAFE_SUMMARY_CURRENT.md").write_bytes(interview_path.read_bytes())
    (out_dir / "FAILURE_DIAGNOSTIC_CURRENT.md").write_bytes(failure_path.read_bytes())
    return payload


def _write_cv_summary(path: Path, payload: dict[str, Any]) -> None:
    lines = ["# v0.20 CV-safe evidence summary", "", "This file is generated from the real-data evidence bundle. It never treats synthetic fixture metrics as application evidence.", ""]
    pos = payload["summary"]["cv_eligible_positive_horizons"]
    if not pos:
        lines += ["## New numerical price-forecast claims", "", "None. No new positive real-price metric currently satisfies the complete evidence gate.", ""]
    else:
        lines += ["## New numerical price-forecast claims", ""]
        for h in pos:
            c = payload["horizons"][h]
            lines.append(f"- {h}: real fixed-window Market Index Price MAE {c['reference_mae_gbp_mwh']:.3f} → {c['deployed_mae_gbp_mwh']:.3f} £/MWh ({c['final_improvement_pct']:.1f}% improvement), final coverage {100*c['final_coverage']:.1f}%, zero future NESO publications selected.")
        lines.append("")
    lines += ["## Claim boundary", "", "These are public-data forecasting results, not trading P&L. Do not add synthetic coverage, action-rate or alert-rate rehearsal numbers.", ""]
    path.write_text("\n".join(lines), encoding="utf-8")


def _write_interview_summary(path: Path, payload: dict[str, Any]) -> None:
    lines = ["# v0.20 interview-safe evidence summary", "", "Every horizon below is labelled by evidence class. Negative and fallback outcomes are preserved.", ""]
    for h in HORIZONS:
        c = payload["horizons"][h]
        lines.append(f"## {h} — {c['claim_class']}")
        lines.append("")
        if c["claim_class"] == "BLOCKED_EVIDENCE":
            lines.append(f"No numerical claim. Reason: {c.get('reason')}.")
        else:
            lines.append(f"Final MAE: {c.get('reference_mae_gbp_mwh'):.3f} → {c.get('deployed_mae_gbp_mwh'):.3f} £/MWh; final change {c.get('final_improvement_pct'):.1f}%; deployed source: {c.get('deployed_source')}; coverage: {100*c.get('final_coverage', 0):.1f}%.")
            if c["claim_class"] == "REAL_NEGATIVE_RESULT":
                lines.append("The candidate passed the data/information gate but did not improve the independent final window. Preserve this as a negative result.")
            elif c["claim_class"] == "REAL_FALLBACK_RESULT":
                lines.append("The deployment rule used the previous-settlement-day fallback; do not present this horizon as a model win.")
        lines.append("")
    lines += ["## Boundary", "", "System-vs-market spread analysis is diagnostic. It is not a realised trading-return claim.", ""]
    path.write_text("\n".join(lines), encoding="utf-8")


def _write_failure_diagnostic(path: Path, payload: dict[str, Any]) -> None:
    lines = ["# v0.20 failure diagnostic", ""]
    if not payload["global_blockers"] and not payload["summary"]["blocked_horizons"]:
        lines.append("No evidence-integrity blocker was detected.")
    else:
        lines.append("## Global blockers")
        lines.append("")
        for b in payload["global_blockers"]:
            lines.append(f"- {b}")
        lines += ["", "## Blocked horizons", ""]
        for h in payload["summary"]["blocked_horizons"]:
            lines.append(f"- {h}: {payload['horizons'][h].get('reason')}")
    lines += ["", "## Source inventory", ""]
    for s in payload["sources"]:
        state = "present" if s["exists"] else "MISSING"
        digest = f" sha256={s['sha256']}" if s["sha256"] else ""
        lines.append(f"- {s['logical_name']}: {state} — `{s['path']}`{digest}")
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")
