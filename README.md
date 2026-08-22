# GB Power Market Forecasting

Leakage-safe forecasting of GB electricity market prices using real Elexon market data and as-of NESO wind/solar forecast vintages.

Current software version: **v0.25.0**. Historical evidence is versioned and never rewritten: v0.20 is the first locked real benchmark; v0.24 continuously monitors the unchanged frozen models; v0.25 is a separately versioned causal adaptation experiment for the regime-sensitive 2h horizon.

## What this repository contains

- real Elexon APX/N2EX Market Index Price ingestion and a volume-weighted market reference;
- real NESO embedded wind/solar forecast vintages with publication-time-safe selection;
- GB settlement-clock handling, including 46/48/50-period DST days;
- fixed chronological development/selection/calibration/final boundaries;
- exact serialisation and replay of frozen ridge model state;
- continuous forward validation with daily, cumulative and rolling monitoring;
- causal online residual-level adaptation for versioned model upgrades;
- append-only row-level forward ledgers with SHA-256 hash chains and a snapshot registry;
- predeclared degradation alerts and a promotion-readiness gate;
- conformal uncertainty, large-move diagnostics, abstention and evidence/claim controls;
- CI on Python 3.11 and 3.12 plus manual network workflows.

## v0.20 — locked real benchmark

The first fully successful network-enabled benchmark ran on **21 August 2026** using real NESO and Elexon data. The final test window contains **1,623 half-hours** from `2026-07-12T12:00Z` to `2026-08-15T07:30Z`, with 100% target coverage and zero future NESO publications.

| Horizon | Frozen family | Previous-day MAE | Frozen-model MAE | Locked result |
|---|---|---:|---:|---:|
| 30m | Price history only | 24.048 £/MWh | **8.939 £/MWh** | **62.8% better** |
| 2h | Price + as-of NESO levels | 24.048 £/MWh | **17.087 £/MWh** | **28.9% better** |
| 6h | Price + as-of NESO levels | 24.048 £/MWh | 34.437 £/MWh | **43.2% worse** |
| 12h | Price + as-of NESO levels | 24.048 £/MWh | 50.974 £/MWh | **112.0% worse** |

Forecast-revision features were not selected at any horizon. 30m and 2h are `REAL_CLAIMABLE_POSITIVE`; 6h and 12h remain visible as `REAL_NEGATIVE_RESULT` rather than being tuned away.

Evidence:

- [`docs/REAL_RESULTS_2026-08-21.md`](docs/REAL_RESULTS_2026-08-21.md)
- [`reports/locked/V0_20_REAL_BENCHMARK_LOCK.json`](reports/locked/V0_20_REAL_BENCHMARK_LOCK.json)

These are forecasting results on public market data, **not realised trading P&L**.

## v0.21 — exact frozen model state

The exact v0.20 ridge states are serialised in [`reports/locked/V0_21_FROZEN_MODEL_STATE.json`](reports/locked/V0_21_FROZEN_MODEL_STATE.json), SHA-256:

`e9952aa88ca56b85f4d595bfe918cdc589ac0048d717d3fb3d9210361eb18918`

Reconstruction reproduced every locked final prediction with maximum absolute differences around `1e-12 £/MWh`, below the `1e-8` replay tolerance. Later monitoring therefore uses the same family, feature order, alpha, scaler, coefficients and conformal quantile rather than refitting a similar model.

## v0.24 — continuous forward validation

v0.24 keeps the model unchanged and reads outcomes only as they become available. A 21 August snapshot first showed a regime in which 2h performance had temporarily deteriorated, while 30m remained stable and 6h/12h remained poor.

A later unchanged-model replay on **22 August 2026** extended the post-lock segment to **362 half-hours**. The larger sample materially changed the 2h interpretation:

| Horizon | Post-lock frozen-model result vs previous-day reference |
|---|---:|
| **30m** | **61.3% better** |
| **2h** | **13.6% better** |
| **6h** | **106.8% worse** |
| **12h** | **203.6% worse** |

The 2h model therefore did **not** permanently collapse. It moved through a difficult level regime and later recovered enough that the unchanged frozen model again beat the previous-settlement-day baseline across the larger post-lock sample. This is exactly why the repository keeps rolling monitoring separate from model selection.

The monitor writes row-level prediction/error histories, UTC-day summaries, cumulative error advantage and rolling 24h/3d/7d MAE. If monitoring motivates a model change, that revised model receives a new versioned forward segment; previously observed rows are never relabelled as fresh evidence.

Evidence:

- [`docs/V0_24_CONTINUOUS_FORWARD_VALIDATION.md`](docs/V0_24_CONTINUOUS_FORWARD_VALIDATION.md)
- [`docs/V0_24_FORWARD_RESULTS_2026-08-21.md`](docs/V0_24_FORWARD_RESULTS_2026-08-21.md)
- [`reports/monitoring/V0_24_CONTINUOUS_FORWARD_2026-08-21.json`](reports/monitoring/V0_24_CONTINUOUS_FORWARD_2026-08-21.json)

## v0.25 — causal 2h level adaptation

The difficult mid-August 2h regime showed a growing level bias. v0.25 therefore left the original ridge model, NESO feature family, alpha, scaler and coefficients unchanged and added one deliberately low-capacity online correction: the mean `realised - frozen_prediction` residual over the previous 48 hours.

For target `t`, a historical residual may enter only after its target outcome is already available by the current 2h decision time: `s + 30m <= decision_time(t)`. The current target and the most recent 150 minutes of target labels therefore cannot affect their own correction. The rule was frozen with a new forward start at **2026-08-21 11:30 UTC**.

### Append-only forward sequence

| Snapshot | Forward rows | Adaptive MAE | Frozen 2h MAE | Previous-day MAE | Interpretation |
|---|---:|---:|---:|---:|---|
| 21 Aug 14:30 | 6 | **3.859** | 13.185 | 9.227 | strong but extremely early |
| 21 Aug 16:00 | 9 | **5.357** | 11.241 | 8.670 | newest three rows already weaker |
| 21 Aug 18:00 | 13 | **6.828** | 10.832 | 9.621 | tail/overshoot risk visible |
| **22 Aug 20:30** | **66** | **21.918** | **20.082** | 39.545 | **first predeclared degradation alerts fired** |

Across all 66 versioned forward half-hours, the adaptive candidate still beats the previous-day reference by **44.6%**, but it is now **9.1% worse than the unchanged frozen 2h model**. Its P95 absolute error is also worse than frozen (**56.07 vs 52.29 £/MWh**), and adaptive interval coverage is lower (**72.7% vs 78.8%**) with unchanged interval width.

The early 6–13-row improvement was therefore not treated as sufficient evidence for promotion. Once the sample crossed the predeclared 48-row alert threshold, the latest 24h monitor produced:

| Latest 24h / 48 rows | Adaptive | Frozen 2h | Previous-day reference |
|---|---:|---:|---:|
| MAE | **26.853** | **22.796** | 50.780 |
| Signed bias | **16.991** | **12.754** | 50.066 |
| P95 absolute error | **60.237** | **55.844** | 121.400 |
| Interval coverage | **62.5%** | **70.8%** | — |

The resulting alerts are deliberately preserved:

- `ADAPTIVE_TRAILS_FROZEN_24H`
- `BIAS_CORRECTION_WORSENED_24H`

There is **no** `ADAPTIVE_TRAILS_REFERENCE_24H` alert because the adaptive candidate still substantially beats the previous-day reference. The problem is more specific: the fixed 48h residual mean adapts too slowly to level reversals and can overshoot an already-recovering frozen model.

The latest six hours reinforce that diagnosis. The causal correction has swung negative (mean approximately **-2.43 £/MWh**), while adaptive MAE remains slightly worse than frozen (**25.01 vs 23.99 £/MWh**). The v0.25 rule is not retuned in response; changing it requires a new model version and a new forward start.

### Forward-ledger governance

Every versioned target stores target/decision time, realised price, frozen prediction, previous-day reference, causal correction, history cut-off and adaptive prediction in a canonical row. Row SHA-256 values are chained so a later run cannot silently rewrite an earlier observation.

- 6-row genesis chain tip: `b27a99b21466c8a4cbf58d29ad9c980a174b278cee1a741582a978af747789f2`;
- 9-row chain tip: `f857a1f7f069961624cc3cb5d1f4e544e942d06658882ed56f519b09429257c6`;
- 13-row chain tip: `5852d70b1a18acc0ff9ae46de71c372fc9d8878e8e2ecab8d2b2427dae997745`;
- **66-row chain tip:** `b618989dcd02f066cc3e6e38444ceb06eee549820a675d4142ed45094d33ba00`.

The 66-row snapshot is registry sequence 4. It reproduced the complete 13-row preceding ledger plus the permanent first-six genesis anchor before appending **53** new targets. A dedicated snapshot-lock utility now verifies the full chain, requires rows and end time to advance, copies the exact artifact outputs, content-addresses the committed monitor/ledger and refuses to rewrite an existing snapshot.

Current maturity is `INTRADAY_TO_2DAY_MONITORING`. Promotion criteria remain unevaluated until **336 forward half-hours / 7 days**; the current state is `NOT_ELIGIBLE_INSUFFICIENT_ROWS`, with **270 rows still required**. Passing the eventual gate never auto-promotes a model.

Evidence:

- [`docs/V0_25_FORWARD_RESULTS_2026-08-22_2030Z.md`](docs/V0_25_FORWARD_RESULTS_2026-08-22_2030Z.md)
- [`reports/monitoring/V0_25_MONITOR_STATE_2026-08-22_2030Z.json`](reports/monitoring/V0_25_MONITOR_STATE_2026-08-22_2030Z.json)
- [`reports/monitoring/V0_25_FORWARD_LEDGER_2026-08-22_2030Z.csv`](reports/monitoring/V0_25_FORWARD_LEDGER_2026-08-22_2030Z.csv)
- [`reports/monitoring/V0_25_FORWARD_SNAPSHOT_REGISTRY.json`](reports/monitoring/V0_25_FORWARD_SNAPSHOT_REGISTRY.json)

Latest source artifact: `v25-adaptive-2h-32602423009`, ID `9483291389`, SHA-256 `eb2585458aaddb15a2485b4f5c349e8f90917cfc97bbdbe179cf95009e90ab95`.

These 66 rows are **monitoring evidence, not a new CV/headline win**. The important result is that the predeclared governance caught a correction that looked excellent in the first few observations but did not remain better than the unchanged frozen model.

## Earlier prospective/blinding experiments

v0.21 first inspected 271 genuinely post-lock half-hours as `SHADOW_ONLY`; those labels then became diagnostic data.

v0.22 demonstrated metric blinding but was invalidated for confirmatory use after an artifact audit found that a price-bearing processed Parquet had been uploaded pre-gate.

v0.23 fixed that artifact-sealing problem and successfully completed a **0/672** smoke run before any sealed target entered the window. The project subsequently chose continuous forward monitoring as the more appropriate objective, so v0.23 was superseded before producing any confirmatory performance result. Its engineering audit remains in Git history, but its active network workflow has been removed.

## Source-clock audit

The full historical run exposed **1,268** legacy NESO rows with a one-hour raw GMT/BST label inconsistency. The repository therefore uses `SETTLEMENT_DATE + SETTLEMENT_PERIOD` as the canonical GB target key, retains the raw clock for audit, accepts only the identified one-hour source-label offset and fails closed above it.

## Repository layout

```text
src/gb_power_market/          reusable forecasting, timing and monitoring logic
scripts/                      download, materialisation, benchmark and monitor runners
tests/                        unit/regression, leakage and evidence-lock checks
fixtures/                     synthetic contract fixtures + small official samples
data/samples/                 small committed source samples only
docs/                         experiment, result and monitoring protocols
reports/locked/               immutable benchmark/model-state records
reports/prospective/          historical prospective/blinding audit records
reports/monitoring/           versioned continuous forward-monitor snapshots
.github/workflows/            CI + manual real-data/monitoring workflows
```

## Run tests

```bash
python -m pip install -e '.[dev,live]'
pytest -q
```

## Network workflows

- **real-market-evidence** — rebuild the full historical real-data benchmark;
- **prospective-shadow-v21** — historical diagnostic replay utility;
- **continuous-forward-v24** — replay the unchanged frozen models through the latest safe Elexon/NESO observations;
- **adaptive-2h-v25** — extend the unchanged, versioned 2h causal-bias-correction candidate;
- **lock-v25-snapshot** — content-address and commit a verified forward artifact into the append-only registry.

Long-running network workflows are manual so ordinary documentation/source commits do not repeatedly download live market data.
