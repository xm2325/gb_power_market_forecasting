#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

EVIDENCE_CLASS = "HISTORICAL_ASOF_ROLLING_ORIGIN_NOT_LIVE_FORWARD"
LOCK_STATUS = "HISTORICAL_EVIDENCE_LOCKED_NOT_FORWARD_VALIDATION"
README_START = "<!-- V27_HISTORICAL_ROLLING_ORIGIN_START -->"
README_END = "<!-- V27_HISTORICAL_ROLLING_ORIGIN_END -->"

HISTORICAL_RUN = {
    "run_id": 32938613665,
    "artifact_id": 9595918850,
    "artifact_name": "v27-historical-walkforward-32938613665",
    "artifact_zip_sha256": "5c79946e0bc25d5163408b1f3814120bdfcdbffec5439f3facbf04fd6c421d54",
    "evidence_commit": "5d513685f2cea50083617483f9028453ad817b80",
}
UNCERTAINTY_RUN = {
    "run_id": 32939596992,
    "artifact_id": 9596046808,
    "artifact_name": "v27-historical-uncertainty-32939596992",
    "artifact_zip_sha256": "d54f59c460dcb5f627dc4b7100da854a0f77f817dc7e9faffc456c015cf078dc",
    "evidence_commit": "e3435ef7de20ab08d822027fb50d7e095e663c63",
}
PREDICTIVE_BLOBS = {
    "v0.25": "2ccb3d2a0762eec66d646e164262f8ac5b759d8e",
    "v0.26": "399915c6cdd0d3b016bde73cb0ef92eb2697adf8",
    "v0.27": "3c361dbb0e1665bbbad2e1097b8580ce062a203f",
}
EVIDENCE_FILES = (
    "reports/v27_historical_walkforward/historical_walkforward_rows.csv",
    "reports/v27_historical_walkforward/historical_walkforward_summary.json",
    "reports/v27_historical_walkforward/fold_summary.csv",
    "reports/v27_historical_walkforward/historical_uncertainty.json",
    "docs/V0_27_HISTORICAL_ROLLING_ORIGIN.md",
)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def git_blob(path: Path) -> str:
    proc = subprocess.run(
        ["git", "hash-object", str(path)],
        check=True,
        capture_output=True,
        text=True,
    )
    return proc.stdout.strip()


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _validate(summary: dict[str, Any], uncertainty: dict[str, Any]) -> None:
    if summary.get("status") != "HISTORICAL_ASOF_ROLLING_ORIGIN_COMPLETE":
        raise ValueError("historical walk-forward is not complete")
    config = summary.get("config", {})
    if config.get("evidence_class") != EVIDENCE_CLASS or summary.get("overall", {}).get("evidence_class") != EVIDENCE_CLASS:
        raise ValueError("historical evidence class changed")
    if config.get("score_start_utc") != "2026-05-01T00:00:00Z" or config.get("score_end_exclusive_utc") != "2026-08-23T22:00:00Z":
        raise ValueError("historical score window changed")
    if summary.get("overall", {}).get("rows") != 5516:
        raise ValueError("historical row count changed")
    if summary.get("final_score_support_rule") != "DEPLOYED_FAMILY_FEATURES_ONLY_AFTER_COMMON_SUPPORT_SELECTION":
        raise ValueError("deployed-family score support rule changed")

    if uncertainty.get("status") != "HISTORICAL_UNCERTAINTY_ANALYSIS_COMPLETE":
        raise ValueError("historical uncertainty analysis is incomplete")
    if uncertainty.get("evidence_class") != EVIDENCE_CLASS or uncertainty.get("rows") != 5516:
        raise ValueError("historical uncertainty scope changed")
    weekly = uncertainty.get("weekly_consistency", {})
    if weekly.get("causal_base", {}).get("v27_better_folds") != 12 or weekly.get("v0.26", {}).get("v27_better_folds") != 7:
        raise ValueError("weekly consistency evidence changed")
    comparisons = uncertainty.get("comparisons_vs_v27", {})
    if comparisons.get("causal_base", {}).get("observed_mae_gain_gbp_mwh", 0.0) <= 0.0:
        raise ValueError("v0.27/base observed ordering changed")
    if comparisons.get("v0.26", {}).get("observed_mae_gain_gbp_mwh", 0.0) >= 0.0:
        raise ValueError("v0.27/v0.26 observed ordering changed")
    if "live-forward" not in uncertainty.get("claim_boundary", "").lower():
        raise ValueError("uncertainty claim boundary missing")


def build_manifest(root: Path = Path(".")) -> dict[str, Any]:
    summary_path = root / "reports/v27_historical_walkforward/historical_walkforward_summary.json"
    uncertainty_path = root / "reports/v27_historical_walkforward/historical_uncertainty.json"
    summary = load_json(summary_path)
    uncertainty = load_json(uncertainty_path)
    _validate(summary, uncertainty)

    files = {}
    for relative in EVIDENCE_FILES:
        path = root / relative
        if not path.exists():
            raise FileNotFoundError(relative)
        files[relative] = {
            "sha256": sha256_file(path),
            "git_blob_sha1": git_blob(path),
            "bytes": path.stat().st_size,
        }

    models = uncertainty["model_metrics"]
    comparisons = uncertainty["comparisons_vs_v27"]
    return {
        "version": "0.27.0-historical-evidence-lock-1",
        "status": LOCK_STATUS,
        "evidence_class": EVIDENCE_CLASS,
        "claim_boundary": (
            "Locked retrospective historical as-of rolling-origin robustness evidence. It is not live-forward "
            "evidence, not untouched confirmatory validation, and does not authorize retuning, promotion or an automatic model change."
        ),
        "scope": {
            "rows": 5516,
            "start_utc": "2026-05-01T00:00:00+00:00",
            "end_exclusive_utc": "2026-08-23T22:00:00+00:00",
            "horizon_minutes": 120,
            "fold_days": 7,
            "selection_days": 14,
            "calibration_days": 14,
            "adaptation_warmup_hours": 72,
        },
        "source_runs": {
            "historical_walkforward": HISTORICAL_RUN,
            "historical_uncertainty": UNCERTAINTY_RUN,
        },
        "predictive_source_blobs": PREDICTIVE_BLOBS,
        "files": files,
        "headline_metrics": {
            "causal_base_mae_gbp_mwh": models["causal_base"]["mae_gbp_mwh"],
            "v0.25_mae_gbp_mwh": models["v0.25"]["mae_gbp_mwh"],
            "v0.26_mae_gbp_mwh": models["v0.26"]["mae_gbp_mwh"],
            "v0.27_mae_gbp_mwh": models["v0.27"]["mae_gbp_mwh"],
            "previous_day_mae_gbp_mwh": models["previous_day"]["mae_gbp_mwh"],
            "v0.27_improvement_vs_causal_base_pct": comparisons["causal_base"]["observed_improvement_pct"],
            "v0.27_improvement_vs_v0.26_pct": comparisons["v0.26"]["observed_improvement_pct"],
            "v0.27_improvement_vs_v0.25_pct": comparisons["v0.25"]["observed_improvement_pct"],
            "v0.27_improvement_vs_previous_day_pct": comparisons["previous_day"]["observed_improvement_pct"],
        },
        "uncertainty": {
            "primary_block": comparisons["causal_base"]["bootstrap_by_block_length_rows"]["48"],
            "weekly_block_sensitivity": comparisons["causal_base"]["bootstrap_by_block_length_rows"]["336"],
            "v0.27_vs_v0.26_primary_block": comparisons["v0.26"]["bootstrap_by_block_length_rows"]["48"],
            "v0.27_vs_v0.26_weekly_block_sensitivity": comparisons["v0.26"]["bootstrap_by_block_length_rows"]["336"],
        },
        "weekly_consistency": uncertainty["weekly_consistency"],
        "automatic_promotion": False,
        "automatic_model_change": False,
        "retuning_authorized": False,
    }


def render_readme_section(manifest: dict[str, Any]) -> str:
    h = manifest["headline_metrics"]
    u = manifest["uncertainty"]
    w = manifest["weekly_consistency"]
    base24 = u["primary_block"]
    base7d = u["weekly_block_sensitivity"]
    v26_24 = u["v0.27_vs_v0.26_primary_block"]
    v26_7d = u["v0.27_vs_v0.26_weekly_block_sensitivity"]
    return "\n".join(
        [
            README_START,
            "## v0.27 — May–August leakage-safe historical rolling-origin robustness",
            "",
            "To test whether the adaptive structure generalises beyond the short live-forward sequence, the repository now includes a separate retrospective **as-of rolling-origin** evaluation. It does not replay today's fitted coefficients into the past: every weekly fold refits/reselects its causal base using only prior data, then uses a 72h causal adaptation warm-up before scoring.",
            "",
            "Window: **2026-05-01 00:00 UTC → 2026-08-23 22:00 UTC**, exactly **5,516 contiguous half-hours**. Evidence class: `HISTORICAL_ASOF_ROLLING_ORIGIN_NOT_LIVE_FORWARD`.",
            "",
            "| Model | MAE (£/MWh) | Historical interpretation |",
            "|---|---:|---|",
            f"| causal rolling-origin base | {h['causal_base_mae_gbp_mwh']:.3f} | fold-specific refit/reselection |",
            f"| v0.25 | {h['v0.25_mae_gbp_mwh']:.3f} | clearly degraded |",
            f"| **v0.26** | **{h['v0.26_mae_gbp_mwh']:.3f}** | lowest overall MAE |",
            f"| v0.27 | {h['v0.27_mae_gbp_mwh']:.3f} | {h['v0.27_improvement_vs_causal_base_pct']:.2f}% better than base, but {abs(h['v0.27_improvement_vs_v0.26_pct']):.2f}% worse than v0.26 |",
            f"| previous-day reference | {h['previous_day_mae_gbp_mwh']:.3f} | v0.27 is {h['v0.27_improvement_vs_previous_day_pct']:.1f}% better |",
            "",
            f"Against the causal base, v0.27's observed MAE gain is **{base24['observed_paired_mae_gain_gbp_mwh']:.3f} £/MWh**, but the paired 24h-block 95% interval is **[{base24['ci95_lower_gbp_mwh']:.3f}, {base24['ci95_upper_gbp_mwh']:.3f}]** and the 7-day-block sensitivity is **[{base7d['ci95_lower_gbp_mwh']:.3f}, {base7d['ci95_upper_gbp_mwh']:.3f}]**; both include zero. v0.27 beats the base in **{w['causal_base']['v27_better_folds']}/{w['causal_base']['folds']}** weekly folds.",
            "",
            f"Against v0.26, v0.27 is worse overall by **{abs(h['v0.27_improvement_vs_v0.26_pct']):.2f}%** and wins only **{w['v0.26']['v27_better_folds']}/{w['v0.26']['folds']}** folds. The 24h-block interval for `v0.26 MAE − v0.27 MAE` is **[{v26_24['ci95_lower_gbp_mwh']:.3f}, {v26_24['ci95_upper_gbp_mwh']:.3f}] £/MWh**, while the 7-day sensitivity **[{v26_7d['ci95_lower_gbp_mwh']:.3f}, {v26_7d['ci95_upper_gbp_mwh']:.3f}]** narrowly includes zero. The repository therefore does **not** claim that v0.27 historically dominates v0.26.",
            "",
            "The stronger conclusions are narrower: v0.27 robustly improves on the failed v0.25 correction and on the previous-day reference, while its incremental benefit over the causal base is small and uncertain. These historical rows do not authorize retuning or promotion.",
            "",
            "Evidence:",
            "",
            "- [`docs/V0_27_HISTORICAL_ROLLING_ORIGIN.md`](docs/V0_27_HISTORICAL_ROLLING_ORIGIN.md)",
            "- [`reports/v27_historical_walkforward/historical_walkforward_summary.json`](reports/v27_historical_walkforward/historical_walkforward_summary.json)",
            "- [`reports/v27_historical_walkforward/historical_uncertainty.json`](reports/v27_historical_walkforward/historical_uncertainty.json)",
            "- [`reports/locked/V0_27_HISTORICAL_ROLLING_ORIGIN_EVIDENCE_MANIFEST.json`](reports/locked/V0_27_HISTORICAL_ROLLING_ORIGIN_EVIDENCE_MANIFEST.json)",
            README_END,
        ]
    )


def update_readme_text(text: str, section: str) -> str:
    if README_START in text or README_END in text:
        if text.count(README_START) != 1 or text.count(README_END) != 1:
            raise ValueError("README historical evidence markers are malformed")
        start = text.index(README_START)
        end = text.index(README_END) + len(README_END)
        return text[:start] + section + text[end:]
    marker = "## Repository layout"
    if marker not in text:
        raise ValueError("README insertion marker missing")
    return text.replace(marker, section + "\n\n" + marker, 1)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", default="reports/locked/V0_27_HISTORICAL_ROLLING_ORIGIN_EVIDENCE_MANIFEST.json")
    ap.add_argument("--readme", default="README.md")
    args = ap.parse_args()

    manifest = build_manifest()
    manifest_path = Path(args.manifest)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_text = json.dumps(manifest, indent=2) + "\n"
    if manifest_path.exists() and manifest_path.read_text(encoding="utf-8") != manifest_text:
        raise RuntimeError("historical evidence manifest already exists with different bytes")
    manifest_path.write_text(manifest_text, encoding="utf-8")

    readme_path = Path(args.readme)
    original = readme_path.read_text(encoding="utf-8")
    updated = update_readme_text(original, render_readme_section(manifest))
    readme_path.write_text(updated, encoding="utf-8")
    print(manifest_path)


if __name__ == "__main__":
    main()
