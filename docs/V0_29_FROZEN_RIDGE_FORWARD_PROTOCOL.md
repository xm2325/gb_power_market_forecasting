# v0.29: locked ridge coefficients on conservative live inputs

## Why a separate v0.29 experiment is necessary

v0.20/v0.27 use a two-hour frozen ridge forecasting system with Elexon MID
prices and NESO embedded wind/solar vintages. Their historical Elexon feature
builder assumes the last completed period is available at the nominal grid
decision. This is **not** enough evidence to establish first availability of
MID prices. The new v0.29 path uses a deliberate **90 minute delay AFTER
period end** for every price feature. It verifies the exact SHA-256 of
reports/locked/V0_21_FROZEN_MODEL_STATE.json and uses the original ridge
coefficients / scaler unchanged. Because recent price lags now use older
observations, this is **not an exact replication of v0.20 forecasts**.

v0.28 remains operational and entirely separate; the v0.29 workflow cannot
rewrite its prediction or scoring records.

## Candidate models

Four predictions from the same target and issue time:

1. previous_day: yesterday's GB settlement date, same period number;
2. ridge_delay_safe: v0.20 2h frozen coefficients on conservative live inputs;
3. ridge_consensus: ridge_delay_safe plus a 6h/48h same-sign clipped residual
   correction, estimated ONLY from genuinely pretarget, scored v0.29 records;
4. ridge_direction_veto: ridge_consensus correction only if its sign agrees
   with the change between current frozen ridge prediction and the latest
   scored historical frozen ridge prediction. Otherwise use ridge_delay_safe.

Both adaptation methods initially fall back to ridge_delay_safe. At least 8
available scored residuals in 6h and 24 in 48h are required for any update.
There is no historical residual replay or synthetic warm-up admitted as live
evidence. Genuine scores are gated by first Git-add commit time before target
start and by a post-settlement 90-minute outcome delay.

## NESO as-of contract

An actual NESO API snapshot is collected before each forecast is created.
The target's latest vintage with Forecast_Datetime no later than the
actual decision timestamp is selected. The source publication timestamp is
not independently guaranteed as an API first-observed timestamp; it is
recorded as a producer timestamp together with snapshot hashes. Future
vintages are rejected. The Git commit must occur before the future target
starts. Any late run is blocked, not backfilled.

The forecast target is on the next settlement half-hour boundary at least
120 minutes after actual forecast computation time. Consequently actual
lead time is normally **more than 120 minutes**, not exactly 120 minutes.
Inferences and comparison metrics are labelled by their real lead.

## Outputs and evaluation

- reports/forward/v29/predictions/target.json: immutable, pretarget;
- reports/forward/v29/scores/target.json: immutable, mature outcome;
- reports/forward/v29/runs/: append-only errors, missing data and run state;
- reports/forward/v29/latest.json: replaceable derived score summary.

Compare each model with the previous-day baseline on identical target periods.
The first review threshold is 336 genuine scored targets, not model promotion
and not proof of significance. Score MAE, P95, signed bias and paired
differences. For comparison with v0.28 use ONLY the intersection of
pretarget-committed, matured targets; models computed at different actual
decision times must be identified separately.

The scheduler is cron at 17 and 47 minutes each UTC hour, and also
fires once when implementation merges to main. GitHub cron is not an
exact-time guarantee. Only GitHub-committed pretarget records qualify.

No P&L/financial returns, model superiority or deployment promotion
may be claimed from a successful workflow alone.
