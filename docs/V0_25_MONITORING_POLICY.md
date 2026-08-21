# v0.25 adaptive 2h monitoring policy

The v0.25 forecasting rule is frozen. This policy changes only how its forward observations are summarised and monitored; it does **not** alter the 48-hour causal residual correction, frozen ridge state, NESO feature family or forward start (`2026-08-21T11:30:00Z`).

## Maturity is determined only by sample size

| Forward rows | Stage |
|---:|---|
| 0–23 | `EARLY_ONLY` |
| 24–95 | `INTRADAY_TO_2DAY_MONITORING` |
| 96–335 | `MULTIDAY_MONITORING` |
| 336+ | `ONE_WEEK_PLUS_FORWARD` |

The stage cannot change because performance is good or bad.

## Cumulative metrics

Every run reports the same cumulative forward metrics for adaptive v0.25, frozen v0.20 2h and the previous-settlement-day reference:

- MAE and relative improvement;
- win rate of adaptive versus reference and frozen;
- signed forecast bias;
- P95 absolute error;
- causal correction mean, standard deviation, minimum and maximum.

## Rolling windows

Rolling windows are emitted only when enough forward rows exist:

- 12 rows = 6 hours;
- 48 rows = 24 hours;
- 144 rows = 3 days;
- 336 rows = 7 days.

A shorter sample never gets padded or mixed with pre-v0.25 development rows.

## Degradation alerts

No performance alert is allowed before 48 new forward half-hours. Until then the state is `INSUFFICIENT_SAMPLE_FOR_ALERTS`.

From 48 rows onward, the most recent 24 hours can raise only these predeclared alerts:

- `ADAPTIVE_TRAILS_REFERENCE_24H` — adaptive MAE exceeds the previous-day reference MAE;
- `ADAPTIVE_TRAILS_FROZEN_24H` — adaptive MAE exceeds the unchanged frozen-model MAE;
- `BIAS_CORRECTION_WORSENED_24H` — absolute adaptive signed bias exceeds absolute frozen-model signed bias.

There is intentionally no post-hoc 5%, 10% or other performance margin. Correction stability is reported numerically rather than used to invent a new threshold after seeing outcomes.

## Versioning and lineage

The first v0.25 forward artifact (`32500771812`, SHA-256 `64d30a6e18a2c3fa2243fa28ceb800afec1abc66f7dc0816515d96ff9faf885c`) remains immutable and contains six targets from 11:30 to 14:30 UTC. Those six rows stay `EARLY_ONLY` and are not a headline claim.

Later runs may extend the **same** candidate with later targets and record their lineage anchor. If the 48-hour lookback, residual estimator, minimum-history rule, frozen base model or feature family changes, the changed forecast must receive a new version and a new forward start. Previously observed v0.25 rows cannot be relabelled as fresh evidence for that changed model.

These are forecasting diagnostics on public market data, not realised trading P&L.
