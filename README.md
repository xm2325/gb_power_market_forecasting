# GB Power Market Forecasting

Leakage-safe forecasting of GB electricity market prices using real Elexon market data and as-of NESO wind/solar forecast vintages.

## What this repository contains

- real Elexon APX/N2EX Market Index Price ingestion and a volume-weighted market reference;
- real Elexon settlement system prices for market-stress diagnostics;
- real NESO 2026 embedded wind/solar forecast archives with publication-time-safe vintage selection;
- real NESO outturn ingestion and physical-forecast benchmarking;
- 30-minute, 2-hour, 6-hour and 12-hour market-price experiments;
- GB settlement-clock handling, including 46/48/50-period DST days;
- fixed chronological development windows and a frozen 1,623-period final window;
- large-price-move guards, conformal uncertainty, abstention and evidence/claim controls;
- CI on Python 3.11 and 3.12 plus separate real-data and prospective-shadow workflows.

## Locked real benchmark

The first fully successful network-enabled benchmark ran on **21 August 2026** using real NESO forecast vintages/outturn and real Elexon Market Index and system prices.

| Horizon | Selected family | Previous-settlement-day MAE | Deployed MAE | Final result |
|---|---|---:|---:|---:|
| 30m | Price history only | 24.048 £/MWh | **8.939 £/MWh** | **62.8% better** |
| 2h | Price + NESO forecast levels | 24.048 £/MWh | **17.087 £/MWh** | **28.9% better** |
| 6h | Price + NESO forecast levels | 24.048 £/MWh | 34.437 £/MWh | **43.2% worse** |
| 12h | Price + NESO forecast levels | 24.048 £/MWh | 50.974 £/MWh | **112.0% worse** |

All four horizons have:

- 1,623 / 1,623 frozen final targets;
- 100% end-to-end target coverage;
- zero NESO forecast publications after the decision-time cutoff;
- a passing real-data information/coverage gate.

The evidence policy classifies 30m and 2h as `REAL_CLAIMABLE_POSITIVE`. The 6h and 12h results are deliberately retained as `REAL_NEGATIVE_RESULT`; they passed pre-final selection but did not generalise to the independent final window.

Forecast-revision features were **not selected at any horizon**. At 30m, price history alone was strongest. At 2h, as-of NESO forecast levels added useful information.

Full result and provenance:

- [`docs/REAL_RESULTS_2026-08-21.md`](docs/REAL_RESULTS_2026-08-21.md)
- [`reports/locked/V0_20_REAL_BENCHMARK_LOCK.json`](reports/locked/V0_20_REAL_BENCHMARK_LOCK.json)
- [`docs/PROSPECTIVE_HOLDOUT_POLICY.md`](docs/PROSPECTIVE_HOLDOUT_POLICY.md)

These are public-data forecasting results, **not realised trading P&L**.

## v0.21 prospective shadow

The exact v0.20 ridge states are now serialised in [`reports/locked/V0_21_FROZEN_MODEL_STATE.json`](reports/locked/V0_21_FROZEN_MODEL_STATE.json). Reconstructing them from the locked successful artifact reproduced every old final prediction with maximum absolute differences of about `1e-12 GBP/MWh`, well below the `1e-8` replay tolerance.

The first truly post-lock checkpoint used targets from **2026-08-15 07:30 UTC to 2026-08-20 23:00 UTC**. It contains **271/271 half-hours**, 100% coverage and zero future NESO publications. Because the predeclared gate requires **672 half-hours (14 days)**, every horizon remains `SHADOW_ONLY`.

Early shadow behaviour, shown here only as diagnostic evidence:

| Horizon | Frozen-model MAE | Reference MAE | Early shadow difference |
|---|---:|---:|---:|
| 30m | 7.491 £/MWh | 16.509 £/MWh | 54.6% better |
| 2h | 17.013 £/MWh | 16.509 £/MWh | 3.1% worse |
| 6h | 44.914 £/MWh | 16.509 £/MWh | 172.1% worse |
| 12h | 66.843 £/MWh | 16.509 £/MWh | 304.9% worse |

**These 271-row values are not new CV/application headline metrics.** The unchanged frozen models may continue accumulating later observations, but any model changed after inspecting this checkpoint must begin a new prospective evidence window after the checkpoint boundary.

See:

- [`docs/V0_21_PROSPECTIVE_PROTOCOL.md`](docs/V0_21_PROSPECTIVE_PROTOCOL.md)
- [`docs/V0_21_SHADOW_CHECKPOINT_2026-08-21.md`](docs/V0_21_SHADOW_CHECKPOINT_2026-08-21.md)
- [`reports/prospective/V0_21_SHADOW_CHECKPOINT_2026-08-21.json`](reports/prospective/V0_21_SHADOW_CHECKPOINT_2026-08-21.json)

## Real-data snapshot

The successful benchmark downloaded and audited:

- NESO legacy 2026 forecast archive: **2,427,930 rows**;
- NESO current 2026 forecast archive: **1,040,322 rows**;
- NESO Historic Demand Data 2026: **10,174 rows**;
- NESO Demand Data Update: **2,832 downloaded rows**;
- Elexon market/system-price history: **10,894 settlement periods**, with 100% market-reference coverage, 100% system-price coverage and zero duplicate settlement keys.

The full network snapshots remain GitHub Actions artifacts rather than large Git blobs. The locked benchmark records the artifact digest and the SHA-256 identity of each NESO source snapshot.

## Source-clock audit

The full network run exposed a source-clock inconsistency in **1,268** legacy NESO forecast rows published on 20–21 April 2026. Those rows use a BST/local-clock interpretation in the raw `TIME_GMT` field.

The repository therefore treats:

```text
SETTLEMENT_DATE + SETTLEMENT_PERIOD
```

as the canonical GB target key. Raw `DATE_GMT/TIME_GMT` is retained for audit; the identified one-hour GMT/BST label offset is recorded, while larger unexplained clock errors still fail closed.

## Repository layout

```text
src/gb_power_market/          reusable forecasting, timing and evidence logic
scripts/                      download, materialisation and benchmark entry points
tests/                        unit/regression tests and timing-leakage checks
fixtures/                     synthetic contract fixtures + small official samples
data/samples/                 small committed source samples only
docs/                         experiment, results and evidence protocols
reports/locked/               immutable real-benchmark/model-state records
reports/prospective/          immutable shadow checkpoints
.github/workflows/            normal CI + manually triggered real/shadow workflows
```

## Run tests

```bash
python -m pip install -e '.[dev,live]'
pytest -q
```

## Run the real-data pipeline

Use the **real-market-evidence** GitHub Actions workflow for a full historical evidence run. Use **prospective-shadow-v21** to replay the frozen v0.20 model state on later observations. Both network workflows are manual so ordinary source/documentation commits do not redownload market data.

Large network snapshots are intentionally excluded from Git history.

## Prospective development

The v0.20 final window is locked. It may be used for diagnostics, but a model changed after inspecting these labels cannot claim the same 1,623 periods as independent evidence.

The current frozen v0.20 model may continue accumulating its post-lock prospective stream. If a new model is changed in response to the first v0.21 checkpoint, that changed candidate must start its own prospective window no earlier than **2026-08-20 23:00 UTC**.
