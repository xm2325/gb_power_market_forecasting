#!/usr/bin/env python3
"""Run frozen-window real NESO as-of forecast benchmarks with DuckDB.

No model is selected on the final window. For each horizon the latest archive
vintage available by the simulated decision time is selected, joined to official
2026 outturn, and evaluated once on the pre-existing v0.8 final window.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import duckdb

HORIZONS = {"30m": 1, "2h": 4, "6h": 12, "12h": 24}
FROZEN_START_TARGET_END = "2026-07-12 12:30:00+00:00"
FROZEN_END_TARGET_END_EXCLUSIVE = "2026-08-15 08:00:00+00:00"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default="data/processed/v18_neso")
    ap.add_argument("--out-dir", default="reports/v18_real_archive")
    ap.add_argument("--min-coverage", type=float, default=0.95)
    ap.add_argument("--min-rows", type=int, default=500)
    args = ap.parse_args()
    d = Path(args.data_dir); out = Path(args.out_dir); out.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    con.execute(f"CREATE VIEW legacy AS SELECT * FROM read_parquet('{(d/'forecast_legacy.parquet').as_posix()}')")
    con.execute(f"CREATE VIEW current AS SELECT * FROM read_parquet('{(d/'forecast_current.parquet').as_posix()}')")
    con.execute(f"CREATE VIEW outturn_historic AS SELECT *, 1 AS source_priority FROM read_parquet('{(d/'outturn_historic_2026.parquet').as_posix()}')")
    con.execute(f"CREATE VIEW outturn_update AS SELECT *, 2 AS source_priority FROM read_parquet('{(d/'outturn_update.parquet').as_posix()}')")
    con.execute("""CREATE VIEW outturn AS SELECT * EXCLUDE (rn, source_priority) FROM (SELECT *, row_number() OVER (PARTITION BY target_end_utc ORDER BY source_priority DESC) rn FROM (SELECT * FROM outturn_historic UNION ALL SELECT * FROM outturn_update)) WHERE rn=1""")
    switch = con.execute("SELECT min(target_end_utc) FROM current").fetchone()[0]
    switch_sql = str(switch).replace("+00:00", "+00")
    con.execute(f"CREATE VIEW stitched AS SELECT * FROM legacy WHERE target_end_utc < TIMESTAMPTZ '{switch_sql}' UNION ALL SELECT * FROM current WHERE target_end_utc >= TIMESTAMPTZ '{switch_sql}'")

    expected_targets = int((duckdb.execute(f"SELECT date_diff(\'minute\', TIMESTAMPTZ \'{FROZEN_START_TARGET_END}\', TIMESTAMPTZ \'{FROZEN_END_TARGET_END_EXCLUSIVE}\') / 30").fetchone()[0]))
    actual_targets = int(con.execute(f"SELECT count(*) FROM outturn WHERE target_end_utc >= TIMESTAMPTZ \'{FROZEN_START_TARGET_END}\' AND target_end_utc < TIMESTAMPTZ \'{FROZEN_END_TARGET_END_EXCLUSIVE}\'").fetchone()[0])
    actual_outturn_coverage = float(actual_targets / expected_targets) if expected_targets else 0.0
    results = []
    for name, periods in HORIZONS.items():
        cutoff = (periods + 1) * 30
        con.execute("DROP TABLE IF EXISTS selected")
        con.execute(f"""
            CREATE TEMP TABLE selected AS
            SELECT * EXCLUDE (rn) FROM (
              SELECT f.*, row_number() OVER (PARTITION BY target_end_utc ORDER BY publish_time_utc DESC) rn
              FROM stitched f
              WHERE publish_time_utc <= target_end_utc - INTERVAL '{cutoff} minutes'
            ) WHERE rn=1
        """)
        row = con.execute(f"""
            WITH a AS (
              SELECT * FROM outturn
              WHERE target_end_utc >= TIMESTAMPTZ '{FROZEN_START_TARGET_END}'
                AND target_end_utc < TIMESTAMPTZ '{FROZEN_END_TARGET_END_EXCLUSIVE}'
            ), j AS (
              SELECT a.*, s.publish_time_utc, s.wind_mw, s.solar_mw,
                     s.target_end_utc - INTERVAL '{cutoff} minutes' AS decision_time_utc
              FROM a LEFT JOIN selected s USING(target_end_utc)
            )
            SELECT
              count(*) AS n_targets,
              count(publish_time_utc) AS n_asof,
              sum(CASE WHEN publish_time_utc > decision_time_utc THEN 1 ELSE 0 END) AS future_publications,
              avg(abs(wind_mw-actual_wind_mw)) AS wind_mae,
              sqrt(avg(pow(wind_mw-actual_wind_mw,2))) AS wind_rmse,
              avg(wind_mw-actual_wind_mw) AS wind_bias,
              quantile_cont(abs(wind_mw-actual_wind_mw),0.95) AS wind_p95_abs,
              avg(abs(solar_mw-actual_solar_mw)) AS solar_mae,
              sqrt(avg(pow(solar_mw-actual_solar_mw,2))) AS solar_rmse,
              avg(solar_mw-actual_solar_mw) AS solar_bias,
              quantile_cont(abs(solar_mw-actual_solar_mw),0.95) AS solar_p95_abs
            FROM j
        """).fetchone()
        cols = [x[0] for x in con.description]
        r = dict(zip(cols, row))
        r.update({"horizon": name, "horizon_periods": periods, "cutoff_minutes_to_target_end": cutoff})
        r["forecast_coverage_on_available_outturn"] = float(r["n_asof"] / r["n_targets"]) if r["n_targets"] else 0.0
        r["expected_final_window_targets"] = expected_targets
        r["actual_outturn_targets"] = actual_targets
        r["actual_outturn_coverage"] = actual_outturn_coverage
        r["end_to_end_coverage"] = float(r["n_asof"] / expected_targets) if expected_targets else 0.0
        r["claim_gate"] = "PASS_REAL" if (expected_targets >= args.min_rows and actual_outturn_coverage >= args.min_coverage and r["end_to_end_coverage"] >= args.min_coverage and int(r["future_publications"] or 0) == 0) else "BLOCKED"
        results.append(r)

    payload = {
        "version": "0.18.0",
        "data_status": "REAL_NESO_NETWORK_SNAPSHOT",
        "forecast_system_switch_target_end_utc": str(switch),
        "frozen_final_window": {"start_target_end_utc": FROZEN_START_TARGET_END, "end_target_end_exclusive_utc": FROZEN_END_TARGET_END_EXCLUSIVE},
        "results": results,
        "claim_policy": "Numerical results become CV-eligible only for horizons with claim_gate=PASS_REAL. This is forecast accuracy, not trading P&L.",
    }
    (out / "real_neso_asof_benchmark.json").write_text(json.dumps(payload, indent=2, default=str))
    con.execute("CREATE TABLE result_table AS SELECT * FROM read_json_auto(?)", [(out / "real_neso_asof_benchmark.json").as_posix()]) if False else None
    import pandas as pd
    pd.DataFrame(results).to_csv(out / "real_neso_asof_benchmark.csv", index=False)
    print(json.dumps(payload, indent=2, default=str))

if __name__ == "__main__":
    main()
