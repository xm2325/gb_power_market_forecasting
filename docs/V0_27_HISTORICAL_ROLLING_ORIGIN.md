# v0.27 historical rolling-origin uncertainty

Evidence class: `HISTORICAL_ASOF_ROLLING_ORIGIN_NOT_LIVE_FORWARD`.

Window: 2026-05-01T00:00:00+00:00 to 2026-08-23T22:00:00+00:00 (end-exclusive), 5,516 half-hours.

| Model | MAE (£/MWh) | P95 abs error (£/MWh) |
|---|---:|---:|
| causal_base | 18.720 | 60.884 |
| v0.25 | 20.384 | 64.570 |
| v0.26 | 18.380 | 58.541 |
| v0.27 | 18.578 | 59.065 |
| previous_day | 25.170 | 95.118 |

## Paired time-block uncertainty

### v0.27 vs causal_base

Observed MAE gain: **0.142 £/MWh** (0.76%). Positive means v0.27 is better.
24h-block 95% interval: **[-0.129, 0.403] £/MWh**; `INTERVAL_INCLUDES_ZERO`.
7-day-block sensitivity: **[-0.060, 0.341] £/MWh**; `INTERVAL_INCLUDES_ZERO`.

### v0.27 vs v0.26

Observed MAE gain: **-0.198 £/MWh** (-1.08%). Positive means v0.27 is better.
24h-block 95% interval: **[-0.446, -0.005] £/MWh**; `SUPPORTS_V27_HIGHER_MAE`.
7-day-block sensitivity: **[-0.499, 0.024] £/MWh**; `INTERVAL_INCLUDES_ZERO`.

### v0.27 vs v0.25

Observed MAE gain: **1.805 £/MWh** (8.86%). Positive means v0.27 is better.
24h-block 95% interval: **[1.018, 2.679] £/MWh**; `SUPPORTS_V27_LOWER_MAE`.
7-day-block sensitivity: **[0.867, 3.108] £/MWh**; `SUPPORTS_V27_LOWER_MAE`.

### v0.27 vs previous_day

Observed MAE gain: **6.592 £/MWh** (26.19%). Positive means v0.27 is better.
24h-block 95% interval: **[4.388, 8.651] £/MWh**; `SUPPORTS_V27_LOWER_MAE`.
7-day-block sensitivity: **[3.034, 10.248] £/MWh**; `SUPPORTS_V27_LOWER_MAE`.

## Weekly consistency

- vs causal_base: v0.27 better in 12/17 folds, worse in 5/17, ties 0.
- vs v0.26: v0.27 better in 7/17 folds, worse in 10/17, ties 0.
- vs v0.25: v0.27 better in 15/17 folds, worse in 2/17, ties 0.
- vs previous_day: v0.27 better in 14/17 folds, worse in 3/17, ties 0.

## Claim boundary

Retrospective historical as-of rolling-origin robustness evidence only. The v0.27 structure was designed after these dates, so bootstrap intervals quantify temporal uncertainty in this backtest; they do not convert it into live-forward or untouched confirmatory evidence. No predictive rule is changed by this analysis.
