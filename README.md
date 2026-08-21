# GB Power Market Forecasting

Leakage-safe forecasting of GB electricity market prices using **real Elexon market data** and **as-of NESO wind/solar forecast vintages**.

## What this repository does

The live pipeline downloads public GB electricity data, reconstructs what was knowable at each historical decision time, and compares four forecast horizons: **30 minutes, 2 hours, 6 hours, and 12 hours**. It keeps model selection, uncertainty calibration, and the final evaluation window separate.

The price target is the volume-weighted Elexon Market Index Price across APX/N2EX providers. NESO embedded wind/solar forecasts are selected only when their publication timestamp is at or before the corresponding decision time. GB daylight-saving settlement days are handled with the real 46/48/50-period market clock rather than a fixed `shift(48)` assumption.

## Evidence status

The repository deliberately distinguishes three things:

- **Real official samples and metadata committed here**: small NESO archive/outturn samples used to verify schema and settlement-time semantics.
- **Full real data hydrated in GitHub Actions**: multi-million-row NESO forecast archives plus Elexon MID/system-price history are downloaded at run time and stored as workflow artifacts, not committed to Git history.
- **Synthetic contract fixtures**: only for software tests; file names explicitly contain `SYNTHETIC` and their metrics are not treated as market results.

Until the network-enabled workflow completes all provenance, coverage, timestamp and final-window gates, new real-price headline metrics remain blocked. The current evidence ledger is under `reports/v20_evidence/`.

## Live experiment

Run **Actions → real-market-evidence → Run workflow**. The job:

1. runs the full test suite;
2. downloads real 2026 NESO forecast archives and actual outturn;
3. downloads real Elexon APX/N2EX MID and settlement system prices;
4. materialises timestamp-normalised Parquet;
5. evaluates 30m / 2h / 6h / 12h physical and price forecasts on fixed calendar windows;
6. builds a SHA-256-backed evidence ledger;
7. uploads evidence even when the final integrity gate blocks a claim.

The frozen final price window contains **1,623 half-hour targets** from 2026-07-12 12:00 UTC to 2026-08-15 07:30 UTC (end exclusive at 08:00).

## Main paths

```text
src/gb_power_market/                 forecasting + market-time logic
scripts/                             real-data download/materialisation/evaluation
tests/                               DST, leakage, provenance and model tests
data/samples/                        small real NESO samples + metadata
fixtures/                            explicitly synthetic contract fixtures
.github/workflows/real-market-evidence.yml
reports/v20_evidence/                current claim-safe evidence status
docs/REAL_MARKET_PROTOCOL.md
docs/EVIDENCE_PROTOCOL.md
```

## Reproduce locally

```bash
python -m pip install -e '.[dev,live]'
pytest -q
```

The large official archives are intentionally not committed. Use the workflow or the scripts in `scripts/` to hydrate them.

## Data sources

- NESO Data Portal: embedded wind and solar forecasts, Historic Demand Data and Demand Data Update.
- Elexon BMRS Insights API: Market Index Data and settlement system prices.

Public-source data remain subject to the providers' terms and attribution requirements. No realised trading P&L is claimed: the repository does not contain private positions, nominations, fees, netting or execution constraints.
