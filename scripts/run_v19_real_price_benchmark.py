#!/usr/bin/env python3
"""Run the real Elexon + NESO price experiment with a fixed final window.

This script intentionally separates the market-price target from the settlement
system price. The target is the volume-weighted APX/N2EX Market Index Price.
System price is used only to define pre-final stress regimes for diagnostics.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

from gb_power_market.elexon_v19 import build_information_safe_market_frame
from gb_power_market.fixed_market_experiment import FixedMarketWindows, run_fixed_window_real_price_experiment
from gb_power_market.market_stress import apply_spread_regimes, fit_spread_regime_thresholds

HORIZONS = {"30m": 30, "2h": 120, "6h": 360, "12h": 720}


def load_selected_neso(con: duckdb.DuckDBPyConnection, horizon_minutes: int, windows: FixedMarketWindows) -> pd.DataFrame:
    w = windows.parsed()
    cutoff = horizon_minutes + 30  # target end is one settlement period after price target start
    start_end = w["train_start_utc"] + pd.Timedelta(minutes=30)
    final_end = w["final_end_exclusive_utc"] + pd.Timedelta(minutes=30)
    q = f"""
    WITH eligible AS (
      SELECT *,
             row_number() OVER (PARTITION BY target_end_utc ORDER BY publish_time_utc DESC) AS vintage_rank
      FROM stitched
      WHERE target_end_utc >= TIMESTAMPTZ '{start_end.isoformat()}'
        AND target_end_utc < TIMESTAMPTZ '{final_end.isoformat()}'
        AND publish_time_utc <= target_end_utc - INTERVAL '{cutoff} minutes'
    )
    SELECT target_end_utc, publish_time_utc, wind_mw, wind_capacity_mw,
           solar_mw, solar_capacity_mw, source_regime, vintage_rank
    FROM eligible WHERE vintage_rank <= 2
    ORDER BY target_end_utc, vintage_rank
    """
    raw = con.execute(q).df()
    if raw.empty:
        raise RuntimeError(f"no eligible NESO vintages for {horizon_minutes}m")
    raw["target_end_utc"] = pd.to_datetime(raw["target_end_utc"], utc=True)
    raw["publish_time_utc"] = pd.to_datetime(raw["publish_time_utc"], utc=True)
    rows = []
    for target_end, g in raw.groupby("target_end_utc", sort=True):
        g = g.sort_values("vintage_rank")
        latest = g.iloc[0]
        previous = g.iloc[1] if len(g) > 1 else None
        target_start = target_end - pd.Timedelta(minutes=30)
        decision = target_start - pd.Timedelta(minutes=horizon_minutes)
        if latest["publish_time_utc"] > decision:
            raise AssertionError("future NESO vintage escaped SQL cutoff")
        row = {
            "target_start_utc": target_start,
            "neso_publish_time_utc": latest["publish_time_utc"],
            "neso_source_regime": str(latest["source_regime"]),
            "neso_forecast_age_minutes": float((decision - latest["publish_time_utc"]).total_seconds() / 60.0),
            "neso_embedded_wind_forecast_mw": float(latest["wind_mw"]),
            "neso_embedded_wind_capacity_mw": float(latest["wind_capacity_mw"]),
            "neso_embedded_solar_forecast_mw": float(latest["solar_mw"]),
            "neso_embedded_solar_capacity_mw": float(latest["solar_capacity_mw"]),
        }
        if previous is not None:
            wd = float(latest["wind_mw"] - previous["wind_mw"])
            sd = float(latest["solar_mw"] - previous["solar_mw"])
            row.update({
                "neso_previous_publish_time_utc": previous["publish_time_utc"],
                "neso_embedded_wind_revision_delta_mw": wd,
                "neso_embedded_wind_abs_revision_delta_mw": abs(wd),
                "neso_embedded_solar_revision_delta_mw": sd,
                "neso_embedded_solar_abs_revision_delta_mw": abs(sd),
            })
        else:
            row.update({
                "neso_previous_publish_time_utc": pd.NaT,
                "neso_embedded_wind_revision_delta_mw": np.nan,
                "neso_embedded_wind_abs_revision_delta_mw": np.nan,
                "neso_embedded_solar_revision_delta_mw": np.nan,
                "neso_embedded_solar_abs_revision_delta_mw": np.nan,
            })
        rows.append(row)
    return pd.DataFrame(rows)


def price_stress_diagnostics(result: dict, reference: pd.DataFrame, system: pd.DataFrame, windows: FixedMarketWindows) -> dict:
    w = windows.parsed()
    market = reference[["target_start_utc", "reference_market_price_gbp_mwh"]].merge(
        system[["target_start_utc", "system_buy_price_gbp_mwh", "system_sell_price_gbp_mwh"]],
        on="target_start_utc", how="inner",
    )
    market["system_price_gbp_mwh"] = (market["system_buy_price_gbp_mwh"] + market["system_sell_price_gbp_mwh"]) / 2.0
    market["absolute_spread_gbp_mwh"] = (market["system_price_gbp_mwh"] - market["reference_market_price_gbp_mwh"]).abs()
    calibration_spread = market[
        (market["target_start_utc"] >= w["calibration_start_utc"])
        & (market["target_start_utc"] < w["final_start_utc"])
    ]
    thresholds = fit_spread_regime_thresholds(calibration_spread)
    final_rows = pd.DataFrame(result.get("row_level_final", []))
    if final_rows.empty:
        return {"status": "BLOCKED", "reason": "row-level final predictions unavailable"}
    final_rows["target_start_utc"] = pd.to_datetime(final_rows["target_start_utc"], utc=True)
    j = final_rows.merge(market[["target_start_utc", "absolute_spread_gbp_mwh"]], on="target_start_utc", how="left")
    j = apply_spread_regimes(j, thresholds)
    j["abs_error_gbp_mwh"] = (j["actual_gbp_mwh"] - j["prediction_gbp_mwh"]).abs()
    j["reference_abs_error_gbp_mwh"] = (j["actual_gbp_mwh"] - j["previous_settlement_day_gbp_mwh"]).abs()
    by = {}
    for label in ["normal", "high", "extreme"]:
        g = j[j["spread_regime"].astype(str) == label].dropna(subset=["abs_error_gbp_mwh", "reference_abs_error_gbp_mwh"])
        if len(g):
            ref = float(g["reference_abs_error_gbp_mwh"].mean())
            dep = float(g["abs_error_gbp_mwh"].mean())
            by[label] = {
                "n_rows": int(len(g)),
                "reference_mae_gbp_mwh": ref,
                "deployed_mae_gbp_mwh": dep,
                "deployed_improvement_pct": float(100.0 * (ref - dep) / ref) if ref else None,
                "mean_absolute_system_market_spread_gbp_mwh": float(g["absolute_spread_gbp_mwh"].mean()),
            }
    return {
        "status": "PASS" if j["absolute_spread_gbp_mwh"].notna().mean() >= 0.95 else "BLOCKED",
        "thresholds_fit_on": "pre-final calibration window only",
        "thresholds": thresholds,
        "final_price_coverage": float(j["absolute_spread_gbp_mwh"].notna().mean()),
        "by_spread_regime": by,
        "interpretation": "Price-forecast MAE conditioned on historical system-vs-market spread; not trading P&L.",
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--neso-dir", default="data/processed/v18_neso")
    ap.add_argument("--elexon-dir", default="data/processed/v19_elexon")
    ap.add_argument("--out-dir", default="reports/v19_real_market")
    args = ap.parse_args()
    neso = Path(args.neso_dir); elexon = Path(args.elexon_dir); out = Path(args.out_dir); out.mkdir(parents=True, exist_ok=True)

    reference = pd.read_parquet(elexon / "reference_market.parquet")
    system = pd.read_parquet(elexon / "system_prices.parquet")
    reference["target_start_utc"] = pd.to_datetime(reference["target_start_utc"], utc=True)
    system["target_start_utc"] = pd.to_datetime(system["target_start_utc"], utc=True)

    con = duckdb.connect()
    con.execute(f"CREATE VIEW legacy AS SELECT * FROM read_parquet('{(neso/'forecast_legacy.parquet').as_posix()}')")
    con.execute(f"CREATE VIEW current AS SELECT * FROM read_parquet('{(neso/'forecast_current.parquet').as_posix()}')")
    switch = con.execute("SELECT min(target_end_utc) FROM current").fetchone()[0]
    switch_sql = str(switch).replace("+00:00", "+00")
    con.execute(f"CREATE VIEW stitched AS SELECT * FROM legacy WHERE target_end_utc < TIMESTAMPTZ '{switch_sql}' UNION ALL SELECT * FROM current WHERE target_end_utc >= TIMESTAMPTZ '{switch_sql}'")

    windows = FixedMarketWindows()
    results = {}
    for name, h in HORIZONS.items():
        price = build_information_safe_market_frame(reference, horizon_minutes=h)
        selected = load_selected_neso(con, h, windows)
        frame = price.merge(selected, on="target_start_utc", how="left")
        result = run_fixed_window_real_price_experiment(frame, horizon_minutes=h, windows=windows, return_row_level=True)
        result["stress_diagnostics"] = price_stress_diagnostics(result, reference, system, windows)
        # Keep the main JSON compact; row-level output is persisted separately.
        rows = result.pop("row_level_final", [])
        pd.DataFrame(rows).to_parquet(out / f"final_predictions_{name}.parquet", index=False, compression="zstd")
        (out / f"real_price_benchmark_{name}.json").write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
        results[name] = result
        print(f"{name}: {result['claim_gate']['status']} | final n={result['rows']['final']} | source={result['selection']['deployed_source']}")

    summary_rows = []
    for name, r in results.items():
        f = r["final_test"]["deployed"]
        ref = r["final_test"]["previous_settlement_day_reference"]
        summary_rows.append({
            "horizon": name,
            "claim_gate": r["claim_gate"]["status"],
            "selected_family": r["selection"]["selected_family"],
            "promoted": r["selection"]["promoted"],
            "deployed_source": r["selection"]["deployed_source"],
            "final_rows": r["rows"]["final"],
            "final_coverage": r["rows"]["final_coverage"],
            "reference_mae_gbp_mwh": ref["mae_gbp_mwh"],
            "deployed_mae_gbp_mwh": f["mae_gbp_mwh"],
            "deployed_p95_abs_error_gbp_mwh": f["p95_abs_error_gbp_mwh"],
            "interval_coverage": r["final_test"]["interval"]["empirical_coverage"],
            "abstention_action_rate": r["final_test"]["abstention"]["action_rate"],
        })
    pd.DataFrame(summary_rows).to_csv(out / "real_price_benchmark_summary.csv", index=False)
    overall = {
        "version": "0.19.0",
        "data_status": "REAL_ELEXON_PLUS_REAL_NESO_NETWORK_SNAPSHOT",
        "forecast_system_switch_target_end_utc": str(switch),
        "horizons": results,
        "claim_policy": "Only horizons with claim_gate=PASS_REAL may supply numerical price-forecast evidence. No metric is trading P&L.",
    }
    (out / "real_price_benchmark_all.json").write_text(json.dumps(overall, indent=2, default=str), encoding="utf-8")


if __name__ == "__main__":
    main()
