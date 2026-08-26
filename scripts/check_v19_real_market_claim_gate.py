#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

REPORT = Path("reports/v19_real_market")


def main() -> None:
    audit = json.loads((REPORT / "elexon_coverage_audit.json").read_text())
    if audit.get("status") != "PASS_REAL":
        raise SystemExit(f"Elexon coverage gate blocked: {audit}")
    all_result = json.loads((REPORT / "real_price_benchmark_all.json").read_text())
    blocked = {
        name: r.get("claim_gate", {}).get("status")
        for name, r in all_result.get("horizons", {}).items()
        if r.get("claim_gate", {}).get("status") != "PASS_REAL"
    }
    if blocked:
        raise SystemExit(f"One or more real price horizons failed the information/coverage gate: {blocked}")
    print("PASS_REAL: Elexon coverage + all horizon information gates passed. Performance may still be negative/fallback; that is not a gate failure.")


if __name__ == "__main__":
    main()
