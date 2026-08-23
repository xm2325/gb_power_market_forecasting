# GB Power Market Forecasting

Leakage-safe forecasting of GB electricity market prices using real Elexon market data and as-of NESO wind/solar forecast vintages.

Current software version: **v0.26.0**. Historical evidence is versioned and never rewritten: v0.20 is the first locked real benchmark; v0.24 continuously monitors the unchanged frozen models; v0.25 records a 48h causal-bias correction that triggered its predeclared degradation alerts; v0.26 is a separately versioned 2h regime-adaptation candidate.

## What this repository contains

- real Elexon APX/N2EX Market Index Price ingestion and a volume-weighted market reference;
- real NESO embedded wind/solar forecast vintages with publication-time-safe selection;
- GB settlement-clock handling, including 46/48/50-period DST days;
- fixed chronological development/selection/calibration/final boundaries;
- exact serialisation and replay of frozen ridge model state;
- continuous forward validation with daily, cumulative and rolling monitoring;
- causal online residual-level adaptation for versioned model upgrades;
- append-only row-level forward ledgers with SHA-256 hash chains and snapshot registries;
- predeclared degradation alerts and promotion-readiness gates;
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

## v0.25 — causal 48h 2h level adaptation

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

Once the sample crossed the predeclared 48-row alert threshold, the latest 24h monitor produced:

| Latest 24h / 48 rows | Adaptive | Frozen 2h | Previous-day reference |
|---|---:|---:|---:|
| MAE | **26.853** | **22.796** | 50.780 |
| Signed bias | **16.991** | **12.754** | 50.066 |
| P95 absolute error | **60.237** | **55.844** | 121.400 |
| Interval coverage | **62.5%** | **70.8%** | — |

The resulting alerts are preserved:

- `ADAPTIVE_TRAILS_FROZEN_24H`
- `BIAS_CORRECTION_WORSENED_24H`

There is no `ADAPTIVE_TRAILS_REFERENCE_24H` alert because the adaptive candidate still substantially beats the previous-day reference. The failure is more specific: a fixed 48h residual mean adapts too slowly to level reversals and can overcorrect an already-recovering frozen model.

The complete 66-row sequence is registry **sequence 4**, with chain tip:

`b618989dcd02f066cc3e6e38444ceb06eee549820a675d4142ed45094d33ba00`

It reproduced the preceding 13-row ledger and permanent first-six genesis anchor before appending 53 new targets. The v0.25 rule is not retuned after these alerts; its degradation remains part of the project evidence.

Evidence:

- [`docs/V0_25_FORWARD_RESULTS_2026-08-22_2030Z.md`](docs/V0_25_FORWARD_RESULTS_2026-08-22_2030Z.md)
- [`reports/monitoring/V0_25_MONITOR_STATE_2026-08-22_2030Z.json`](reports/monitoring/V0_25_MONITOR_STATE_2026-08-22_2030Z.json)
- [`reports/monitoring/V0_25_FORWARD_LEDGER_2026-08-22_2030Z.csv`](reports/monitoring/V0_25_FORWARD_LEDGER_2026-08-22_2030Z.csv)
- [`reports/monitoring/V0_25_FORWARD_SNAPSHOT_REGISTRY.json`](reports/monitoring/V0_25_FORWARD_SNAPSHOT_REGISTRY.json)
- [`reports/monitoring/V0_25_ALERT_CHECKPOINT_2026-08-22_2030Z.json`](reports/monitoring/V0_25_ALERT_CHECKPOINT_2026-08-22_2030Z.json)

Latest source artifact: `v25-adaptive-2h-32602423009`, ID `9483291389`, SHA-256 `eb2585458aaddb15a2485b4f5c349e8f90917cfc97bbdbe179cf95009e90ab95`.

These 66 rows are **monitoring evidence, not a new CV/headline win**. The important result is that the predeclared governance caught a correction that looked excellent in the first few observations but did not remain better than the unchanged frozen model.

## v0.26 — causal 6h/48h consensus-clipped 2h adaptation

v0.26 responds to the observed v0.25 lag/overshoot without refitting the frozen 2h ridge model. The 48h residual window is retained and the 6h window comes from the already predeclared v0.25 monitoring policy; there is no search over lookback lengths.

At each 2h decision, both residual windows use only outcomes already available at decision time. A correction is applied only when the 6h and 48h residual means agree in sign, with magnitude clipped to the smaller absolute mean. Sign disagreement falls back to the unchanged frozen model.

Candidate ID: `2H_FROZEN_PLUS_CAUSAL_6H_48H_CONSENSUS_CLIPPED_RESIDUAL`.

The rule and forward boundary were fixed before v0.26 outcomes were read. Forward start: **2026-08-22T20:30:00Z**.

### Development diagnostic — not new evidence

The already-observed v0.25 forward window was reused only for development diagnostics:

| Model | MAE (£/MWh) |
|---|---:|
| v0.26 consensus candidate | **19.722** |
| frozen v0.20 2h | 20.082 |
| v0.25 48h correction | 21.918 |
| previous-day reference | 39.545 |

These rows were already observed before v0.26 and are not counted as fresh v0.26 evidence.

### Latest locked forward snapshot — sequence 2

Snapshot sequence **2** contains **23 genuine forward half-hours** through `2026-08-23T08:00:00Z` end-exclusive, including **21 rows added** since the preceding locked snapshot.

| Model | Forward MAE (£/MWh) |
|---|---:|
| v0.26 consensus candidate | **7.623** |
| frozen v0.20 2h | **7.569** |
| v0.25 48h correction | 9.219 |
| previous-day reference | 18.799 |

Current v0.26 improvement vs frozen: **-0.7%**; vs v0.25: **17.3%**; vs previous-day reference: **59.4%**.

Maturity: `EARLY_ONLY`. Alert status: `INSUFFICIENT_SAMPLE_FOR_ALERTS`; alerts: none. Performance alerts remain gated until 48 forward rows.

Integrity:

- source run: `32632409230`; artifact ID: `9491420056`;
- artifact SHA-256: `06d21cd67b40d3143ba472f412e2e2e3f403691d43f01ba71b810b96bddda249`;
- ledger chain tip: `487f1e33478f9c07a25b088b1297d8aa170db9959642e108388bebd613765ca2`;
- locked checkpoint: [`reports/monitoring/V0_26_FORWARD_CHECKPOINT_2026-08-23_0800Z.json`](reports/monitoring/V0_26_FORWARD_CHECKPOINT_2026-08-23_0800Z.json);
- snapshot registry: [`reports/monitoring/V0_26_FORWARD_SNAPSHOT_REGISTRY.json`](reports/monitoring/V0_26_FORWARD_SNAPSHOT_REGISTRY.json).

The two-row first v0.26 ledger remains the permanent genesis anchor. Every later snapshot must reproduce the latest registered prefix before appending rows. The predictive source and frozen model state are also byte-locked; changing either requires a new candidate version and forward boundary.

For the 23-row sequence-2 gate analysis, see [`docs/V0_26_GATE_EFFECTIVENESS_2026-08-23_0800Z.md`](docs/V0_26_GATE_EFFECTIVENESS_2026-08-23_0800Z.md).

Promotion review remains unavailable before **336 half-hours / 7 days**, and no gate auto-promotes a candidate.

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
- **adaptive-2h-v25** — extend the unchanged v0.25 48h residual-correction candidate;
- **lock-v25-snapshot** — content-address and commit a verified v0.25 forward artifact into the append-only registry;
- **adaptive-2h-v26** — extend the unchanged v0.26 6h/48h consensus-clipped candidate.

Long-running network workflows are manual so ordinary documentation/source commits do not repeatedly download live market data.
