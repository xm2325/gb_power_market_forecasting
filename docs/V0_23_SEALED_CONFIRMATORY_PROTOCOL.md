# v0.23 sealed confirmatory protocol

## Why v0.23 exists

v0.22 successfully prevented model-performance metrics from being calculated or serialised before its reveal gate. A later artifact audit found a stricter blinding problem: the pre-gate artifact also contained `data/processed/v22/reference_market.parquet`, which carries realised Market Index Price labels. Those labels were therefore accessible even though MAE and improvement metrics were absent.

v0.22 is retained as an engineering smoke test, but it is invalidated for clean confirmatory use. The last price-bearing target in that artifact was `2026-08-21T11:00:00Z`.

v0.23 starts at the next half-hour:

- sealed start: `2026-08-21T11:30:00Z`;
- fixed end exclusive: `2026-09-04T11:30:00Z`;
- exact targets: 672 half-hours / 14 days;
- model state: unchanged v0.21 frozen export derived from the locked v0.20 evidence;
- minimum coverage: 95%;
- future NESO publications allowed: 0.

## Pre-reveal seal

Before the exact fixed window is complete, the workflow may inspect only:

- target timestamps and the fixed expected grid;
- completeness / missingness;
- duplicate and off-grid target counts;
- source and model identity hashes;
- NESO publication-time eligibility;
- counts and coverage.

It must not compute or serialise model-performance evidence, including MAE, RMSE, improvement, prediction-error summaries, interval coverage, action/abstention performance, bootstrap performance intervals or confirmatory classification.

The pre-reveal Actions artifact contains `reports/v23_confirmatory/` only. Raw and processed price-bearing data remain ephemeral on the GitHub runner and are not uploaded. A second processed-source artifact is enabled only after the reveal has occurred.

## Fixed grid identity

The confirmatory population is not defined merely as “672 available rows”. It is the exact 30-minute UTC grid from the fixed start to the fixed end. v0.23 records a SHA-256 identity for that target grid and blocks on duplicate, missing or off-grid complete rows.

Coverage is calculated from unique on-grid complete target timestamps divided by the expected grid available so far. Duplicate rows therefore cannot inflate coverage.

## Single reveal

Once the fixed end has elapsed and information/coverage gates pass, the unchanged frozen models are scored on exactly the fixed 672-row window. Later observations cannot enter this confirmatory result.

The primary decision statistic is daily-block resampling of:

`|model - realised price| - |previous-settlement-day reference - realised price|`.

The predeclared 5,000-replicate daily-block bootstrap classification is:

- 95% interval entirely below zero: `CONFIRMATORY_POSITIVE`;
- 95% interval entirely above zero: `CONFIRMATORY_NEGATIVE`;
- interval crosses zero or bootstrap unavailable: `CONFIRMATORY_INCONCLUSIVE`.

This classification is horizon-specific. No post-reveal rule changes are allowed to rewrite the same fixed window as independent evidence.

## Evidence lineage

- locked v0.20 evidence fingerprint: `7c5f78b98c8ed877ab4c5cefa8a40b3068abb74cb2062ecf677f319d74a14661`;
- exact frozen model-state file SHA-256: `e9952aa88ca56b85f4d595bfe918cdc589ac0048d717d3fb3d9210361eb18918`;
- v0.22 invalidation record: `reports/prospective/V0_22_BLINDING_AUDIT_2026-08-21.json`.

Public-data forecasting evidence is not realised trading P&L.
