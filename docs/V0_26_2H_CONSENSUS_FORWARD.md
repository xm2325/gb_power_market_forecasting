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

## Development diagnostic on the already-observed v0.25 window

Applying the frozen v0.26 rule retrospectively to the 66 rows that motivated the redesign gives:

| Model | MAE (£/MWh) |
|---|---:|
| v0.26 consensus candidate | **19.722** |
| frozen v0.20 2h | 20.082 |
| v0.25 48h correction | 21.918 |
| previous-day reference | 39.545 |

The consensus rule therefore removes much of the v0.25 overshoot on those observed rows and is 1.8% lower-MAE than frozen in this development diagnostic. It is not uniformly better: candidate P95 is 54.864 versus 52.287 frozen, absolute signed bias is 9.563 versus 7.046, and interval coverage is 77.3% versus 78.8%. These values are **development evidence only**.

## First fresh forward checkpoint

The first real v0.26 network run was GitHub Actions run `32604734019`. Tests were executed before accessing new labels; the safe data boundary was then fixed at `2026-08-22T21:30:00Z`.

Only **2 fresh half-hours** were available after the frozen v0.26 start:

| Model | MAE (£/MWh) |
|---|---:|
| v0.26 consensus candidate | 4.779 |
| frozen v0.20 2h | 4.155 |
| v0.25 48h correction | **4.095** |
| previous-day reference | 8.160 |

For these two rows, v0.26 is 41.4% better than the previous-day reference but 15.0% worse than frozen and 16.7% worse than v0.25 on mean MAE. One of the two targets fell back to frozen (`fallback_rate = 0.5`). Both frozen and v0.26 intervals covered both observations.

This checkpoint is deliberately labelled `EARLY_ONLY_2_ROWS_NO_HEADLINE_CLAIM`. Two observations cannot establish whether the consensus gate improves 2h forecasting, and the rule is **not changed** in response to this early result.

The first v0.26 forward ledger contains two rows and has chain tip:

`49cc9148d1756ff1fce3bdcac5f8f9405850cf516b0c701215e81121a7677f9d`

Evidence record:

- `reports/monitoring/V0_26_FIRST_FORWARD_CHECKPOINT_2026-08-22_2130Z.json`
- Actions run `32604734019`
- artifact `v26-consensus-2h-32604734019`, ID `9483846187`
- artifact SHA-256 `c26eccc3be5491bba50b2a583ebd3f7d169f7f10406974a080df6a4db663f6fb`

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

v0.26 is motivated by observed v0.25 degradation. Therefore retrospective performance before 20:30 UTC on 22 August is **development evidence**, regardless of how strong it looks. Only later observations can support new forward-performance evidence, and the first two such observations remain too early for a new accuracy claim.
