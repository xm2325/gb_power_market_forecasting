# Locked real benchmark — 21 August 2026

This document records the first fully successful network-enabled real benchmark for the repository.

## Provenance

- GitHub Actions run: `32469293682`
- Artifact: `gb-power-market-real-evidence-32469293682`
- Artifact SHA-256: `152434ff0ff2198991eaf5a2c2c49b66a3a7da73f78e4d04ac39be7e6916c0b3`
- Evidence fingerprint: `7c5f78b98c8ed877ab4c5cefa8a40b3068abb74cb2062ecf677f319d74a14661`
- Final claim-integrity gate: `PASS`
- Frozen price final window: 1,623 half-hour targets, from 2026-07-12 12:00 UTC to 2026-08-15 07:30 UTC exclusive.
- Final target coverage: 100% at all four horizons.
- Future NESO publications selected: 0 at all four horizons.

The result is public-data forecasting evidence. It is not realised trading P&L, execution performance, or a claim about a trading desk.

## Source snapshot

| Source | Snapshot |
|---|---:|
| NESO legacy 2026 forecast archive | 2,427,930 rows |
| NESO current 2026 forecast archive | 1,040,322 rows |
| NESO Historic Demand 2026 | 10,174 rows |
| NESO Demand Data Update | 2,832 downloaded rows; 2,465 actual rows materialised |
| Elexon expected settlement periods | 10,894 |
| Elexon market-reference coverage | 100% |
| Elexon system-price coverage | 100% |
| Elexon joint price coverage | 100% |

The legacy NESO materialiser identified 1,268 rows with a one-hour raw `DATE_GMT/TIME_GMT` offset. The canonical target key is GB `SETTLEMENT_DATE + SETTLEMENT_PERIOD`; the raw clock is retained for audit. Offsets greater than one hour still fail closed.

## Real Market Index Price benchmark

The reference is the previous settlement day's same Settlement Period. Feature-family selection, ridge regularisation, tail guards and calibration were completed before the frozen final window.

| Horizon | Selected family | Reference MAE | Deployed MAE | Final change | Evidence class |
|---|---|---:|---:|---:|---|
| 30m | Price history only | 24.048 £/MWh | **8.939 £/MWh** | **62.8% better** | `REAL_CLAIMABLE_POSITIVE` |
| 2h | Price + NESO forecast levels | 24.048 £/MWh | **17.087 £/MWh** | **28.9% better** | `REAL_CLAIMABLE_POSITIVE` |
| 6h | Price + NESO forecast levels | 24.048 £/MWh | 34.437 £/MWh | **43.2% worse** | `REAL_NEGATIVE_RESULT` |
| 12h | Price + NESO forecast levels | 24.048 £/MWh | 50.974 £/MWh | **112.0% worse** | `REAL_NEGATIVE_RESULT` |

The 6h and 12h candidates are deliberately retained as negative held-out results. They passed the pre-final selection rules but did not generalise to the independent final window. They must not be reframed as wins.

## What the family comparison says

Selection-window MAE in £/MWh:

| Horizon | Price history | + NESO levels | + NESO levels + revisions | Selected |
|---|---:|---:|---:|---|
| 30m | **7.087** | 9.227 | 8.520 | Price history |
| 2h | 13.828 | **13.045** | 13.119 | + NESO levels |
| 6h | 19.275 | **17.965** | 18.119 | + NESO levels |
| 12h | 20.156 | **17.192** | 17.379 | + NESO levels |

Forecast-revision features were not selected at any horizon. At 30m, adding physical forecasts made the selection result worse. At 2h, forecast levels added useful information. At 6h and 12h, the same type of feature improvement did not survive the independent final window.

## Real NESO physical-forecast accuracy on the same final window

| Horizon | Wind MAE | Solar MAE | End-to-end coverage |
|---|---:|---:|---:|
| 30m | 42.83 MW | 445.05 MW | 100% |
| 2h | 58.73 MW | 445.97 MW | 100% |
| 6h | 78.67 MW | 465.17 MW | 100% |
| 12h | 104.63 MW | 466.85 MW | 100% |

These are NESO forecast-vs-outturn metrics, not price-model metrics.

## Uncertainty and abstention

The point-model conclusions above do not depend on the abstention layer. The 90% nominal conformal intervals achieved final empirical coverage of 89.5% at 30m, 89.5% at 2h, 85.9% at 6h and 83.1% at 12h. The lower coverage at 6h/12h is consistent with the long-horizon generalisation failure and should be treated as a monitoring signal, not tuned away on this final window.

## Market-stress diagnostic

The system-vs-market spread thresholds were fitted on the pre-final calibration window only.

For the 30m model, final MAE improvement over the reference was 65.6% in normal-spread periods, 51.2% in high-spread periods and 57.8% in extreme-spread periods. For the 2h model, the corresponding improvements were 33.4%, 7.0% and 27.0%.

These are diagnostics by historical spread regime, not trading-return claims.

## Locked interpretation

1. **30m:** short-horizon price history is sufficient; NESO forecast features did not add value.
2. **2h:** as-of NESO forecast levels add useful information and improve the independent final result.
3. **6h / 12h:** pre-final gains did not generalise; retain the failure rather than tuning against the final period.
4. **Forecast revisions:** not selected at any horizon in this snapshot.
5. **Next research step:** investigate the long-horizon regime shift using diagnostics, but any new model claim must use a later prospective holdout.

Machine-readable details are in `reports/locked/V0_20_REAL_BENCHMARK_LOCK.json`.
