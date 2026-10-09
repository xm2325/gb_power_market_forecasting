#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

import duckdb
import pandas as pd

from gb_power_market.elexon_v19 import build_information_safe_market_frame
from gb_power_market.fixed_market_experiment import FixedMarketWindows, run_fixed_window_real_price_experiment
from gb_power_market.historical_walkforward_v27 import (
    EVIDENCE_CLASS,
    WalkForwardConfig,
    apply_candidate_suite,
    build_deployed_base_rows,
    build_fold_schedule,
    config_payload,
    summarise_score_rows,
)
from run_v27_historical_walkforward import load_selected_neso, monthly_summary, period_class


def create_causal_stitched_view(con: duckdb.DuckDBPyConnection) -> None:
    """Union both forecast systems and resolve overlap at publication-time granularity.

    Around the source transition a target can legitimately have an older legacy
    vintage and a newer current-system vintage. Historical as-of replay must use
    whichever publication actually existed by the decision time; hard-cutting by
    target date can delete legitimate pre-decision history.
    """
    con.execute(
        """
        CREATE VIEW stitched AS
        SELECT * EXCLUDE (source_priority, source_rank)
        FROM (
          SELECT *, row_number() OVER (
            PARTITION BY target_end_utc, publish_time_utc
            ORDER BY source_priority DESC
          ) AS source_rank
          FROM (
            SELECT *, 1 AS source_priority FROM legacy
            UNION ALL
            SELECT *, 2 AS source_priority FROM current
          ) u
        ) ranked
        WHERE source_rank = 1
        """
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--neso-dir", default="data/processed/v27_historical_neso")
    ap.add_argument("--elexon-reference", default="data/processed/v27_historical_elexon/reference_market.parquet")
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
    con.execute(f"CREATE VIEW legacy AS SELECT * FROM read_parquet('{(neso_dir / 'forecast_legacy.parquet').as_posix()}')")
    con.execute(f"CREATE VIEW current AS SELECT * FROM read_parquet('{(neso_dir / 'forecast_current.parquet').as_posix()}')")
    current_first_target = con.execute("SELECT min(target_end_utc) FROM current").fetchone()[0]
    create_causal_stitched_view(con)

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

        # Selection remains on the exact common-support protocol used by the base experiment.
        base_result = run_fixed_window_real_price_experiment(
            fold_frame,
            horizon_minutes=cfg.horizon_minutes,
            windows=windows,
            return_row_level=False,
        )
        # Once deployment is fixed, score every row supported by the deployed family.
        base_rows = build_deployed_base_rows(
            fold_frame,
            fold=fold,
            selection=base_result["selection"],
            horizon_minutes=cfg.horizon_minutes,
        )
        candidate_rows = apply_candidate_suite(base_rows)
        score_start = pd.Timestamp(fold["score_start_utc"])
        score_rows = candidate_rows[
            (candidate_rows["target_start_utc"] >= score_start)
            & (candidate_rows["target_start_utc"] < fold_end)
        ].copy()
        expected = len(pd.date_range(score_start, fold_end, freq="30min", inclusive="left"))
        if len(score_rows) != expected:
            missing = pd.date_range(score_start, fold_end, freq="30min", inclusive="left").difference(
                pd.DatetimeIndex(score_rows["target_start_utc"])
            )
            raise RuntimeError(
                f"fold {fold['fold']} deployed-family score coverage incomplete: rows={len(score_rows)} "
                f"expected={expected} missing={[x.isoformat() for x in missing[:12]]}"
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
            "base_rows_common_support": base_result["rows"],
            "base_purge": base_result["purge"],
            "information_audit": base_result["information_audit"],
            "deployed_family_score_rows": int(len(score_rows)),
            "score": summarise_score_rows(score_rows),
            "fold_input_max_target_utc": fold_frame["target_start_utc"].max().isoformat(),
            "future_labels_passed_to_fold_runner": False,
            "final_score_support_rule": "DEPLOYED_FAMILY_FEATURES_ONLY_AFTER_COMMON_SUPPORT_SELECTION",
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
        "version": "0.27.0-historical-walkforward-2",
        "status": "HISTORICAL_ASOF_ROLLING_ORIGIN_COMPLETE",
        "config": config_payload(cfg),
        "current_source_first_target_end_utc": str(current_first_target),
        "source_transition_rule": (
            "Union legacy and current forecasts; at identical target/publication timestamps prefer current, then "
            "select the latest publication actually available by each decision time."
        ),
        "final_score_support_rule": "DEPLOYED_FAMILY_FEATURES_ONLY_AFTER_COMMON_SUPPORT_SELECTION",
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
    pd.DataFrame([
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
    ]).to_csv(out_dir / "fold_summary.csv", index=False)
    (out_dir / "historical_walkforward_summary.json").write_text(
        json.dumps(payload, indent=2, default=str), encoding="utf-8"
    )
    print(json.dumps({"overall": overall, "monthly": payload["monthly"]}, indent=2, default=str))


if __name__ == "__main__":
    main()
