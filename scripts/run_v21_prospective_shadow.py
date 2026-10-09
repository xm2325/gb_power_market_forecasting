#!/usr/bin/env python3
"""Score unchanged v0.20 models on post-lock prospective market data."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import duckdb
import pandas as pd

from gb_power_market.elexon_v19 import build_information_safe_market_frame
from gb_power_market.prospective_v21 import score_prospective_shadow

HORIZONS = {"30m": 30, "2h": 120, "6h": 360, "12h": 720}


def select_latest_current_neso(
    con: duckdb.DuckDBPyConnection,
    *,
    horizon_minutes: int,
    start_utc: pd.Timestamp,
    end_exclusive_utc: pd.Timestamp,
) -> pd.DataFrame:
    cutoff = horizon_minutes + 30
    start_end = start_utc + pd.Timedelta(minutes=30)
    end_target = end_exclusive_utc + pd.Timedelta(minutes=30)
    raw = con.execute(
        f"""
        WITH eligible AS (
          SELECT *, row_number() OVER (
            PARTITION BY target_end_utc ORDER BY publish_time_utc DESC
          ) AS vintage_rank
          FROM current_forecasts
          WHERE target_end_utc >= TIMESTAMPTZ '{start_end.isoformat()}'
            AND target_end_utc < TIMESTAMPTZ '{end_target.isoformat()}'
            AND publish_time_utc <= target_end_utc - INTERVAL '{cutoff} minutes'
        )
        SELECT target_end_utc, publish_time_utc, wind_mw, wind_capacity_mw,
               solar_mw, solar_capacity_mw, source_regime
        FROM eligible
        WHERE vintage_rank = 1
        ORDER BY target_end_utc
        """
    ).df()
    if raw.empty:
        raise RuntimeError(f"no eligible current-regime NESO forecasts for {horizon_minutes}m")
    raw["target_end_utc"] = pd.to_datetime(raw["target_end_utc"], utc=True)
    raw["publish_time_utc"] = pd.to_datetime(raw["publish_time_utc"], utc=True)
    raw["target_start_utc"] = raw["target_end_utc"] - pd.Timedelta(minutes=30)
    raw["decision_time_utc"] = raw["target_start_utc"] - pd.Timedelta(minutes=horizon_minutes)
    if (raw["publish_time_utc"] > raw["decision_time_utc"]).any():
        raise AssertionError("future NESO forecast escaped prospective cutoff")
    raw["neso_publish_time_utc"] = raw["publish_time_utc"]
    raw["neso_source_regime"] = raw["source_regime"].astype(str)
    raw["neso_forecast_age_minutes"] = (
        (raw["decision_time_utc"] - raw["publish_time_utc"]).dt.total_seconds() / 60.0
    )
    raw["neso_embedded_wind_forecast_mw"] = raw["wind_mw"].astype(float)
    raw["neso_embedded_wind_capacity_mw"] = raw["wind_capacity_mw"].astype(float)
    raw["neso_embedded_solar_forecast_mw"] = raw["solar_mw"].astype(float)
    raw["neso_embedded_solar_capacity_mw"] = raw["solar_capacity_mw"].astype(float)
    return raw[[
        "target_start_utc",
        "neso_publish_time_utc",
        "neso_source_regime",
        "neso_forecast_age_minutes",
        "neso_embedded_wind_forecast_mw",
        "neso_embedded_wind_capacity_mw",
        "neso_embedded_solar_forecast_mw",
        "neso_embedded_solar_capacity_mw",
    ]]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--elexon-dir", default="data/processed/v21/elexon")
    ap.add_argument("--neso-current", default="data/processed/v21/forecast_current.parquet")
    ap.add_argument("--model-state", default="reports/locked/V0_21_FROZEN_MODEL_STATE.json")
    ap.add_argument("--start-utc", default="2026-08-15T07:30:00Z")
    ap.add_argument("--end-exclusive-utc", required=True)
    ap.add_argument("--out-dir", default="reports/v21_shadow")
    args = ap.parse_args()

    start = pd.Timestamp(args.start_utc)
    end = pd.Timestamp(args.end_exclusive_utc)
    if start.tzinfo is None or end.tzinfo is None:
        raise ValueError("shadow boundaries must be timezone-aware")

    model_bundle = json.loads(Path(args.model_state).read_text(encoding="utf-8"))
    if model_bundle.get("status") != "FROZEN_MODEL_STATE_EXPORTED":
        raise RuntimeError("frozen model-state bundle is not locked/exported")

    reference = pd.read_parquet(Path(args.elexon_dir) / "reference_market.parquet")
    reference["target_start_utc"] = pd.to_datetime(reference["target_start_utc"], utc=True)

    con = duckdb.connect()
    con.execute(
        f"CREATE VIEW current_forecasts AS SELECT * FROM read_parquet('{Path(args.neso_current).as_posix()}')"
    )

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    summary = []
    results = {}
    for label, horizon in HORIZONS.items():
        state = model_bundle["states"][label]
        price = build_information_safe_market_frame(reference, horizon_minutes=horizon)
        if state["selected_family"] == "PRICE_PLUS_NESO_LEVELS":
            neso = select_latest_current_neso(
                con,
                horizon_minutes=horizon,
                start_utc=start,
                end_exclusive_utc=end,
            )
            frame = price.merge(neso, on="target_start_utc", how="left")
        else:
            frame = price
        result = score_prospective_shadow(
            frame,
            frozen_state=state,
            start_utc=start,
            end_exclusive_utc=end,
        )
        results[label] = result
        summary.append({
            "horizon": label,
            "status": result["status"],
            "selected_family": result.get("selected_family"),
            "rows": result.get("prospective_window", {}).get("rows", result.get("rows")),
            "coverage": result.get("prospective_window", {}).get("coverage", result.get("coverage")),
            "future_neso_publications": result.get("information_audit", {}).get("future_neso_publications"),
            "reference_mae_gbp_mwh": result.get("reference", {}).get("mae_gbp_mwh"),
            "frozen_model_mae_gbp_mwh": result.get("frozen_model", {}).get("mae_gbp_mwh"),
            "improvement_pct": result.get("improvement_vs_previous_settlement_day_pct"),
            "interval_coverage": result.get("interval", {}).get("empirical_coverage"),
            "action_rate": result.get("abstention", {}).get("action_rate"),
            "bootstrap_status": result.get("daily_block_bootstrap", {}).get("status"),
        })
        (out / f"prospective_shadow_{label}.json").write_text(
            json.dumps(result, indent=2, default=str), encoding="utf-8"
        )
        print(
            f"{label}: {result['status']} | rows={summary[-1]['rows']} | "
            f"MAE={summary[-1]['frozen_model_mae_gbp_mwh']}",
            flush=True,
        )

    pd.DataFrame(summary).to_csv(out / "prospective_shadow_summary.csv", index=False)
    overall = {
        "version": "0.21.0",
        "status": "SHADOW_REPLAY_COMPLETE",
        "source_model_state_sha256": "e9952aa88ca56b85f4d595bfe918cdc589ac0048d717d3fb3d9210361eb18918",
        "source_evidence_id_sha256": model_bundle["source_evidence_id_sha256"],
        "prospective_start_utc": start.isoformat(),
        "end_exclusive_utc": end.isoformat(),
        "horizons": results,
        "claim_boundary": (
            "No family, alpha, coefficient, scaler or conformal quantile is changed in this replay. "
            "Rows before the predeclared 672-half-hour gate are shadow diagnostics only."
        ),
    }
    (out / "prospective_shadow_all.json").write_text(
        json.dumps(overall, indent=2, default=str), encoding="utf-8"
    )


if __name__ == "__main__":
    main()
