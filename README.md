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
- CI on Python 3.11 and 3.12 plus a separate real-data evidence workflow.

## Real-data status

A network-enabled GitHub Actions run on 21 August 2026 successfully downloaded the official source snapshots:

- NESO legacy 2026 forecast archive: 2,427,930 rows;
- NESO current 2026 forecast archive: 1,039,670 rows;
- NESO Historic Demand Data 2026: 10,174 rows;
- NESO Demand Data Update: 2,832 rows;
- Elexon market/system-price history: 10,894 expected settlement periods with 100% MID coverage, 100% system-price coverage and no duplicate settlement keys in the materialised audit.

The first full network run exposed a source-clock inconsistency in 1,268 legacy NESO forecast rows published on 20--21 April 2026. Those rows use a BST/local-clock interpretation in the raw `TIME_GMT` field. The repository now treats `SETTLEMENT_DATE + SETTLEMENT_PERIOD` as the canonical target key, records the raw-clock offset for audit, allows the identified one-hour GMT/BST label offset, and still fails closed for larger unexplained clock errors.

New real price-performance claims remain blocked until the corrected materialisation and fixed-window benchmark rerun completes successfully. The downloaded source snapshots are retained as workflow artifacts rather than committed as large Git blobs.

## Repository layout

```text
src/gb_power_market/          reusable forecasting, timing and evidence logic
scripts/                      download, materialisation and benchmark entry points
tests/                        unit/regression tests and timing-leakage checks
fixtures/                     synthetic contract fixtures + small official samples
data/samples/                 small committed source samples only
docs/                         experiment and evidence protocols
reports/                      small audit/status files
.github/workflows/            normal CI + real-data evidence workflow
```

## Run tests

```bash
python -m pip install -e '.[dev]'
pytest -q
```

## Run the real-data pipeline

Use the **real-market-evidence** GitHub Actions workflow. It downloads official NESO/Elexon snapshots, materialises compact Parquet data, runs the physical and price benchmarks, uploads the full evidence artifact, and applies the final claim-integrity gate.

Large network snapshots are intentionally excluded from Git history.
