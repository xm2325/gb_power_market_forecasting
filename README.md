# GB Power Market Forecasting

Leakage-safe forecasting of GB electricity market prices using real Elexon market data and as-of NESO wind/solar forecast vintages.

Current software version: **v0.23.0**. Historical evidence versions remain immutable: the first locked real benchmark is **v0.20** and later development does not rewrite it.

## What this repository contains

- real Elexon APX/N2EX Market Index Price ingestion and a volume-weighted market reference;
- real Elexon settlement system prices for market-stress diagnostics;
- real NESO embedded wind/solar forecast archives with publication-time-safe vintage selection;
- real NESO outturn ingestion and physical-forecast benchmarking;
- 30-minute, 2-hour, 6-hour and 12-hour market-price experiments;
- GB settlement-clock handling, including 46/48/50-period DST days;
- fixed chronological development windows and a frozen 1,623-period final window;
- exact frozen-model replay, prospective shadow evaluation and sealed confirmatory evaluation;
- large-price-move guards, conformal uncertainty, abstention and evidence/claim controls;
- CI on Python 3.11 and 3.12 plus manually triggered network workflows.

## v0.20 — locked real benchmark

The first fully successful network-enabled benchmark ran on **21 August 2026** using real NESO forecast vintages/outturn and real Elexon Market Index and system prices.

| Horizon | Selected family | Previous-settlement-day MAE | Deployed MAE | Final result |
|---|---|---:|---:|---:|
| 30m | Price history only | 24.048 £/MWh | **8.939 £/MWh** | **62.8% better** |
| 2h | Price + NESO forecast levels | 24.048 £/MWh | **17.087 £/MWh** | **28.9% better** |
| 6h | Price + NESO forecast levels | 24.048 £/MWh | 34.437 £/MWh | **43.2% worse** |
| 12h | Price + NESO forecast levels | 24.048 £/MWh | 50.974 £/MWh | **112.0% worse** |

All four horizons have **1,623/1,623** frozen final targets, 100% end-to-end target coverage and zero NESO forecast publications after the decision-time cutoff. The evidence policy classifies 30m and 2h as `REAL_CLAIMABLE_POSITIVE`; 6h and 12h remain visible as `REAL_NEGATIVE_RESULT`.

Forecast-revision features were not selected at any horizon. At 30m, price history alone was strongest. At 2h, as-of NESO forecast levels added useful information.

Evidence:

- [`docs/REAL_RESULTS_2026-08-21.md`](docs/REAL_RESULTS_2026-08-21.md)
- [`reports/locked/V0_20_REAL_BENCHMARK_LOCK.json`](reports/locked/V0_20_REAL_BENCHMARK_LOCK.json)
- [`docs/PROSPECTIVE_HOLDOUT_POLICY.md`](docs/PROSPECTIVE_HOLDOUT_POLICY.md)

These are public-data forecasting results, **not realised trading P&L**.

## v0.21 — exact frozen state + first prospective shadow

The exact v0.20 ridge states are serialised in [`reports/locked/V0_21_FROZEN_MODEL_STATE.json`](reports/locked/V0_21_FROZEN_MODEL_STATE.json). Reconstructing them from the locked successful artifact reproduced every old final prediction with maximum absolute differences of about `1e-12 £/MWh`, below the `1e-8` replay tolerance.

The first post-lock shadow checkpoint used targets from **2026-08-15 07:30 UTC to 2026-08-20 23:00 UTC**. It contained **271/271 half-hours**, 100% coverage and zero future NESO publications. Those 271 rows were intentionally diagnostic only; after inspection they ceased to be blind data.

Evidence:

- [`docs/V0_21_PROSPECTIVE_PROTOCOL.md`](docs/V0_21_PROSPECTIVE_PROTOCOL.md)
- [`docs/V0_21_SHADOW_CHECKPOINT_2026-08-21.md`](docs/V0_21_SHADOW_CHECKPOINT_2026-08-21.md)
- [`reports/prospective/V0_21_SHADOW_CHECKPOINT_2026-08-21.json`](reports/prospective/V0_21_SHADOW_CHECKPOINT_2026-08-21.json)

## v0.22 — blinding implementation audit

v0.22 tightened the design by suppressing all performance metrics before a fixed reveal gate. Its first smoke run correctly emitted no MAE, improvement, interval or bootstrap performance metrics.

A subsequent artifact audit found a stricter problem: the pre-gate artifact also uploaded `data/processed/v22/reference_market.parquet`, which contains realised Market Index Price labels. The last price-bearing target in that artifact was **2026-08-21 11:00 UTC**. Therefore v0.22 is retained as a useful engineering/no-metric-leak smoke test but is **invalidated for clean confirmatory evidence**.

Audit record:

- [`reports/prospective/V0_22_BLINDING_AUDIT_2026-08-21.json`](reports/prospective/V0_22_BLINDING_AUDIT_2026-08-21.json)

The obsolete `confirmatory-v22` workflow has been removed from the current branch so it cannot be run accidentally.

## v0.23 — sealed confirmatory replay

v0.23 restarts at the first half-hour after the last label exposed by the v0.22 artifact and keeps the exact same frozen model state.

The sealed confirmatory population is fixed now:

- start: `2026-08-21T11:30:00Z`;
- fixed end exclusive: `2026-09-04T11:30:00Z`;
- exactly **672 half-hours / 14 days**;
- minimum coverage: 95%;
- future NESO publications allowed: 0;
- model/family/alpha/scaler/coefficients/conformal state unchanged from the locked v0.21 export.

Before reveal, code may inspect only target identity, completeness, source/model hashes and publication timing. It must not compute or serialise point-loss, improvement, interval, action/direction or bootstrap performance. A recursive schema guard rejects performance-bearing keys even if nested.

The population is the **exact timestamp grid**, not merely “any 672 rows”. The workflow records a SHA-256 identity for the fixed grid and blocks duplicate, missing or off-grid complete rows. Coverage uses unique on-grid targets, so duplicates cannot inflate it.

Most importantly, pre-reveal Actions artifacts contain **sanitised reports/manifests only**. Price-bearing raw/processed files remain ephemeral on the runner. Processed source data may be uploaded only after the fixed reveal occurs.

After the exact fixed window is complete, a single 5,000-replicate daily-block bootstrap is applied to:

`|frozen model - realised price| - |previous-settlement-day reference - realised price|`.

Classification is fixed in advance:

- 95% interval entirely below zero → `CONFIRMATORY_POSITIVE`;
- 95% interval entirely above zero → `CONFIRMATORY_NEGATIVE`;
- interval crosses zero or bootstrap unavailable → `CONFIRMATORY_INCONCLUSIVE`.

Protocol:

- [`docs/V0_23_SEALED_CONFIRMATORY_PROTOCOL.md`](docs/V0_23_SEALED_CONFIRMATORY_PROTOCOL.md)

## Real-data snapshot

The successful v0.20 benchmark downloaded and audited:

- NESO legacy 2026 forecast archive: **2,427,930 rows**;
- NESO current 2026 forecast archive: **1,040,322 rows**;
- NESO Historic Demand Data 2026: **10,174 rows**;
- NESO Demand Data Update: **2,832 downloaded rows**;
- Elexon market/system-price history: **10,894 settlement periods**, with 100% market-reference coverage, 100% system-price coverage and zero duplicate settlement keys.

Later prospective/confirmatory workflows use bounded incremental windows rather than redownloading the full archive.

## Source-clock audit

The full network run exposed a source-clock inconsistency in **1,268** legacy NESO forecast rows published on 20–21 April 2026. Those rows use a BST/local-clock interpretation in the raw `TIME_GMT` field.

The repository therefore treats `SETTLEMENT_DATE + SETTLEMENT_PERIOD` as the canonical GB target key. Raw `DATE_GMT/TIME_GMT` is retained for audit; the identified one-hour GMT/BST label offset is recorded, while larger unexplained clock errors fail closed.

## Repository layout

```text
src/gb_power_market/          reusable forecasting, timing and evidence logic
scripts/                      download, materialisation and benchmark entry points
tests/                        unit/regression tests and leakage/seal checks
fixtures/                     synthetic contract fixtures + small official samples
data/samples/                 small committed source samples only
docs/                         experiment, results and evidence protocols
reports/locked/               immutable real-benchmark/model-state records
reports/prospective/          immutable shadow/blinding audit/checkpoint records
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
- **confirmatory-v23**: sealed accumulation and one fixed 672-row reveal.

All long-running network workflows are manual after their initial smoke validation, so ordinary source/documentation commits do not repeatedly download market data or expose new labels.
