#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

EVIDENCE_CLASS = "HISTORICAL_ASOF_ROLLING_ORIGIN_NOT_LIVE_FORWARD"
MODEL_COLUMNS = {
    "causal_base": "frozen_prediction_gbp_mwh",
    "v0.25": "adaptive_prediction_gbp_mwh",
    "v0.26": "v26_prediction_gbp_mwh",
    "v0.27": "v27_prediction_gbp_mwh",
    "previous_day": "previous_settlement_day_reference_gbp_mwh",
}


def _moving_block_indices(n: int, block_length: int, rng: np.random.Generator) -> np.ndarray:
    if n <= 0:
        raise ValueError("n must be positive")
    if block_length <= 0 or block_length > n:
        raise ValueError("block_length must be in [1, n]")
    n_blocks = int(np.ceil(n / block_length))
    max_start = n - block_length
    starts = rng.integers(0, max_start + 1, size=n_blocks)
    offsets = np.arange(block_length)
    return (starts[:, None] + offsets[None, :]).reshape(-1)[:n]


def paired_block_bootstrap(
    comparator_abs_error: np.ndarray,
    candidate_abs_error: np.ndarray,
    *,
    block_length: int,
    n_resamples: int,
    seed: int,
) -> dict:
    comp = np.asarray(comparator_abs_error, dtype=float)
    cand = np.asarray(candidate_abs_error, dtype=float)
    if comp.shape != cand.shape or comp.ndim != 1 or len(comp) == 0:
        raise ValueError("paired error arrays must be non-empty 1-D arrays of equal length")
    if not (np.isfinite(comp).all() and np.isfinite(cand).all()):
        raise ValueError("paired error arrays must be finite")
    if n_resamples < 100:
        raise ValueError("n_resamples must be at least 100")

    paired_gain = comp - cand  # positive means v0.27 has lower absolute error
    observed = float(paired_gain.mean())
    rng = np.random.default_rng(seed)
    boot = np.empty(n_resamples, dtype=float)
    for i in range(n_resamples):
        idx = _moving_block_indices(len(paired_gain), block_length, rng)
        boot[i] = float(paired_gain[idx].mean())
    lower, upper = np.quantile(boot, [0.025, 0.975])
    return {
        "rows": int(len(paired_gain)),
        "block_length_rows": int(block_length),
        "block_length_hours": float(block_length / 2.0),
        "n_resamples": int(n_resamples),
        "seed": int(seed),
        "observed_paired_mae_gain_gbp_mwh": observed,
        "ci95_lower_gbp_mwh": float(lower),
        "ci95_upper_gbp_mwh": float(upper),
        "bootstrap_probability_gain_gt_zero": float((boot > 0.0).mean()),
        "interval_classification": (
            "SUPPORTS_V27_LOWER_MAE" if lower > 0.0 else
            "SUPPORTS_V27_HIGHER_MAE" if upper < 0.0 else
            "INTERVAL_INCLUDES_ZERO"
        ),
    }


def _validate_rows(rows: pd.DataFrame) -> pd.DataFrame:
    required = {
        "target_start_utc",
        "realised_price_gbp_mwh",
        "evidence_class",
        *MODEL_COLUMNS.values(),
    }
    missing = sorted(required - set(rows.columns))
    if missing:
        raise ValueError(f"historical rows missing columns: {missing}")
    x = rows.copy()
    target = pd.to_datetime(x["target_start_utc"], utc=True, errors="raise")
    x["target_start_utc"] = target
    x = x.sort_values("target_start_utc").reset_index(drop=True)
    if x["target_start_utc"].duplicated().any():
        raise ValueError("historical target timestamps are duplicated")
    expected = pd.date_range(target.min(), target.max() + pd.Timedelta(minutes=30), freq="30min", inclusive="left")
    if not x["target_start_utc"].equals(pd.Series(expected, name="target_start_utc")):
        raise ValueError("historical target timestamps are not contiguous half-hours")
    if x["evidence_class"].nunique() != 1 or x["evidence_class"].iloc[0] != EVIDENCE_CLASS:
        raise ValueError("historical evidence class changed")
    return x


def analyse(
    rows: pd.DataFrame,
    folds: pd.DataFrame,
    *,
    block_lengths: tuple[int, ...] = (48, 336),
    n_resamples: int = 10000,
    seed: int = 20260826,
) -> dict:
    x = _validate_rows(rows)
    y = x["realised_price_gbp_mwh"].to_numpy(float)
    abs_errors = {
        name: np.abs(x[col].to_numpy(float) - y)
        for name, col in MODEL_COLUMNS.items()
    }
    if not np.isfinite(y).all() or not all(np.isfinite(v).all() for v in abs_errors.values()):
        raise ValueError("historical predictions/targets must be finite")

    model_metrics = {
        name: {
            "mae_gbp_mwh": float(err.mean()),
            "p95_abs_error_gbp_mwh": float(np.quantile(err, 0.95)),
        }
        for name, err in abs_errors.items()
    }
    comparisons = {}
    for comparator in ("causal_base", "v0.26", "v0.25", "previous_day"):
        comp = model_metrics[comparator]["mae_gbp_mwh"]
        cand = model_metrics["v0.27"]["mae_gbp_mwh"]
        by_block = {}
        for block in block_lengths:
            by_block[str(block)] = paired_block_bootstrap(
                abs_errors[comparator],
                abs_errors["v0.27"],
                block_length=block,
                n_resamples=n_resamples,
                seed=seed + block + sum(ord(c) for c in comparator),
            )
        comparisons[comparator] = {
            "observed_mae_gain_gbp_mwh": float(comp - cand),
            "observed_improvement_pct": float(100.0 * (comp - cand) / comp) if comp else None,
            "bootstrap_by_block_length_rows": by_block,
        }

    fold_required = {"fold", "base_mae_gbp_mwh", "v25_mae_gbp_mwh", "v26_mae_gbp_mwh", "v27_mae_gbp_mwh", "previous_day_mae_gbp_mwh"}
    missing_fold = sorted(fold_required - set(folds.columns))
    if missing_fold:
        raise ValueError(f"fold summary missing columns: {missing_fold}")
    weekly = {}
    fold_cols = {
        "causal_base": "base_mae_gbp_mwh",
        "v0.26": "v26_mae_gbp_mwh",
        "v0.25": "v25_mae_gbp_mwh",
        "previous_day": "previous_day_mae_gbp_mwh",
    }
    for comparator, col in fold_cols.items():
        diff = folds[col].to_numpy(float) - folds["v27_mae_gbp_mwh"].to_numpy(float)
        weekly[comparator] = {
            "folds": int(len(diff)),
            "v27_better_folds": int((diff > 0.0).sum()),
            "v27_worse_folds": int((diff < 0.0).sum()),
            "ties": int((diff == 0.0).sum()),
            "mean_fold_mae_gain_gbp_mwh": float(diff.mean()),
            "median_fold_mae_gain_gbp_mwh": float(np.median(diff)),
        }

    return {
        "version": "0.27.0-historical-uncertainty-1",
        "status": "HISTORICAL_UNCERTAINTY_ANALYSIS_COMPLETE",
        "evidence_class": EVIDENCE_CLASS,
        "rows": int(len(x)),
        "start_utc": x["target_start_utc"].min().isoformat(),
        "end_exclusive_utc": (x["target_start_utc"].max() + pd.Timedelta(minutes=30)).isoformat(),
        "model_metrics": model_metrics,
        "comparisons_vs_v27": comparisons,
        "weekly_consistency": weekly,
        "primary_block_length_rows": int(block_lengths[0]),
        "sensitivity_block_length_rows": int(block_lengths[1]) if len(block_lengths) > 1 else None,
        "claim_boundary": (
            "Retrospective historical as-of rolling-origin robustness evidence only. The v0.27 structure was designed "
            "after these dates, so bootstrap intervals quantify temporal uncertainty in this backtest; they do not "
            "convert it into live-forward or untouched confirmatory evidence. No predictive rule is changed by this analysis."
        ),
    }


def render_markdown(result: dict) -> str:
    m = result["model_metrics"]
    lines = [
        "# v0.27 historical rolling-origin uncertainty",
        "",
        f"Evidence class: `{result['evidence_class']}`.",
        "",
        f"Window: {result['start_utc']} to {result['end_exclusive_utc']} (end-exclusive), {result['rows']:,} half-hours.",
        "",
        "| Model | MAE (£/MWh) | P95 abs error (£/MWh) |",
        "|---|---:|---:|",
    ]
    for name in ("causal_base", "v0.25", "v0.26", "v0.27", "previous_day"):
        lines.append(f"| {name} | {m[name]['mae_gbp_mwh']:.3f} | {m[name]['p95_abs_error_gbp_mwh']:.3f} |")
    lines += ["", "## Paired time-block uncertainty", ""]
    for comparator in ("causal_base", "v0.26", "v0.25", "previous_day"):
        c = result["comparisons_vs_v27"][comparator]
        primary = c["bootstrap_by_block_length_rows"][str(result["primary_block_length_rows"])]
        sensitivity = c["bootstrap_by_block_length_rows"][str(result["sensitivity_block_length_rows"])]
        lines += [
            f"### v0.27 vs {comparator}",
            "",
            f"Observed MAE gain: **{c['observed_mae_gain_gbp_mwh']:.3f} £/MWh** ({c['observed_improvement_pct']:.2f}%). Positive means v0.27 is better.",
            f"24h-block 95% interval: **[{primary['ci95_lower_gbp_mwh']:.3f}, {primary['ci95_upper_gbp_mwh']:.3f}] £/MWh**; `{primary['interval_classification']}`.",
            f"7-day-block sensitivity: **[{sensitivity['ci95_lower_gbp_mwh']:.3f}, {sensitivity['ci95_upper_gbp_mwh']:.3f}] £/MWh**; `{sensitivity['interval_classification']}`.",
            "",
        ]
    lines += ["## Weekly consistency", ""]
    for comparator, w in result["weekly_consistency"].items():
        lines.append(
            f"- vs {comparator}: v0.27 better in {w['v27_better_folds']}/{w['folds']} folds, worse in {w['v27_worse_folds']}/{w['folds']}, ties {w['ties']}."
        )
    lines += ["", "## Claim boundary", "", result["claim_boundary"], ""]
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rows", default="reports/v27_historical_walkforward/historical_walkforward_rows.csv")
    ap.add_argument("--folds", default="reports/v27_historical_walkforward/fold_summary.csv")
    ap.add_argument("--out-json", default="reports/v27_historical_walkforward/historical_uncertainty.json")
    ap.add_argument("--out-md", default="docs/V0_27_HISTORICAL_ROLLING_ORIGIN.md")
    ap.add_argument("--resamples", type=int, default=10000)
    ap.add_argument("--seed", type=int, default=20260826)
    args = ap.parse_args()

    result = analyse(
        pd.read_csv(args.rows),
        pd.read_csv(args.folds),
        n_resamples=args.resamples,
        seed=args.seed,
    )
    out_json = Path(args.out_json)
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(result, indent=2), encoding="utf-8")
    out_md = Path(args.out_md)
    out_md.parent.mkdir(parents=True, exist_ok=True)
    out_md.write_text(render_markdown(result), encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
