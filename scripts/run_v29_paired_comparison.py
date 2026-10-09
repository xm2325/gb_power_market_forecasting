#!/usr/bin/env python3
"""Refresh derived, non-authoritative same-target v0.28/v0.29 score report."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from gb_power_market.paired_monitor_v29 import compare_streams
from gb_power_market.prospective_v28 import utc


def _load(directory: Path) -> dict[str, dict]:
    data: dict[str, dict] = {}
    for path in sorted(directory.glob("*.json")):
        row = json.loads(path.read_text(encoding="utf-8"))
        key = utc(row["target_start_utc"]).isoformat()
        if key in data:
            raise ValueError("duplicate target in comparison stream")
        data[key] = row
    return data


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--v28-root", type=Path, default=Path("reports/forward/v28"))
    ap.add_argument("--v29-root", type=Path, default=Path("reports/forward/v29"))
    ap.add_argument("--max-issue-gap-minutes", type=float, default=15)
    args = ap.parse_args()

    result = compare_streams(
        _load(args.v28_root / "scores"),
        _load(args.v29_root / "scores"),
        _load(args.v28_root / "predictions"),
        _load(args.v29_root / "predictions"),
        max_issue_gap_minutes=args.max_issue_gap_minutes,
    )
    out = args.v29_root / "paired_v28_v29_latest.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": result["status"],
        "matched_rows": result["matched_rows"],
        "rejected_pairs": len(result["rejected_pairs"]),
    }, indent=2))


if __name__ == "__main__":
    main()
