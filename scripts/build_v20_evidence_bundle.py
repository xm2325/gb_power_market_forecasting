#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from gb_power_market.evidence_v20 import build_evidence_bundle


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project-root", default=".")
    ap.add_argument("--report-dir", default="reports/v19_real_market")
    ap.add_argument("--out-dir", default="reports/v20_evidence")
    ap.add_argument("--generated-at-utc", default=None)
    ap.add_argument("--github-step-summary", default=None)
    args = ap.parse_args()
    root = Path(args.project_root).resolve()
    payload = build_evidence_bundle(root, root / args.report_dir, root / args.out_dir, generated_at_utc=args.generated_at_utc)
    print(json.dumps(payload["summary"], indent=2))
    if args.github_step_summary:
        summary = Path(args.github_step_summary)
        text = (root / args.out_dir / "V0_20_INTERVIEW_SAFE_SUMMARY.md").read_text(encoding="utf-8")
        with summary.open("a", encoding="utf-8") as f:
            f.write("\n" + text + "\n")


if __name__ == "__main__":
    main()
