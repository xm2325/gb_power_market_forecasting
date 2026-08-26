# v0.27 first forward prediction protocol

The sealed 48-row v0.27 result is **development validation only**. After that result passed and was immutably locked, the unchanged validated predictive source was promoted to the fresh `0.27.0` implementation lock.

The implementation lock fixed these times before any v0.27 forward outcome was read:

- implementation lock: `2026-08-25T00:11:28.620570+00:00`;
- first forward decision: `2026-08-25T00:30:00+00:00`;
- first forward target: `2026-08-25T02:30:00+00:00`;
- horizon: 120 minutes;
- forward outcomes present at lock: **0**.

## Stronger-than-replay evidence

The first forecast is not allowed to be reconstructed after its target outcome exists. `freeze-v27-first-prediction` must commit the numerical prediction to Git **after the locked 00:30 UTC decision time and before the 02:30 UTC target period begins**.

The workflow fails closed if either condition is violated. It checks the timing before any market-data access and again immediately before commit and push.

## Causal input boundary

For the 02:30 UTC target:

- Elexon Market Index Data is downloaded only through `2026-08-25T00:30:00Z` end-exclusive, so the latest target price entering history is 00:00 UTC;
- the exact-time downloader sends no settlement-period filters and checks every returned `startTime` before persistence;
- NESO vintages may be downloaded into an ephemeral runner, but the selected target vintage must have `publish_time_utc <= 2026-08-25T00:30:00Z`;
- the frozen 2h prediction is generated from the byte-locked v0.20 state;
- the v0.27 residual correction uses only outcomes whose 30-minute availability time is no later than the 00:30 UTC decision;
- the target's realised price is represented as unknown/NaN during calculation and is forbidden from the committed prediction record.

The committed record must state `target_label_status = UNOBSERVED_NOT_ACCESSED` and `realised_price_in_prediction_record = false`.

## What is committed

Only the prediction record, its provenance and input manifests are committed. Raw Elexon/NESO downloads and retrospective frozen-history tables remain ephemeral and are not written to the repository.

The prediction record is **not a performance claim**. It proves that a numerical forecast existed before the target outcome. Scoring is a separate later evidence step that may join the realised outcome only after the existing 90-minute safety policy makes it available.

For the first 02:30 UTC target, outcome scoring therefore cannot occur before approximately `2026-08-25T04:00:00Z` under the current policy.

## Missed-window rule

If the first prediction is not successfully committed before 02:30 UTC, it must not be reconstructed later and described as prospectively frozen. The locked forward boundary is not moved to a more favourable time after observing prices.
