# GB Power Market Forecasting

Leakage-safe forecasting of GB electricity market prices using real Elexon market data and as-of NESO wind/solar forecast vintages.

Current software version: **v0.22.0**. The first locked real benchmark remains **v0.20** and is not rewritten by later development.

## What this repository contains

- real Elexon APX/N2EX Market Index Price ingestion and a volume-weighted market reference;
- real Elexon settlement system prices for market-stress diagnostics;
- real NESO 2026 embedded wind/solar forecast archives with publication-time-safe vintage selection;
- real NESO outturn ingestion and physical-forecast benchmarking;
- 30-minute, 2-hour, 6-hour and 12-hour market-price experiments;
- GB settlement-clock handling, including 46/48/50-period DST days;
- fixed chronological development windows and a frozen 1,623-period final window;
- exact frozen-model replay, prospective shadow evaluation and blinded confirmatory evaluation;
- large-price-move guards, conformal uncertainty, abstention and evidence/claim controls;
- CI on Python 3.11 and 3.12 plus manually triggered real-data, shadow and confirmatory workflows.

## Locked v0.20 real benchmark

The first fully successful network-enabled benchmark ran on **21 August 2026** using real NESO forecast vintages/outturn and real Elexon Market Index and system prices.

| Horizon | Selected family | Previous-settlement-day MAE | Deployed MAE | Final result |
|---|---|---:|---:|---:|
| 30m | Price history only | 24.048 £/MWh | **8.939 £/MWh** | **62.8% better** |
| 2h | Price + NESO forecast levels | 24.048 £/MWh | **17.087 £/MWh** | **28.9% better** |
| 6h | Price + NESO forecast levels | 24.048 £/MWh | 34.437 £/MWh | **43.2% worse** |
| 12h | Price + NESO forecast levels | 24.048 £/MWh | 50.974 £/MWh | **112.0% worse** |

All four horizons have 1,623/1,623 frozen final targets, 100% end-to-end target coverage and zero NESO forecast publications after the decision-time cutoff. The evidence policy classifies 30m and 2h as `REAL_CLAIMABLE_POSITIVE`; 6h and 12h remain visible as `REAL_NEGATIVE_RESULT`.

Forecast-revision features were not selected at any horizon. At 30m, price history alone was strongest. At 2h, as-of NESO forecast levels added useful information.

Full result and provenance:

- [`docs/REAL_RESULTS_2026-08-21.md`](docs/REAL_RESULTS_2026-08-21.md)
- [`reports/locked/V0_20_REAL_BENCHMARK_LOCK.json`](reports/locked/V0_20_REAL_BENCHMARK_LOCK.json)
- [`docs/PROSPECTIVE_HOLDOUT_POLICY.md`](docs/PROSPECTIVE_HOLDOUT_POLICY.md)

These are public-data forecasting results, **not realised trading P&L**.

## v0.21 prospective shadow

The exact v0.20 ridge states are serialised in [`reports/locked/V0_21_FROZEN_MODEL_STATE.json`](reports/locked/V0_21_FROZEN_MODEL_STATE.json). Reconstructing them from the locked successful artifact reproduced every old final prediction with maximum absolute differences of about `1e-12 GBP/MWh`, below the `1e-8` replay tolerance.

The first truly post-lock checkpoint used targets from **2026-08-15 07:30 UTC to 2026-08-20 23:00 UTC**. It contains **271/271 half-hours**, 100% coverage and zero future NESO publications. Because the predeclared gate required 672 half-hours, every horizon remained `SHADOW_ONLY`.

Early shadow behaviour was diagnostic only: 30m remained clearly better, 2h was slightly worse than the previous-settlement-day reference, and 6h/12h remained materially weak. Those 271 labels have now been inspected and are no longer blind data.

See:

- [`docs/V0_21_PROSPECTIVE_PROTOCOL.md`](docs/V0_21_PROSPECTIVE_PROTOCOL.md)
- [`docs/V0_21_SHADOW_CHECKPOINT_2026-08-21.md`](docs/V0_21_SHADOW_CHECKPOINT_2026-08-21.md)
- [`reports/prospective/V0_21_SHADOW_CHECKPOINT_2026-08-21.json`](reports/prospective/V0_21_SHADOW_CHECKPOINT_2026-08-21.json)

## v0.22 blinded confirmatory replay

To avoid sequential peeking after the 271-row shadow checkpoint, v0.22 starts a stricter confirmatory window at **2026-08-20 23:00 UTC** using the same frozen model state.

The confirmatory window is fixed in advance:

- start: `2026-08-20T23:00:00Z`;
- fixed end exclusive: `2026-09-03T23:00:00Z`;
- exactly **672 half-hours / 14 days**;
- minimum coverage: 95%;
- future NESO publications allowed: 0.

Before the fixed window is complete, the workflow is deliberately blind to model performance. It may report only row counts, coverage, rows remaining, source identities and publication-time audits. It does **not** compute or serialize MAE, improvement, interval coverage, direction/abstention performance or bootstrap performance intervals.

The first real blinded smoke run, GitHub Actions run `32477240056`, reached **21/21 complete half-hours**, 100% coverage and zero future NESO publications, leaving **651 rows** before reveal. The workflow's no-leak gate passed. The artifact contains no pre-gate performance metrics.

After all 672 rows are available, the fixed window is revealed once. The predeclared point-MAE classification uses a 5,000-replicate daily-block bootstrap on `model absolute error - previous-settlement-day reference absolute error`: an interval entirely below zero is `CONFIRMATORY_POSITIVE`, entirely above zero is `CONFIRMATORY_NEGATIVE`, otherwise `CONFIRMATORY_INCONCLUSIVE`.

See:

- [`docs/V0_22_CONFIRMATORY_PROTOCOL.md`](docs/V0_22_CONFIRMATORY_PROTOCOL.md)
- [`reports/prospective/V0_22_BLINDED_CHECKPOINT_2026-08-21.json`](reports/prospective/V0_22_BLINDED_CHECKPOINT_2026-08-21.json)

## Real-data snapshot

The successful v0.20 benchmark downloaded and audited:

- NESO legacy 2026 forecast archive: **2,427,930 rows**;
- NESO current 2026 forecast archive: **1,040,322 rows**;
- NESO Historic Demand Data 2026: **10,174 rows**;
- NESO Demand Data Update: **2,832 downloaded rows**;
- Elexon market/system-price history: **10,894 settlement periods**, with 100% market-reference coverage, 100% system-price coverage and zero duplicate settlement keys.

Later prospective workflows use bounded incremental windows instead of redownloading the full archive. The first v0.22 blinded run downloaded **30,828** current-regime NESO forecast rows and materialised a contiguous **409-period** Elexon MID reference through the available current-day data.

## Source-clock audit

The full network run exposed a source-clock inconsistency in **1,268** legacy NESO forecast rows published on 20–21 April 2026. Those rows use a BST/local-clock interpretation in the raw `TIME_GMT` field.

The repository therefore treats `SETTLEMENT_DATE + SETTLEMENT_PERIOD` as the canonical GB target key. Raw `DATE_GMT/TIME_GMT` is retained for audit; the identified one-hour GMT/BST label offset is recorded, while larger unexplained clock errors fail closed.

## Repository layout

```text
src/gb_power_market/          reusable forecasting, timing and evidence logic
scripts/                      download, materialisation and benchmark entry points
tests/                        unit/regression tests and timing-leakage checks
fixtures/                     synthetic contract fixtures + small official samples
data/samples/                 small committed source samples only
docs/                         experiment, results and evidence protocols
reports/locked/               immutable real-benchmark/model-state records
reports/prospective/          immutable shadow/blinded checkpoints
.github/workflows/            normal CI + manually triggered network workflows
```

## Run tests

```bash
python -m pip install -e '.[dev,live]'
pytest -q
```

## Network workflows

- **real-market-evidence**: full historical real-data benchmark;
- **prospective-shadow-v21**: diagnostic replay of the frozen model on later observations;
- **confirmatory-v22**: blinded accumulation and one fixed 672-row confirmatory reveal.

All network workflows are manual so ordinary source/documentation commits do not repeatedly download market data or expose new labels.
