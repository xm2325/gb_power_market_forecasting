from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from scripts.analyse_v27_historical_uncertainty import (
    EVIDENCE_CLASS,
    analyse,
    paired_block_bootstrap,
)


ROWS = Path("reports/v27_historical_walkforward/historical_walkforward_rows.csv")
FOLDS = Path("reports/v27_historical_walkforward/fold_summary.csv")


def test_block_bootstrap_is_deterministic_and_positive_for_known_gain() -> None:
    comparator = np.tile(np.array([3.0, 4.0, 5.0, 6.0]), 100)
    candidate = comparator - 0.5
    a = paired_block_bootstrap(comparator, candidate, block_length=8, n_resamples=500, seed=7)
    b = paired_block_bootstrap(comparator, candidate, block_length=8, n_resamples=500, seed=7)
    assert a == b
    assert a["observed_paired_mae_gain_gbp_mwh"] == 0.5
    assert a["ci95_lower_gbp_mwh"] > 0.0
    assert a["interval_classification"] == "SUPPORTS_V27_LOWER_MAE"


def test_block_bootstrap_detects_uncertain_mixed_gain() -> None:
    comparator = np.ones(480)
    candidate = np.ones(480)
    candidate[::2] += 0.5
    candidate[1::2] -= 0.5
    result = paired_block_bootstrap(comparator, candidate, block_length=48, n_resamples=500, seed=11)
    assert abs(result["observed_paired_mae_gain_gbp_mwh"]) < 1e-12
    assert result["ci95_lower_gbp_mwh"] <= 0.0 <= result["ci95_upper_gbp_mwh"]
    assert result["interval_classification"] == "INTERVAL_INCLUDES_ZERO"


def test_committed_historical_evidence_has_exact_scope_and_weekly_consistency() -> None:
    result = analyse(
        pd.read_csv(ROWS),
        pd.read_csv(FOLDS),
        block_lengths=(48, 336),
        n_resamples=200,
        seed=20260826,
    )
    assert result["evidence_class"] == EVIDENCE_CLASS
    assert result["rows"] == 5516
    assert result["start_utc"] == "2026-05-01T00:00:00+00:00"
    assert result["end_exclusive_utc"] == "2026-08-23T22:00:00+00:00"
    assert abs(result["model_metrics"]["v0.27"]["mae_gbp_mwh"] - 18.578152729094757) < 1e-9
    assert abs(result["model_metrics"]["v0.26"]["mae_gbp_mwh"] - 18.380394170256366) < 1e-9
    assert result["weekly_consistency"]["causal_base"]["v27_better_folds"] == 12
    assert result["weekly_consistency"]["causal_base"]["v27_worse_folds"] == 5
    assert result["weekly_consistency"]["v0.26"]["v27_better_folds"] == 7
    assert result["weekly_consistency"]["v0.26"]["v27_worse_folds"] == 10
    assert result["comparisons_vs_v27"]["causal_base"]["observed_mae_gain_gbp_mwh"] > 0.0
    assert result["comparisons_vs_v27"]["v0.26"]["observed_mae_gain_gbp_mwh"] < 0.0
