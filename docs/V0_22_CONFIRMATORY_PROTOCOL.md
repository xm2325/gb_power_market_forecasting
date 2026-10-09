# v0.22 blinded confirmatory protocol

The first v0.21 post-lock shadow checkpoint exposed 271 genuinely later half-hours ending at 2026-08-20 23:00 UTC. Those rows are therefore no longer blind data.

v0.22 starts a stricter confirmatory phase at exactly **2026-08-20 23:00 UTC** using the unchanged v0.20 frozen model state (`e9952aa88ca56b85f4d595bfe918cdc589ac0048d717d3fb3d9210361eb18918`).

## Fixed reveal window

- start: `2026-08-20T23:00:00Z`
- rows: `672` half-hours
- fixed end exclusive: `2026-09-03T23:00:00Z`
- minimum target/feature coverage: `95%`
- allowed future NESO publications: `0`

The window does not move in response to performance. Later observations cannot extend or replace it for the first confirmatory result.

## Blinding rule

Before all 672 rows are available, the confirmatory workflow may emit only:

- available/complete row counts;
- coverage;
- rows remaining;
- NESO publication-time audit;
- source snapshot identities.

It must not calculate or serialize MAE, improvement, interval coverage, direction accuracy, abstention performance, or bootstrap confidence intervals. Tests verify that changing the numerical target labels before the reveal gate does not change the blinded output.

## Reveal rule

Once the exact fixed window is complete and information gates pass, the workflow scores the unchanged frozen model once. Daily UTC blocks are resampled with a fixed seed and 5,000 bootstrap replicates. Let

`D = model absolute error - previous-settlement-day reference absolute error`.

The first confirmatory classification is predeclared as:

- `CONFIRMATORY_POSITIVE` if the 95% daily-block bootstrap interval for mean D is entirely below zero;
- `CONFIRMATORY_NEGATIVE` if it is entirely above zero;
- `CONFIRMATORY_INCONCLUSIVE` if it crosses zero.

Interval calibration and abstention statistics are reported after reveal but are not part of the point-MAE classification rule.

## Model boundary

No family, feature, alpha, scaler, coefficient, or conformal quantile may change inside this confirmatory stream. Any changed candidate must start a separate prospective window after the last data inspected during its development.
