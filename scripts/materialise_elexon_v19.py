#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from gb_power_market.elexon_v19 import (
    ElexonCoverageGate,
    audit_elexon_bundle,
    build_volume_weighted_market_reference,
    dump_json,
    normalise_mid,
    normalise_system_prices,
)


def read_daily(directory: Path, normaliser) -> pd.DataFrame:
    frames = []
    for p in sorted(directory.glob("*.json")):
        frames.append(normaliser(json.loads(p.read_text(encoding="utf-8"))))
    if not frames:
        raise RuntimeError(f"no daily files under {directory}")
    return pd.concat(frames, ignore_index=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bundle-dir", default="data/external/elexon_v19")
    ap.add_argument("--out-dir", default="data/processed/v19_elexon")
    ap.add_argument("--report-dir", default="reports/v19_real_market")
    ap.add_argument("--start-date", default="2026-01-01")
    ap.add_argument("--end-date-exclusive", default="2026-08-16")
    ap.add_argument("--min-coverage", type=float, default=0.95)
    args = ap.parse_args()

    bundle = Path(args.bundle_dir)
    out = Path(args.out_dir); out.mkdir(parents=True, exist_ok=True)
    report = Path(args.report_dir); report.mkdir(parents=True, exist_ok=True)

    mid = read_daily(bundle / "mid_daily", normalise_mid)
    system = read_daily(bundle / "system_price_daily", normalise_system_prices)
    # A repeated API response across adjacent date checkpoints is not expected
    # with settlement-date queries; fail rather than silently keeping one copy.
    if mid.duplicated(["settlement_date", "settlement_period", "data_provider"]).any():
        raise RuntimeError("duplicate MID rows after daily concatenation")
    if system.duplicated(["settlement_date", "settlement_period"]).any():
        raise RuntimeError("duplicate system-price rows after daily concatenation")
    reference = build_volume_weighted_market_reference(mid)
    audit = audit_elexon_bundle(
        reference=reference,
        system_prices=system,
        start_date=args.start_date,
        end_date_exclusive=args.end_date_exclusive,
        gate=ElexonCoverageGate(minimum_expected_coverage=args.min_coverage),
    )

    mid.to_parquet(out / "mid.parquet", index=False, compression="zstd")
    system.to_parquet(out / "system_prices.parquet", index=False, compression="zstd")
    reference.to_parquet(out / "reference_market.parquet", index=False, compression="zstd")
    dump_json(report / "elexon_coverage_audit.json", audit)
    pd.DataFrame([audit]).to_csv(report / "elexon_coverage_audit.csv", index=False)
    print(json.dumps(audit, indent=2))
    if audit["status"] != "PASS_REAL":
        raise SystemExit("Elexon real-data coverage gate blocked")


if __name__ == "__main__":
    main()
