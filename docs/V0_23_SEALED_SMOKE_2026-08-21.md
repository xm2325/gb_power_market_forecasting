# v0.23 sealed confirmatory smoke — 21 August 2026

The first successful v0.23 smoke run validates the **seal**, not model performance.

## Run identity

- GitHub Actions run: `32482320136`
- artifact: `v23-sealed-confirmatory-32482320136`
- artifact ID: `9446545003`
- artifact SHA-256: `b5215327c5ba0450a19387fec633be5d93b22e6a42c244a8e1d680a234ecbef0`
- frozen model-state SHA-256: `e9952aa88ca56b85f4d595bfe918cdc589ac0048d717d3fb3d9210361eb18918`
- fixed target-grid SHA-256: `05f6487d7ae5adb6290ff1071f781bd77032c5a19c86028f971c0b9dbf4ba4af`

The fixed confirmatory window remains:

- start: `2026-08-21T11:30:00Z`
- end exclusive: `2026-09-04T11:30:00Z`
- exact targets: 672 half-hours

At this smoke run the safe availability boundary was `2026-08-21T11:00:00Z`, before the sealed start. Every horizon therefore correctly reported `SEALED_ACCUMULATION`, `0/672` complete rows and zero future NESO publications. No performance calculation was performed.

## Artifact audit

The uploaded pre-reveal artifact contains exactly 10 files:

- `confirmatory_30m.json`
- `confirmatory_2h.json`
- `confirmatory_6h.json`
- `confirmatory_12h.json`
- `confirmatory_all.json`
- `confirmatory_summary.csv`
- `neso_window_manifest.json`
- `neso_materialise_manifest.json`
- `elexon_mid_manifest.json`
- `elexon_mid_materialise_manifest.json`

It contains **no Parquet file, no raw Elexon/NESO data file and no price-bearing CSV**. The only CSV is the sanitised confirmatory summary with columns:

`horizon,status,complete_rows_so_far,rows_remaining_to_reveal,coverage_so_far,future_neso_publications`

A recursive scan found no MAE, RMSE, improvement, prediction-error, interval-performance, abstention, classification or bootstrap-result fields. Predeclared `protocol.bootstrap_replicates` and `protocol.bootstrap_seed` are allowed only as protocol metadata; bootstrap-like fields anywhere else are rejected.

The workflow step that could upload `data/processed/v23/` was explicitly **skipped** because reveal had not occurred.

## Source/data-path smoke evidence

The runner successfully exercised the bounded source path without exporting the price-bearing data:

- NESO current-regime rows downloaded/materialised: 15,370
- NESO current-window SHA-256: `4568bb128e44be30e9f117d2bb1dd40e80e8dfe51ea63eb05b36555beb3528b8`
- NESO raw-clock mismatches: 0
- Elexon MID reference rows materialised ephemerally on the runner: 363

Those processed market files existed only on the ephemeral runner and were not included in the pre-reveal artifact.

## What this establishes

This run establishes that v0.23 can:

1. execute the real incremental NESO/Elexon data path;
2. preserve the fixed model and timestamp-grid identities;
3. audit coverage, duplicate/off-grid rows and publication timing;
4. withhold performance calculations before the fixed reveal;
5. keep price-bearing processed sources out of pre-reveal artifacts.

It establishes **no new forecasting-performance claim**. The v0.20 locked numbers remain the only current real headline metrics.

Machine-readable checkpoint: [`reports/prospective/V0_23_SEALED_CHECKPOINT_2026-08-21.json`](../reports/prospective/V0_23_SEALED_CHECKPOINT_2026-08-21.json).
