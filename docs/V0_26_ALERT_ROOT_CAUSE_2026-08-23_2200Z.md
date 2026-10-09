# v0.26 first 24h degradation alert — root cause

Snapshot sequence 3 is the first v0.26 checkpoint beyond the predeclared 48-row degradation-alert gate. It contains 51 genuine forward half-hours through `2026-08-23T22:00:00Z` end-exclusive.

The locked forward result is negative versus the unchanged frozen 2h model:

| Model | MAE (£/MWh) |
|---|---:|
| v0.26 consensus candidate | **17.102** |
| frozen v0.20 2h | **15.802** |
| v0.25 48h correction | 18.243 |
| previous-day reference | 19.527 |

v0.26 is **8.2% worse than frozen**, although it remains 6.3% better than v0.25 and 12.4% better than the previous-day reference. The active 24h monitor therefore fired:

- `V26_TRAILS_FROZEN_24H`
- `V26_BIAS_WORSE_THAN_FROZEN_24H`

## Where the degradation came from

The fallback mechanism is not the failure mode. Of the 51 forward rows, 34 fall back exactly to the frozen prediction. All candidate-versus-frozen error difference therefore comes from the 17 rows on which a consensus correction is actually applied.

Across those 17 applied rows:

- candidate better than frozen: **4 rows**;
- candidate worse than frozen: **13 rows**;
- harmful excess absolute error: **77.106 £/MWh**;
- helpful absolute-error reduction: **10.764 £/MWh**;
- net candidate excess absolute error versus frozen: **66.341 £/MWh**.

The dominant episode is one contiguous 16-row applied block from `2026-08-23T11:00:00Z` through `18:30:00Z`. It alone contributes **65.093 £/MWh** of the net excess error.

During that block:

- all 16 corrections are negative;
- realised price rises from **13.63** to **167.64 £/MWh**;
- the frozen forecast rises from **57.18** to **160.87 £/MWh**;
- the 6h residual mean remains negative throughout;
- the 48h residual mean also remains negative throughout;
- only 4 corrected rows beat frozen, while 12 are worse.

The consensus rule therefore solved only one failure mode from v0.25: disagreement between recent and long-run residual signs. It did **not** solve a turning point where both residual windows are stale in the same direction. Once price levels rebound, a still-negative consensus correction can amplify underprediction even though both windows agree.

## Governance decision

The unchanged frozen v0.20 2h model remains the champion. v0.26 remains an alerted challenger and is not eligible for promotion. The candidate is not retuned after observing this checkpoint.

These 51 rows are now development/monitoring data for any later version. They must never be relabelled as fresh v0.27 evidence. A future v0.27 should address **jointly stale residual windows**, not merely add another residual lookback or search thresholds on this alert window.

Source evidence:

- workflow run `32675196453`;
- artifact ID `9502476322`;
- artifact SHA-256 `a162270d94528429c0d3dcca89152f57fba9ed12654b0a2b70fbb0386fa8af1a`;
- locked ledger chain tip `dca4ef5173dcf18a81814a2bcfadaea72c4ed5fa5abc1b1c78555e55129e4a8b`;
- machine-readable root cause: [`reports/monitoring/V0_26_ALERT_ROOT_CAUSE_2026-08-23_2200Z.json`](../reports/monitoring/V0_26_ALERT_ROOT_CAUSE_2026-08-23_2200Z.json).

This is forecasting/governance evidence on public market data, not realised trading P&L.
