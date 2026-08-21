# v0.21 Prospective Shadow Protocol

## Purpose

v0.20 is an immutable historical benchmark. v0.21 does not tune against its 1,623 final labels. Instead, it freezes the exact v0.20 model states and replays them on market targets after 2026-08-15 07:30 UTC.

The aim is to answer a stricter question: does the unchanged model continue to work on observations that arrived only after the v0.20 evaluation boundary?

## Exact frozen state

The frozen state is stored in `reports/locked/V0_21_FROZEN_MODEL_STATE.json` and is tied to v0.20 evidence fingerprint:

`7c5f78b98c8ed877ab4c5cefa8a40b3068abb74cb2062ecf677f319d74a14661`

The export reconstructed the original pre-final ridge fits and compared them row by row with all 1,623 locked final predictions. Maximum absolute replay differences were approximately 9e-13 to 2.1e-12 GBP/MWh, below the 1e-8 export tolerance.

Frozen recipes:

| Horizon | Family | Ridge alpha |
|---|---|---:|
| 30m | price history only | 10 |
| 2h | price + as-of NESO forecast levels | 1 |
| 6h | price + as-of NESO forecast levels | 100 |
| 12h | price + as-of NESO forecast levels | 100 |

The coefficients, training means/scales, feature order and conformal residual quantiles are serialised. Prospective replay does not refit any of them.

## Data boundary

Prospective targets start no earlier than:

`2026-08-15T07:30:00Z`

For price-history features, only prices observable at each decision time may enter the frame. For NESO-level models, the latest historical forecast vintage must satisfy:

`publish_time_utc <= decision_time_utc`

A future publication count above zero blocks the checkpoint.

The v0.21 downloader uses only the NESO current forecast regime for the new scoring window. It does not redownload the legacy Jan--Jun archive. Elexon data retain enough history before the prospective boundary to construct one-day/seven-day and rolling price features.

## Predeclared evidence gate

A checkpoint is classified as:

- `BLOCKED_EVIDENCE` if target coverage is below 95% or any future NESO publication enters a level-based model;
- `SHADOW_ONLY` when information/coverage gates pass but there are fewer than 672 complete half-hours;
- `PROSPECTIVE_EVIDENCE_READY` only after at least 672 complete half-hours (14 days).

The daily-block uncertainty calculation additionally requires at least seven complete UTC days. Days, rather than individual half-hours, are resampled to reduce false precision from serial dependence.

`PROSPECTIVE_EVIDENCE_READY` is not automatically a public claim. A separate immutable checkpoint/evidence lock must be created before any new numerical CV statement.

## No moving the goalposts

After a shadow checkpoint is inspected, its labels may be used for diagnosis. If any family, feature, alpha, coefficient, scaler, conformal quantile, threshold or other model rule is changed in response, the changed model must start a new prospective evaluation after the last inspected target. It cannot reuse the inspected checkpoint as independent evidence.

The unchanged frozen v0.20 model may continue accumulating prospective rows across checkpoints because no fitting decision is changing.

## Outputs

`run_v21_prospective_shadow.py` writes:

- one JSON report per horizon;
- a compact CSV summary;
- a combined JSON report;
- target coverage and publication-time audit;
- MAE/RMSE/P95 error;
- frozen conformal coverage;
- abstention/action-rate diagnostics;
- deterministic daily-block bootstrap of model-minus-reference absolute error when enough complete days exist.

These are public-data forecasting diagnostics. They are not realised trading P&L.
