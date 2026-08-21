# GB Power Market Forecasting

Leakage-safe forecasting of GB electricity market prices using real Elexon market data and as-of NESO wind/solar forecast vintages.

Current software version: **v0.25.0**. Historical evidence is versioned and never rewritten: v0.20 is the first locked real benchmark; v0.24 continuously monitors the unchanged frozen models; v0.25 adds a separately versioned causal adaptation candidate for the regime-sensitive 2h horizon.

## What this repository contains

- real Elexon APX/N2EX Market Index Price ingestion and a volume-weighted market reference;
- real NESO embedded wind/solar forecast vintages with publication-time-safe selection;
- GB settlement-clock handling, including 46/48/50-period DST days;
- fixed chronological development/selection/calibration/final boundaries;
- exact serialisation and replay of frozen ridge model state;
- continuous forward validation with daily, cumulative and rolling 24h/3d/7d monitoring;
- causal online residual-level adaptation for versioned model upgrades;
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

For an operational forecasting project, delaying all accuracy inspection until one future reveal date is less useful than continuously monitoring a frozen model. v0.24 therefore keeps the model unchanged but reads outcomes as they become available.

Successful GitHub Actions run `32485905691` replayed all four frozen horizons from **12 July through 21 August 11:30 UTC (end exclusive)**:

- **1,919 / 1,919** complete half-hours at every horizon;
- 100% coverage;
- zero duplicate/off-grid complete targets;
- zero future NESO publications;
- **612,906** bounded current-regime NESO forecast-vintage rows;
- Elexon history starts on 1 July solely to warm up `price_lag_7d_same_target`; scoring still starts on 12 July.

### Current forward-monitoring snapshot

| Horizon | Locked v0.20 | 1 Aug → latest | Post-lock → latest | Latest 7d |
|---|---:|---:|---:|---:|
| **30m** | **62.8% better** | **54.2% better** | **52.2% better** | **49.8% better** |
| **2h** | **28.9% better** | **9.3% better** | **6.2% worse** | **11.2% worse** |
| **6h** | 43.2% worse | 98.5% worse | 176.5% worse | 184.2% worse |
| **12h** | 112.0% worse | 193.6% worse | 314.9% worse | 325.3% worse |

The monitoring view changes the interpretation materially:

- **30m is stable.** Post-lock MAE is **7.587 vs 15.885 £/MWh** for the previous-settlement-day reference; latest-7d interval coverage is 92.9% and the model beats the reference on 73.5% of half-hours.
- **2h is regime-sensitive.** Its historical advantage weakens to +9.3% when 1 August onward is pooled, then turns negative in the post-lock segment (**16.875 vs 15.885 £/MWh**) and latest 7 days. Its rolling 7-day relative improvement crossed below zero around 15 August.
- **6h/12h are persistent failures.** Recent forward monitoring strengthens, rather than weakens, the negative conclusion. The 12h post-lock model beats the reference on only about 0.3% of half-hours and interval coverage falls to 56.4%.

The monitor writes row-level prediction/error histories, UTC-day summaries, cumulative error advantage and rolling 24h/3d/7d MAE. Monitoring data are intentionally visible. If monitoring motivates a model change, the revised model receives a new versioned forward segment; previously observed rows are never relabelled as fresh prospective evidence.

Evidence:

- [`docs/V0_24_CONTINUOUS_FORWARD_VALIDATION.md`](docs/V0_24_CONTINUOUS_FORWARD_VALIDATION.md)
- [`docs/V0_24_FORWARD_RESULTS_2026-08-21.md`](docs/V0_24_FORWARD_RESULTS_2026-08-21.md)
- [`reports/monitoring/V0_24_CONTINUOUS_FORWARD_2026-08-21.json`](reports/monitoring/V0_24_CONTINUOUS_FORWARD_2026-08-21.json)

## v0.25 — causal 2h level adaptation

v0.24 showed that the 2h model's main recent problem was a growing negative level bias: the frozen model under-predicted by about **£8.2/MWh** over the locked window and about **£15.1/MWh** after 15 August. v0.25 therefore leaves the original ridge model and NESO feature family unchanged and adds one low-capacity online correction.

For a target `t`, the candidate adds the mean `realised - frozen_prediction` residual over the previous 48 hours, but a residual may enter only when its target outcome is already available by the current 2h decision time (`s + 30m <= decision_time(t)`). The current target and the most recent 150 minutes of target labels therefore cannot affect their own correction.

Previously observed diagnostics suggested the rule was worth forward testing: post-lock-to-freeze adaptive MAE was **10.698 vs 15.885 £/MWh** for the previous-day reference. These rows are development diagnostics, not new evidence.

The rule was frozen with a new forward start at **2026-08-21 11:30 UTC**. First successful run `32500771812` observed only **6 new half-hours** through 14:30 UTC (end exclusive):

| Model | MAE |
|---|---:|
| frozen v0.20 2h | 13.185 £/MWh |
| previous-day reference | 9.227 £/MWh |
| **v0.25 adaptive 2h** | **3.859 £/MWh** |

The adaptive candidate beat the reference on **5/6** targets and used an average causal correction of **+9.763 £/MWh**. This is explicitly `EARLY_ONLY_6_HALF_HOURS_NO_HEADLINE_CLAIM`; later runs extend the same v0.25 segment without changing these six observations.

Evidence:

- [`docs/V0_25_2H_ADAPTIVE_FORWARD.md`](docs/V0_25_2H_ADAPTIVE_FORWARD.md)
- [`reports/monitoring/V0_25_2H_ADAPTIVE_FORWARD_2026-08-21.json`](reports/monitoring/V0_25_2H_ADAPTIVE_FORWARD_2026-08-21.json)

Artifact: `v25-adaptive-2h-32500771812`, ID `9453438684`, SHA-256 `64d30a6e18a2c3fa2243fa28ceb800afec1abc66f7dc0816515d96ff9faf885c`.

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
- **adaptive-2h-v25** — extend the versioned 2h causal-bias-correction candidate through later observations.

Long-running network workflows are manual so ordinary documentation/source commits do not repeatedly download live market data.
