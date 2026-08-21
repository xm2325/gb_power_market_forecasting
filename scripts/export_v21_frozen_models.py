#!/usr/bin/env python3
"""Export exact v0.20 pre-final model state from the locked successful artifact.

The export is not a new fit or a new model choice. Family, alpha and conformal
quantile come from the locked replay specification. This script reconstructs the
same purged common-row fit used by v0.20, verifies the calibration quantile, and
checks predictions against the immutable final-prediction artifact before
serialising model coefficients/scalers for prospective inference.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

from gb_power_market.elexon_v19 import build_information_safe_market_frame
from gb_power_market.fixed_market_experiment import FixedMarketWindows
from gb_power_market.prospective_v21 import fit_frozen_replay_state, model_from_frozen_state


def select_neso_vintages(
    con: duckdb.DuckDBPyConnection,
    horizon_minutes: int,
    windows: FixedMarketWindows,
) -> pd.DataFrame:
    w = windows.parsed()
    cutoff = horizon_minutes + 30
    start_end = w["train_start_utc"] + pd.Timedelta(minutes=30)
    final_end = w["final_end_exclusive_utc"] + pd.Timedelta(minutes=30)
    raw = con.execute(
        f"""
        WITH eligible AS (
          SELECT *,
                 row_number() OVER (
                   PARTITION BY target_end_utc
                   ORDER BY publish_time_utc DESC
                 ) AS vintage_rank
          FROM stitched
          WHERE target_end_utc >= TIMESTAMPTZ '{start_end.isoformat()}'
            AND target_end_utc < TIMESTAMPTZ '{final_end.isoformat()}'
            AND publish_time_utc <= target_end_utc - INTERVAL '{cutoff} minutes'
        )
        SELECT target_end_utc, publish_time_utc, wind_mw, wind_capacity_mw,
               solar_mw, solar_capacity_mw, source_regime, vintage_rank
        FROM eligible
        WHERE vintage_rank <= 2
        ORDER BY target_end_utc, vintage_rank
        """
    ).df()
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
            raise AssertionError("future NESO vintage escaped frozen export cutoff")
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
        if previous is None:
            row.update({
                "neso_previous_publish_time_utc": pd.NaT,
                "neso_embedded_wind_revision_delta_mw": np.nan,
                "neso_embedded_wind_abs_revision_delta_mw": np.nan,
                "neso_embedded_solar_revision_delta_mw": np.nan,
                "neso_embedded_solar_abs_revision_delta_mw": np.nan,
            })
        else:
            wd = float(latest["wind_mw"] - previous["wind_mw"])
            sd = float(latest["solar_mw"] - previous["solar_mw"])
            row.update({
                "neso_previous_publish_time_utc": previous["publish_time_utc"],
                "neso_embedded_wind_revision_delta_mw": wd,
                "neso_embedded_wind_abs_revision_delta_mw": abs(wd),
                "neso_embedded_solar_revision_delta_mw": sd,
                "neso_embedded_solar_abs_revision_delta_mw": abs(sd),
            })
        rows.append(row)
    return pd.DataFrame(rows)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--artifact-root", required=True)
    ap.add_argument("--spec", default="reports/locked/V0_21_FROZEN_REPLAY_SPEC.json")
    ap.add_argument("--out", default="reports/locked/V0_21_FROZEN_MODEL_STATE.json")
    ap.add_argument("--prediction-tolerance", type=float, default=1e-8)
    args = ap.parse_args()

    root = Path(args.artifact_root)
    spec = json.loads(Path(args.spec).read_text(encoding="utf-8"))
    if spec["source_evidence_id_sha256"] != "7c5f78b98c8ed877ab4c5cefa8a40b3068abb74cb2062ecf677f319d74a14661":
        raise RuntimeError("replay spec is not tied to locked v0.20 evidence")

    neso = root / "data/processed/v18_neso"
    elexon = root / "data/processed/v19_elexon"
    benchmark = root / "reports/v19_real_market"
    for path in [
        neso / "forecast_legacy.parquet",
        neso / "forecast_current.parquet",
        elexon / "reference_market.parquet",
    ]:
        if not path.exists():
            raise FileNotFoundError(path)

    reference = pd.read_parquet(elexon / "reference_market.parquet")
    reference["target_start_utc"] = pd.to_datetime(reference["target_start_utc"], utc=True)

    con = duckdb.connect()
    con.execute(f"CREATE VIEW legacy AS SELECT * FROM read_parquet('{(neso / 'forecast_legacy.parquet').as_posix()}')")
    con.execute(f"CREATE VIEW current AS SELECT * FROM read_parquet('{(neso / 'forecast_current.parquet').as_posix()}')")
    switch = con.execute("SELECT min(target_end_utc) FROM current").fetchone()[0]
    switch_sql = str(switch).replace("+00:00", "+00")
    con.execute(
        "CREATE VIEW stitched AS "
        f"SELECT * FROM legacy WHERE target_end_utc < TIMESTAMPTZ '{switch_sql}' "
        "UNION ALL "
        f"SELECT * FROM current WHERE target_end_utc >= TIMESTAMPTZ '{switch_sql}'"
    )

    windows = FixedMarketWindows()
    parsed = windows.parsed()
    states = {}
    checks = {}
    for label, entry in spec["horizons"].items():
        horizon = int(entry["horizon_minutes"])
        selected = select_neso_vintages(con, horizon, windows)
        price = build_information_safe_market_frame(reference, horizon_minutes=horizon)
        frame = price.merge(selected, on="target_start_utc", how="left")
        state = fit_frozen_replay_state(
            frame,
            horizon_minutes=horizon,
            selected_family=str(entry["selected_family"]),
            alpha=float(entry["alpha"]),
            locked_conformal_q_gbp_mwh=float(entry["conformal_absolute_residual_quantile_gbp_mwh"]),
        )

        old_pred_path = benchmark / f"final_predictions_{label}.parquet"
        old = pd.read_parquet(old_pred_path)
        old["target_start_utc"] = pd.to_datetime(old["target_start_utc"], utc=True)
        final = frame[
            (frame["target_start_utc"] >= parsed["final_start_utc"])
            & (frame["target_start_utc"] < parsed["final_end_exclusive_utc"])
        ].dropna(subset=state["features"]).copy()
        model = model_from_frozen_state(state)
        replay = pd.DataFrame({
            "target_start_utc": final["target_start_utc"],
            "replayed_prediction_gbp_mwh": model.predict(final[state["features"]].to_numpy(float)),
        })
        joined = old[["target_start_utc", "prediction_gbp_mwh"]].merge(replay, on="target_start_utc", how="inner")
        if len(joined) != len(old):
            raise RuntimeError(f"{label}: replay row count {len(joined)} != locked prediction count {len(old)}")
        max_diff = float(np.max(np.abs(joined["prediction_gbp_mwh"] - joined["replayed_prediction_gbp_mwh"])))
        if max_diff > args.prediction_tolerance:
            raise RuntimeError(f"{label}: frozen replay prediction mismatch {max_diff}")
        states[label] = state
        checks[label] = {
            "locked_prediction_rows": int(len(old)),
            "maximum_absolute_prediction_difference_gbp_mwh": max_diff,
            "prediction_tolerance_gbp_mwh": float(args.prediction_tolerance),
            "status": "PASS",
        }
        print(f"{label}: exact replay PASS; max prediction diff={max_diff:.3e}", flush=True)

    payload = {
        "version": "0.21.0",
        "status": "FROZEN_MODEL_STATE_EXPORTED",
        "source_workflow_run_id": int(spec["source_workflow_run_id"]),
        "source_artifact_id": int(spec["source_artifact_id"]),
        "source_artifact_sha256": spec["source_artifact_sha256"],
        "source_evidence_id_sha256": spec["source_evidence_id_sha256"],
        "forecast_system_switch_target_end_utc": str(switch),
        "states": states,
        "locked_prediction_replay_checks": checks,
        "boundary": "Coefficients/scalers are reconstructed from pre-final development rows only and exactly reproduce the immutable v0.20 final predictions. No prospective outcomes are used.",
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    digest = sha256(out)
    out.with_suffix(out.suffix + ".sha256").write_text(f"{digest}  {out.name}\n", encoding="utf-8")
    print(out)
    print(digest)


if __name__ == "__main__":
    main()
