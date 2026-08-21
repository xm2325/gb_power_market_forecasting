# Long-horizon failure diagnostic

This is a post-hoc diagnostic of the **locked v0.20 final window**. It does not change the v0.20 model or claim. Any hypothesis derived here must be tested on a later prospective holdout.

## What happened

Both long-horizon candidates looked useful before the final window:

| Horizon | Reference selection MAE | Selected-family selection MAE | Pre-final improvement | Tail gate |
|---|---:|---:|---:|---|
| 6h | 23.414 £/MWh | 17.965 £/MWh | 23.3% | PASS |
| 12h | 22.919 £/MWh | 17.192 £/MWh | 25.0% | PASS |

The selected family in both cases was `PRICE_PLUS_NESO_LEVELS`.

On the independent final window, both reversed:

| Horizon | Reference final MAE | Deployed final MAE | Final change |
|---|---:|---:|---:|
| 6h | 24.048 £/MWh | 34.437 £/MWh | 43.2% worse |
| 12h | 24.048 £/MWh | 50.974 £/MWh | 112.0% worse |

This is a genuine generalisation failure, not a data-coverage failure: both horizons have 1,623/1,623 final targets, 100% end-to-end NESO coverage and zero future NESO publications.

## It is not explained only by extreme spread periods

The spread-regime diagnostic was defined using thresholds fitted on the pre-final calibration window.

For 6h:

- normal spread: 41.1% worse than the reference;
- high spread: 73.4% worse;
- extreme spread: approximately flat (0.1% better).

For 12h:

- normal spread: 113.7% worse;
- high spread: 143.5% worse;
- extreme spread: 23.1% worse.

The failure therefore appears across broad parts of the final population. It is not just a handful of extreme system-vs-market spread periods.

## Uncertainty also degraded

The conformal interval was calibrated before the final window with 90% nominal coverage.

Final empirical coverage was:

- 6h: 85.9%;
- 12h: 83.1%.

Point direction accuracy also fell below the previous-settlement-day reference:

- 6h: deployed 73.9% vs reference 81.7%;
- 12h: deployed 59.7% vs reference 86.5%.

These diagnostics are consistent with a change in the relationship between the selected predictors and price during the final period.

## Forecast revisions did not solve it before final

Selection-window MAE for the revision family was slightly worse than the simpler NESO-level family:

- 6h: 18.119 vs 17.965 £/MWh;
- 12h: 17.379 vs 17.192 £/MWh.

There is therefore no v0.20 evidence that simply adding revision features fixes the long-horizon problem.

## What may be tested next

The following are **prospective hypotheses**, not conclusions from the locked final window:

1. use horizon-specific shrinkage toward the price-history model when exogenous relationships become unstable;
2. add a pre-deployment model-health gate that detects deterioration in interval coverage or recent residual structure before trusting long-horizon forecasts;
3. test additional truly as-of physical drivers such as demand/net-demand forecasts only if publication timestamps are available and audited;
4. compare fixed and rolling training windows to test whether older relationships are hurting longer horizons;
5. require a larger validation margin for adding exogenous complexity at 6h/12h.

None of these changes may be selected using the locked v0.20 final labels and then re-evaluated on the same window as independent evidence. See `docs/PROSPECTIVE_HOLDOUT_POLICY.md`.
