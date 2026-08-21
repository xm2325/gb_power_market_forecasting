#!/usr/bin/env python3
"""Continuously replay unchanged v0.20 models over historical OOS and later market data."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import duckdb
import pandas as pd

from gb_power_market.elexon_v19 import build_information_safe_market_frame
from gb_power_market.forward_monitor_v24 import (
    LOCKED_FINAL_START_UTC,
    daily_metrics,
    score_frozen_forward_rows,
    segment_metrics,
)

HORIZONS = {"30m": 30, "2h": 120, "6h": 360, "12h": 720}
FROZEN_MODEL_STATE_FILE_SHA256 = "e9952aa88ca56b85f4d595bfe918cdc589ac0048d717d3fb3d9210361eb18918"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


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
        raise AssertionError("future NESO forecast escaped continuous-monitor cutoff")
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
    ap.add_argument("--elexon-reference", required=True)
    ap.add_argument("--neso-current", required=True)
    ap.add_argument("--model-state", default="reports/locked/V0_21_FROZEN_MODEL_STATE.json")
    ap.add_argument("--start-utc", default=LOCKED_FINAL_START_UTC.isoformat())
    ap.add_argument("--end-exclusive-utc", required=True)
    ap.add_argument("--out-dir", default="reports/v24_forward")
    args = ap.parse_args()

    start = pd.Timestamp(args.start_utc)
    end = pd.Timestamp(args.end_exclusive_utc)
    if start.tzinfo is None or end.tzinfo is None:
        raise ValueError("continuous-monitor boundaries must be timezone-aware")
    start = start.tz_convert("UTC")
    end = end.tz_convert("UTC")

    state_path = Path(args.model_state)
    if sha256_file(state_path) != FROZEN_MODEL_STATE_FILE_SHA256:
        raise RuntimeError("frozen model-state file SHA-256 changed")
    model_bundle = json.loads(state_path.read_text(encoding="utf-8"))
    if model_bundle.get("status") != "FROZEN_MODEL_STATE_EXPORTED":
        raise RuntimeError("frozen model-state bundle is not locked/exported")

    reference = pd.read_parquet(args.elexon_reference)
    reference["target_start_utc"] = pd.to_datetime(reference["target_start_utc"], utc=True)

    con = duckdb.connect()
    con.execute(
        f"CREATE VIEW current_forecasts AS SELECT * FROM read_parquet('{Path(args.neso_current).as_posix()}')"
    )

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    overall: dict[str, object] = {
        "version": "0.24.0",
        "status": "CONTINUOUS_FORWARD_MONITOR_COMPLETE",
        "model_state_file_sha256": FROZEN_MODEL_STATE_FILE_SHA256,
        "source_evidence_id_sha256": model_bundle["source_evidence_id_sha256"],
        "monitor_start_utc": start.isoformat(),
        "end_exclusive_utc": end.isoformat(),
        "evidence_policy": {
            "locked_final_full": "historical out-of-sample evidence; immutable v0.20 benchmark remains authoritative",
            "august_1_to_latest": "recent-regime monitoring that mixes historical final and post-lock rows",
            "post_lock_to_latest": "forward monitoring of the unchanged frozen model",
            "rolling_windows": "operational monitoring only; not independent model-selection evidence",
            "model_changes": "any model change starts a new versioned forward segment; old curves are never rewritten",
        },
        "horizons": {},
    }

    segment_table: list[dict[str, object]] = []
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

        rows, audit = score_frozen_forward_rows(
            frame,
            frozen_state=state,
            start_utc=start,
            end_exclusive_utc=end,
        )
        segments = segment_metrics(rows, monitor_end_exclusive_utc=end)
        days = daily_metrics(rows)

        row_path = out / f"forward_rows_{label}.csv"
        daily_path = out / f"daily_metrics_{label}.csv"
        rows.to_csv(row_path, index=False)
        days.to_csv(daily_path, index=False)
        result = {
            "horizon": label,
            "selected_family": state["selected_family"],
            "alpha": state["alpha"],
            "audit": audit,
            "segments": segments,
            "row_output": row_path.name,
            "daily_output": daily_path.name,
        }
        overall["horizons"][label] = result
        (out / f"forward_monitor_{label}.json").write_text(
            json.dumps(result, indent=2, default=str), encoding="utf-8"
        )
        for segment_name, metrics in segments.items():
            segment_table.append({"horizon": label, "segment": segment_name, **metrics})
        post = segments["post_lock_to_latest"]
        print(
            f"{label}: coverage={audit['coverage']:.3f} | post-lock rows={post['rows']} | "
            f"post-lock model MAE={post.get('frozen_model_mae_gbp_mwh')} | "
            f"improvement={post.get('improvement_pct')}",
            flush=True,
        )

    pd.DataFrame(segment_table).to_csv(out / "segment_summary.csv", index=False)
    (out / "forward_monitor_all.json").write_text(
        json.dumps(overall, indent=2, default=str), encoding="utf-8"
    )


if __name__ == "__main__":
    main()
