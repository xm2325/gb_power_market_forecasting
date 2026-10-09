import numpy as np

from gb_power_market.price_tail import TailGuardRule, evaluate_tail_guard, fit_large_move_threshold, tail_metrics


def test_tail_threshold_and_metrics_are_deterministic():
    last = np.zeros(100)
    actual = np.arange(100, dtype=float)
    pred = actual + 1.0
    threshold = fit_large_move_threshold(actual, last, 0.90)
    out = tail_metrics(actual, pred, last, large_move_threshold_gbp_mwh=threshold)
    assert threshold == np.quantile(actual, 0.90)
    assert out["n_large_move_rows"] == 10
    assert out["large_move_mae_gbp_mwh"] == 1.0


def test_tail_guard_can_block_mean_acceptable_challenger_on_large_moves():
    n = 200
    last = np.zeros(n)
    actual = np.concatenate([np.ones(180), np.full(20, 100.0)])
    baseline = actual + 10.0
    challenger = actual.copy()
    challenger[:180] += 1.0
    challenger[180:] += 25.0
    threshold = 50.0
    out = evaluate_tail_guard(
        actual, challenger, baseline, last,
        threshold_gbp_mwh=threshold,
        rule=TailGuardRule(minimum_large_move_rows=20, maximum_large_move_mae_degradation_pct=5.0),
    )
    assert np.abs(actual - challenger).mean() < np.abs(actual - baseline).mean()
    assert out["status"] == "BLOCKED"
    assert out["large_move_mae_degradation_pct"] > 0
