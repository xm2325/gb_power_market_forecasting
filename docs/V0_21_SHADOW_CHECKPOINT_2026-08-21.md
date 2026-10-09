# v0.21 Prospective Shadow Checkpoint — 21 August 2026

## Status

`SHADOW_ONLY` — real post-lock data, but not enough observations for a new claim.

The checkpoint replays the unchanged v0.20 model states on targets after the locked final window. No family, ridge alpha, coefficient, feature scaler or conformal quantile was refitted or reselected.

- Prospective start: `2026-08-15T07:30:00Z`
- Checkpoint end (exclusive): `2026-08-20T23:00:00Z`
- Complete half-hours: **271 / 271**
- Coverage: **100%** at every horizon
- Future NESO publications selected: **0**
- Predeclared evidence threshold: **672 half-hours (14 days)**
- Complete UTC days available for block bootstrap: **4**; threshold is 7

## Early shadow results

| Horizon | Frozen family | Reference MAE | Frozen-model MAE | Difference vs reference | Interval coverage |
|---|---|---:|---:|---:|---:|
| 30m | Price history only | 16.509 £/MWh | **7.491 £/MWh** | **54.6% better** | 93.7% |
| 2h | Price + NESO levels | 16.509 £/MWh | 17.013 £/MWh | 3.1% worse | 90.4% |
| 6h | Price + NESO levels | 16.509 £/MWh | 44.914 £/MWh | 172.1% worse | 76.8% |
| 12h | Price + NESO levels | 16.509 £/MWh | 66.843 £/MWh | 304.9% worse | 53.9% |

These values are **not** new CV/application headline metrics. The sample gate has not been reached and the daily-block uncertainty calculation is not yet available.

## What this checkpoint tells us

The 30-minute model remains strong in the first new post-lock observations without any model change. That is useful evidence of short-horizon stability, but the window is still too short for a new claim.

The two-hour model is currently close to the previous-settlement-day reference and slightly worse. This is exactly why the prospective gate exists: a small early slice should not replace the much larger locked v0.20 result or trigger immediate retuning.

The 6-hour and 12-hour failures persist and their conformal coverage has deteriorated further. That makes the existing long-horizon generalisation concern harder to dismiss as one unlucky historical split. It does **not** justify tuning against this checkpoint and re-reporting the same labels.

## Incremental data path

This checkpoint did not redownload the 2.43M-row legacy NESO archive.

It downloaded only:

- **108,352** rows from the current NESO embedded wind/solar forecast resource for settlement dates 14–20 August;
- **624** Elexon settlement periods covering the price-feature history and scoring window.

The bounded NESO current-window snapshot had:

- SHA-256 `4fdc7cae27c363ad8afe28e5a541f947b53499e99f4a95726878550b232ce667`;
- zero current-regime raw-clock mismatches;
- stable count before/after the paged SQL extraction.

Elexon market-reference, system-price and joint coverage were all 100%, with zero duplicate settlement keys.

## Provenance

- Workflow run: `32473442425`
- Artifact: `v21-prospective-shadow-32473442425`
- Artifact SHA-256: `403219ea5178ca48ff06c0630992a958e8121a797fbb379772a973a12f740c29`
- Frozen model-state SHA-256: `e9952aa88ca56b85f4d595bfe918cdc589ac0048d717d3fb3d9210361eb18918`
- Source v0.20 evidence fingerprint: `7c5f78b98c8ed877ab4c5cefa8a40b3068abb74cb2062ecf677f319d74a14661`
- Machine-readable checkpoint: `reports/prospective/V0_21_SHADOW_CHECKPOINT_2026-08-21.json`

## Development boundary after inspection

The unchanged frozen v0.20 models may continue accumulating prospective observations into the same evaluation stream.

If any model rule is changed after inspecting this checkpoint, the changed candidate must start its own prospective evidence window no earlier than:

`2026-08-20T23:00:00Z`

That prevents the newly inspected 271 labels from becoming a hidden tuning set while still being reported as independent evidence.
