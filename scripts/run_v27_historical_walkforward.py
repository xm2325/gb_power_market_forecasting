#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

from gb_power_market.elexon_v19 import build_information_safe_market_frame
from gb_power_market.fixed_market_experiment import FixedMarketWindows, run_fixed_window_real_price_experiment
from gb_power_market.historical_walkforward_v27 import (
    EVIDENCE_CLASS,
    WalkForwardConfig,
    apply_candidate_suite,
    build_fold_schedule,
    config_payload,
    summarise_score_rows,
)


def load_selected_neso(
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
          FROM stitched
          WHERE target_end_utc >= TIMESTAMPTZ '{start_end.isoformat()}'
            AND target_end_utc < TIMESTAMPTZ '{end_target.isoformat()}'
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
        raise RuntimeError("no eligible NESO vintages for historical walk-forward")
    raw["target_end_utc"] = pd.to_datetime(raw["target_end_utc"], utc=True)
    raw["publish_time_utc"] = pd.to_datetime(raw["publish_time_utc"], utc=True)

    rows: list[dict] = []
    for target_end, group in raw.groupby("target_end_utc", sort=True):
        g = group.sort_values("vintage_rank")
        latest = g.iloc[0]
        previous = g.iloc[1] if len(g) > 1 else None
        target_start = target_end - pd.Timedelta(minutes=30)
        decision = target_start - pd.Timedelta(minutes=horizon_minutes)
        if latest["publish_time_utc"] > decision:
            raise AssertionError("future NESO vintage escaped rolling-origin cutoff")
        row = {
            "target_start_utc": target_start,
            "neso_publish_time_utc": latest["publish_time_utc"],
            "neso_source_regime": str(latest["source_regime"]),
            "neso_forecast_age_minutes": float(
                (decision - latest["publish_time_utc"]).total_seconds() / 60.0
            ),
            "neso_embedded_wind_forecast_mw": float(latest["wind_mw"]),
            "neso_embedded_wind_capacity_mw": float(latest["wind_capacity_mw"]),
            "neso_embedded_solar_forecast_mw": float(latest["solar_mw"]),
            "neso_embedded_solar_capacity_mw": float(latest["solar_capacity_mw"]),
        }
        if previous is None:
            row.update(
                {
                    "neso_previous_publish_time_utc": pd.NaT,
                    "neso_embedded_wind_revision_delta_mw": np.nan,
                    "neso_embedded_wind_abs_revision_delta_mw": np.nan,
                    "neso_embedded_solar_revision_delta_mw": np.nan,
                    "neso_embedded_solar_abs_revision_delta_mw": np.nan,
                }
            )
        else:
            wind_delta = float(latest["wind_mw"] - previous["wind_mw"])
            solar_delta = float(latest["solar_mw"] - previous["solar_mw"])
            row.update(
                {
                    "neso_previous_publish_time_utc": previous["publish_time_utc"],
                    "neso_embedded_wind_revision_delta_mw": wind_delta,
                    "neso_embedded_wind_abs_revision_delta_mw": abs(wind_delta),
                    "neso_embedded_solar_revision_delta_mw": solar_delta,
                    "neso_embedded_solar_abs_revision_delta_mw": abs(solar_delta),
                }
            )
        rows.append(row)
    result = pd.DataFrame(rows)
    future = pd.to_datetime(result["neso_publish_time_utc"], utc=True) > (
        pd.to_datetime(result["target_start_utc"], utc=True) - pd.Timedelta(minutes=horizon_minutes)
    )
    if future.any():
        raise AssertionError("historical walk-forward contains post-decision NESO publication")
    return result


def period_class(target: pd.Series) -> pd.Series:
    ts = pd.to_datetime(target, utc=True)
    return pd.Series(
        np.where(
            ts < pd.Timestamp("2026-07-01T00:00:00Z"),
            "EARLIER_TEMPORAL_BACKTEST_MAY_JUNE",
            "LATER_HISTORICAL_ROBUSTNESS_JULY_AUGUST",
        ),
        index=target.index,
    )


def monthly_summary(rows: pd.DataFrame) -> list[dict]:
    x = rows.copy()
    x["month"] = pd.to_datetime(x["target_start_utc"], utc=True).dt.strftime("%Y-%m")
    out = []
    for month, group in x.groupby("month", sort=True):
        summary = summarise_score_rows(group)
        out.append({"month": month, **summary})
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--neso-dir", default="data/processed/v18_neso")
    ap.add_argument("--elexon-reference", default="data/processed/v19_elexon/reference_market.parquet")
    ap.add_argument("--out-dir", default="reports/v27_historical_walkforward")
    ap.add_argument("--score-start-utc", default="2026-05-01T00:00:00Z")
    ap.add_argument("--score-end-exclusive-utc", default="2026-08-23T22:00:00Z")
    ap.add_argument("--fold-days", type=int, default=7)
    args = ap.parse_args()

    cfg = WalkForwardConfig(
        score_start_utc=args.score_start_utc,
        score_end_exclusive_utc=args.score_end_exclusive_utc,
        fold_days=args.fold_days,
    )
    schedule = build_fold_schedule(cfg)
    train_start = pd.Timestamp(cfg.train_start_utc)
    score_end = pd.Timestamp(cfg.score_end_exclusive_utc)

    neso_dir = Path(args.neso_dir)
    reference = pd.read_parquet(args.elexon_reference)
    reference["target_start_utc"] = pd.to_datetime(reference["target_start_utc"], utc=True)

    con = duckdb.connect()
    con.execute(
        f"CREATE VIEW legacy AS SELECT * FROM read_parquet('{(neso_dir / 'forecast_legacy.parquet').as_posix()}')"
    )
    con.execute(
        f"CREATE VIEW current AS SELECT * FROM read_parquet('{(neso_dir / 'forecast_current.parquet').as_posix()}')"
    )
    switch = con.execute("SELECT min(target_end_utc) FROM current").fetchone()[0]
    switch_sql = str(switch).replace("+00:00", "+00")
    con.execute(
        "CREATE VIEW stitched AS "
        f"SELECT * FROM legacy WHERE target_end_utc < TIMESTAMPTZ '{switch_sql}' "
        "UNION ALL "
        f"SELECT * FROM current WHERE target_end_utc >= TIMESTAMPTZ '{switch_sql}'"
    )

    selected = load_selected_neso(
        con,
        horizon_minutes=cfg.horizon_minutes,
        start_utc=train_start,
        end_exclusive_utc=score_end,
    )
    price = build_information_safe_market_frame(reference, horizon_minutes=cfg.horizon_minutes)
    full_frame = price.merge(selected, on="target_start_utc", how="left")
    full_frame["target_start_utc"] = pd.to_datetime(full_frame["target_start_utc"], utc=True)
    full_frame = full_frame[
        (full_frame["target_start_utc"] >= train_start)
        & (full_frame["target_start_utc"] < score_end)
    ].copy()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    fold_dir = out_dir / "folds"
    fold_dir.mkdir(parents=True, exist_ok=True)

    all_score_rows: list[pd.DataFrame] = []
    fold_summaries: list[dict] = []
    for fold in schedule:
        windows = FixedMarketWindows(
            train_start_utc=fold["train_start_utc"],
            selection_start_utc=fold["selection_start_utc"],
            calibration_start_utc=fold["calibration_start_utc"],
            final_start_utc=fold["adaptation_warmup_start_utc"],
            final_end_exclusive_utc=fold["score_end_exclusive_utc"],
        )
        fold_end = pd.Timestamp(fold["score_end_exclusive_utc"])
        fold_frame = full_frame[full_frame["target_start_utc"] < fold_end].copy()
        if fold_frame["target_start_utc"].max() >= fold_end:
            raise AssertionError("future target row entered rolling-origin fold input")

        base_result = run_fixed_window_real_price_experiment(
            fold_frame,
            horizon_minutes=cfg.horizon_minutes,
            windows=windows,
            return_row_level=True,
        )
        raw_rows = pd.DataFrame(base_result.pop("row_level_final"))
        if raw_rows.empty:
            raise RuntimeError(f"fold {fold['fold']} produced no base final rows")
        target = pd.to_datetime(raw_rows["target_start_utc"], utc=True)
        base_rows = pd.DataFrame(
            {
                "target_start_utc": target,
                "decision_time_utc": target - pd.Timedelta(minutes=cfg.horizon_minutes),
                "realised_price_gbp_mwh": raw_rows["actual_gbp_mwh"].astype(float),
                "frozen_prediction_gbp_mwh": raw_rows["prediction_gbp_mwh"].astype(float),
                "previous_settlement_day_reference_gbp_mwh": raw_rows[
                    "previous_settlement_day_gbp_mwh"
                ].astype(float),
                "interval_lower_gbp_mwh": raw_rows["lower_gbp_mwh"].astype(float),
                "interval_upper_gbp_mwh": raw_rows["upper_gbp_mwh"].astype(float),
            }
        )
        candidate_rows = apply_candidate_suite(base_rows)
        score_start = pd.Timestamp(fold["score_start_utc"])
        score_rows = candidate_rows[
            (candidate_rows["target_start_utc"] >= score_start)
            & (candidate_rows["target_start_utc"] < fold_end)
        ].copy()
        expected = len(pd.date_range(score_start, fold_end, freq="30min", inclusive="left"))
        if len(score_rows) != expected:
            raise RuntimeError(
                f"fold {fold['fold']} score coverage incomplete: rows={len(score_rows)} expected={expected}"
            )
        score_rows["fold"] = int(fold["fold"])
        score_rows["base_selected_family"] = base_result["selection"]["selected_family"]
        score_rows["base_deployed_source"] = base_result["selection"]["deployed_source"]
        score_rows["base_promoted"] = bool(base_result["selection"]["promoted"])
        score_rows["historical_period_class"] = period_class(score_rows["target_start_utc"])
        score_rows["evidence_class"] = EVIDENCE_CLASS
        all_score_rows.append(score_rows)

        fold_summary = {
            **fold,
            "base_selection": base_result["selection"],
            "base_rows": base_result["rows"],
            "base_purge": base_result["purge"],
            "information_audit": base_result["information_audit"],
            "score": summarise_score_rows(score_rows),
            "fold_input_max_target_utc": fold_frame["target_start_utc"].max().isoformat(),
            "future_labels_passed_to_fold_runner": False,
        }
        fold_summaries.append(fold_summary)
        (fold_dir / f"fold_{int(fold['fold']):02d}.json").write_text(
            json.dumps(fold_summary, indent=2, default=str), encoding="utf-8"
        )
        print(
            f"fold {fold['fold']:02d}: {fold['score_start_utc']} -> {fold['score_end_exclusive_utc']} | "
            f"base={base_result['selection']['deployed_source']} | "
            f"v27 MAE={fold_summary['score']['models']['v0.27']['mae_gbp_mwh']:.3f} | "
            f"base MAE={fold_summary['score']['models']['causal_base']['mae_gbp_mwh']:.3f}",
            flush=True,
        )

    rows = pd.concat(all_score_rows, ignore_index=True).sort_values("target_start_utc").reset_index(drop=True)
    if rows["target_start_utc"].duplicated().any():
        raise RuntimeError("rolling-origin scored targets overlap across folds")
    overall = summarise_score_rows(rows)
    may_june = rows[rows["target_start_utc"] < pd.Timestamp("2026-07-01T00:00:00Z")]
    july_aug = rows[rows["target_start_utc"] >= pd.Timestamp("2026-07-01T00:00:00Z")]
    payload = {
        "version": "0.27.0-historical-walkforward-1",
        "status": "HISTORICAL_ASOF_ROLLING_ORIGIN_COMPLETE",
        "config": config_payload(cfg),
        "forecast_system_switch_target_end_utc": str(switch),
        "folds": fold_summaries,
        "overall": overall,
        "earlier_temporal_may_june": summarise_score_rows(may_june) if len(may_june) else None,
        "later_historical_july_august": summarise_score_rows(july_aug) if len(july_aug) else None,
        "monthly": monthly_summary(rows),
        "claim_boundary": (
            "Every score target is generated by a rolling-origin base pipeline fit/selected only on prior data, "
            "with decision-time NESO vintages and a causal adaptation warm-up. The v0.27 structure was designed "
            "later, so this is historical pseudo-prospective robustness evidence, not live forward evidence or "
            "untouched confirmatory validation."
        ),
    }
    rows.to_csv(out_dir / "historical_walkforward_rows.csv", index=False, lineterminator="\n")
    pd.DataFrame(
        [
            {
                "fold": x["fold"],
                "score_start_utc": x["score_start_utc"],
                "score_end_exclusive_utc": x["score_end_exclusive_utc"],
                "base_selected_family": x["base_selection"]["selected_family"],
                "base_deployed_source": x["base_selection"]["deployed_source"],
                "base_promoted": x["base_selection"]["promoted"],
                "base_mae_gbp_mwh": x["score"]["models"]["causal_base"]["mae_gbp_mwh"],
                "v25_mae_gbp_mwh": x["score"]["models"]["v0.25"]["mae_gbp_mwh"],
                "v26_mae_gbp_mwh": x["score"]["models"]["v0.26"]["mae_gbp_mwh"],
                "v27_mae_gbp_mwh": x["score"]["models"]["v0.27"]["mae_gbp_mwh"],
                "previous_day_mae_gbp_mwh": x["score"]["models"]["previous_day"]["mae_gbp_mwh"],
            }
            for x in fold_summaries
        ]
    ).to_csv(out_dir / "fold_summary.csv", index=False)
    (out_dir / "historical_walkforward_summary.json").write_text(
        json.dumps(payload, indent=2, default=str), encoding="utf-8"
    )
    print(json.dumps({"overall": overall, "monthly": payload["monthly"]}, indent=2, default=str))


if __name__ == "__main__":
    main()
