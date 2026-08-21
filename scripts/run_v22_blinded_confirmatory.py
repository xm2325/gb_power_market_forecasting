#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

import duckdb
import pandas as pd

from gb_power_market.confirmatory_v22 import evaluate_blinded_confirmatory
from gb_power_market.elexon_v19 import build_information_safe_market_frame

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
        return pd.DataFrame(columns=[
            "target_start_utc", "neso_publish_time_utc", "neso_source_regime",
            "neso_forecast_age_minutes", "neso_embedded_wind_forecast_mw",
            "neso_embedded_wind_capacity_mw", "neso_embedded_solar_forecast_mw",
            "neso_embedded_solar_capacity_mw",
        ])
    raw["target_end_utc"] = pd.to_datetime(raw["target_end_utc"], utc=True)
    raw["publish_time_utc"] = pd.to_datetime(raw["publish_time_utc"], utc=True)
    raw["target_start_utc"] = raw["target_end_utc"] - pd.Timedelta(minutes=30)
    raw["decision_time_utc"] = raw["target_start_utc"] - pd.Timedelta(minutes=horizon_minutes)
    if (raw["publish_time_utc"] > raw["decision_time_utc"]).any():
        raise AssertionError("future NESO forecast escaped v0.22 cutoff")
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
        "target_start_utc", "neso_publish_time_utc", "neso_source_regime",
        "neso_forecast_age_minutes", "neso_embedded_wind_forecast_mw",
        "neso_embedded_wind_capacity_mw", "neso_embedded_solar_forecast_mw",
        "neso_embedded_solar_capacity_mw",
    ]]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--elexon-reference", default="data/processed/v22/reference_market.parquet")
    ap.add_argument("--neso-current", default="data/processed/v22/forecast_current.parquet")
    ap.add_argument("--model-state", default="reports/locked/V0_21_FROZEN_MODEL_STATE.json")
    ap.add_argument("--available-end-exclusive-utc", required=True)
    ap.add_argument("--out-dir", default="reports/v22_confirmatory")
    args = ap.parse_args()

    available_end = pd.Timestamp(args.available_end_exclusive_utc)
    if available_end.tzinfo is None:
        raise ValueError("available end must be timezone-aware")
    model_bundle = json.loads(Path(args.model_state).read_text(encoding="utf-8"))
    if model_bundle.get("status") != "FROZEN_MODEL_STATE_EXPORTED":
        raise RuntimeError("model-state bundle is not the locked v0.21 export")

    reference = pd.read_parquet(args.elexon_reference)
    reference["target_start_utc"] = pd.to_datetime(reference["target_start_utc"], utc=True)
    con = duckdb.connect()
    con.execute(
        f"CREATE VIEW current_forecasts AS SELECT * FROM read_parquet('{Path(args.neso_current).as_posix()}')"
    )

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    results = {}
    summary = []
    for label, horizon in HORIZONS.items():
        state = model_bundle["states"][label]
        price = build_information_safe_market_frame(reference, horizon_minutes=horizon)
        if state["selected_family"] == "PRICE_PLUS_NESO_LEVELS":
            neso = select_latest_current_neso(
                con,
                horizon_minutes=horizon,
                start_utc=pd.Timestamp("2026-08-20T23:00:00Z"),
                end_exclusive_utc=available_end,
            )
            frame = price.merge(neso, on="target_start_utc", how="left")
        else:
            frame = price
        result = evaluate_blinded_confirmatory(
            frame,
            frozen_state=state,
            available_end_exclusive_utc=available_end,
        )
        results[label] = result
        w = result.get("confirmatory_window", result.get("availability_gate", {}).get("confirmatory_window", {}))
        summary.append({
            "horizon": label,
            "status": result["status"],
            "complete_rows_so_far": w.get("complete_rows_so_far"),
            "rows_remaining_to_reveal": w.get("rows_remaining_to_reveal"),
            "coverage_so_far": w.get("coverage_so_far"),
            "future_neso_publications": (
                result.get("information_audit", result.get("availability_gate", {}).get("information_audit", {}))
            ).get("future_neso_publications"),
            "classification": result.get("classification", {}).get("status"),
        })
        (out / f"confirmatory_{label}.json").write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
        print(f"{label}: {result['status']} | rows={summary[-1]['complete_rows_so_far']} | remaining={summary[-1]['rows_remaining_to_reveal']}")

    import pandas as pd2
    pd2.DataFrame(summary).to_csv(out / "confirmatory_summary.csv", index=False)
    overall = {
        "version": "0.22.0",
        "status": "CONFIRMATORY_CHECK_COMPLETE",
        "source_model_state_sha256": "e9952aa88ca56b85f4d595bfe918cdc589ac0048d717d3fb3d9210361eb18918",
        "available_end_exclusive_utc": available_end.isoformat(),
        "horizons": results,
        "blinding_policy": (
            "Before the exact 672-half-hour window is complete, horizon payloads expose only availability, coverage and publication timing."
        ),
    }
    (out / "confirmatory_all.json").write_text(json.dumps(overall, indent=2, default=str), encoding="utf-8")


if __name__ == "__main__":
    main()
