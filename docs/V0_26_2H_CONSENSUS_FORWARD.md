# v0.26 — causal 6h/48h consensus-clipped 2h correction

## Why a new version exists

v0.25 used the mean frozen-model residual over the previous 48 hours as a causal level correction. Its first 13 forward half-hours looked encouraging, but after 66 rows the pre-registered 24-hour monitor raised two degradation alerts:

- `ADAPTIVE_TRAILS_FROZEN_24H`;
- `BIAS_CORRECTION_WORSENED_24H`.

Across the 66-row v0.25 segment, the 48h correction still beat the previous-settlement-day reference (21.918 vs 39.545 £/MWh MAE) but trailed the unchanged frozen 2h model (20.082 £/MWh). In the newest 53 rows after the 13-row checkpoint, adaptive MAE was about 25.62 versus 22.35 frozen and 46.89 reference. This is evidence of correction lag/overshoot, not evidence that the frozen 2h model should be refit.

The v0.25 rule is therefore preserved unchanged as historical evidence. v0.26 is a separately versioned candidate.

## Frozen v0.26 rule

Candidate ID:

`2H_FROZEN_PLUS_CAUSAL_6H_48H_CONSENSUS_CLIPPED_RESIDUAL`

For target `t`, the underlying v0.20 2h ridge prediction remains unchanged. The candidate computes residual means using only outcomes already available by the 2h decision time:

- short window: 6 hours;
- long window: 48 hours;
- outcome availability delay: 30 minutes.

No parameter search is performed. The 48h window is inherited from v0.25; the 6h window is inherited from the pre-registered v0.25 monitoring policy.

The correction is:

1. zero if either window has insufficient causal history;
2. zero if the 6h and 48h residual means disagree in sign;
3. otherwise the common sign multiplied by the smaller absolute residual mean.

This creates two conservative behaviours:

- **regime disagreement → frozen fallback** rather than carrying a stale correction forward;
- **same-sign but different magnitude → clipped correction** rather than following the larger estimate.

Frozen conformal interval endpoints, when present, are translated by exactly the same level correction; interval width is not recalibrated on v0.26 outcomes.

## Evidence boundary

The rule and tests were committed before reading v0.26 outcomes.

- development end / v0.26 forward start: **2026-08-22 20:30 UTC**;
- all earlier observations, including the 66-row v0.25 segment, are development diagnostics only;
- only targets at or after `2026-08-22T20:30:00Z` belong to the versioned v0.26 forward segment;
- if the consensus rule, windows, clipping rule or frozen point model changes later, that change must receive a new version and new forward start.

## Monitoring

The new candidate keeps the existing outcome-independent monitoring cadence:

- 0–23 rows: `EARLY_ONLY`;
- 24–95: `INTRADAY_TO_2DAY_MONITORING`;
- 96–335: `MULTIDAY_MONITORING`;
- 336+: `ONE_WEEK_PLUS_FORWARD`.

Performance alerts remain disabled before 48 forward rows. At 48+ rows, the latest 24h window can flag:

- candidate trails frozen;
- candidate trails previous-day reference;
- candidate absolute signed bias exceeds frozen absolute signed bias.

No candidate is automatically promoted. Seven days / 336 forward half-hours remain the earliest eligibility point for human review.

## Claim boundary

v0.26 is motivated by observed v0.25 degradation. Therefore retrospective performance before 20:30 UTC on 22 August is **development evidence**, regardless of how strong it looks. Only later observations can support a new forward-performance statement.
