#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from gb_power_market.v26_gate_diagnostics import summarise_v26_gate_diagnostics


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rows", default="reports/v26_2h/v26_rows_2h.csv")
    ap.add_argument("--forward-start-utc", default="2026-08-22T20:30:00Z")
    ap.add_argument("--out", default="reports/v26_2h/v26_gate_diagnostics.json")
    args = ap.parse_args()

    rows = pd.read_csv(args.rows)
    target = pd.to_datetime(rows["target_start_utc"], utc=True, errors="raise")
    start = pd.Timestamp(args.forward_start_utc)
    if start.tzinfo is None:
        raise SystemExit("v0.26 gate diagnostic forward start must be timezone-aware")
    forward = rows.loc[target >= start.tz_convert("UTC")].copy()

    result = {
        "version": "0.26.0",
        "forward_start_utc": start.tz_convert("UTC").isoformat(),
        "cumulative": summarise_v26_gate_diagnostics(forward),
        "last_6h": (
            summarise_v26_gate_diagnostics(forward.tail(12))
            if len(forward) >= 12
            else {
                "rows": int(len(forward)),
                "status": "INSUFFICIENT_ROWS_NEED_12",
                "monitoring_only": True,
            }
        ),
        "claim_boundary": (
            "This file is a descriptive monitoring output for the already-frozen v0.26 gate. It does not "
            "change candidate selection, alert thresholds, promotion rules or the v0.26 forward boundary."
        ),
    }

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
