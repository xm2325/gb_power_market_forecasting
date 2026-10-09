# v0.24 continuous forward validation

## Purpose

v0.24 replaces the idea that forecasting quality should only be inspected at one delayed reveal date. A production-style forecasting team needs to know continuously whether an unchanged model is still useful.

The v0.20 locked benchmark remains immutable. v0.24 does **not** refit or reselect the model. It repeatedly replays the exact frozen v0.20 model states on observed market outcomes and records how performance changes through time.

## Fixed model identity

All monitoring runs use the exact serialised model state in:

`reports/locked/V0_21_FROZEN_MODEL_STATE.json`

File SHA-256:

`e9952aa88ca56b85f4d595bfe918cdc589ac0048d717d3fb3d9210361eb18918`

The model family, feature order, alpha, scaler, coefficients and conformal residual quantile are unchanged during a v0.24 monitoring segment.

## Monitoring views

Each run reports the same frozen model through several explicitly labelled views.

### 1. Locked final full

`2026-07-12T12:00:00Z` to `2026-08-15T07:30:00Z`

This reconstructs the already locked v0.20 historical out-of-sample period. It is useful for continuity and daily diagnostics, but the immutable v0.20 result remains the authoritative headline benchmark.

### 2. August recent regime

`2026-08-01T00:00:00Z` to the latest safe available target.

This deliberately mixes the latter part of the historical final period and later post-lock observations. It answers an operational question: how has the frozen model behaved in the most recent market regime? It is not a new independent test claim.

### 3. Post-lock forward monitoring

`2026-08-15T07:30:00Z` to the latest safe available target.

These observations arrived after the frozen v0.20 model state. They are forward-monitoring evidence. They may be inspected continuously; once inspected, they are not later relabelled as untouched confirmatory data.

### 4. Rolling operational windows

The monitor reports the latest 24 hours, 3 days and 7 days. These are operational diagnostics, not independent model-selection evidence.

## Outputs

For every horizon (30m, 2h, 6h, 12h), the monitor stores row-level:

- target and decision timestamps;
- realised Market Index Price;
- frozen-model prediction;
- previous-settlement-day/same-period reference;
- model and reference absolute error;
- model-minus-reference error difference;
- conformal interval and coverage indicator;
- cumulative MAE and cumulative error advantage;
- rolling 24h, 3d and 7d MAE/improvement.

It also stores UTC-day summaries and fixed segment summaries with MAE, P95 absolute error, direction accuracy, interval coverage and model win rate.

## Information safety

Forecast features remain as-of safe. A NESO-level model fails closed if any selected forecast publication is later than its decision time. Monitoring coverage is calculated against the expected half-hour UTC grid and duplicate/off-grid rows fail closed.

## Versioning rule

Continuous observation is allowed. Model rewriting is not.

If performance monitoring motivates a change to features, family, alpha, coefficients, scaler, calibration or decision logic, that change receives a new model/version identifier and a new forward segment beginning after the change is frozen. The old v0.20/v0.24 curves remain unchanged and visible.

Therefore:

- monitoring data may be used to diagnose failure;
- a revised model may be developed using already observed data;
- the revised model must not claim the already observed monitoring period as fresh prospective evidence.

## Claim boundary

v0.24 is intended to show model stability, degradation and regime dependence over time. It does not convert monitoring observations into realised trading P&L and it does not rewrite the locked v0.20 benchmark.
