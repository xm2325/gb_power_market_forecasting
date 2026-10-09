# v0.25 — causal 2h level adaptation

v0.24 continuous monitoring showed that the frozen 2h model retained useful correlation structure but developed a material negative level bias during the mid-August price regime. The v0.25 candidate deliberately does **not** replace the frozen ridge model or reselect its NESO feature family. It adds one small online correction layer.

## Candidate rule

For a 2h target starting at `t`, the original frozen prediction is made at `t - 120 minutes`. A historical target `s` may enter the correction only when its realised outcome is conservatively available by the current decision time:

` s + 30 minutes <= decision_time(t) `

Among eligible observations, v0.25 takes the mean residual `realised - frozen_prediction` over the preceding 48 hours, requiring at least 24 historical rows. The correction is then added to the unchanged frozen prediction.

This means the current target and the most recent 150 minutes of target labels cannot influence their own prediction.

## Why this candidate

The observed frozen 2h model was systematically low rather than simply noisy. On previously inspected rows, the mean under-prediction increased from about £8.2/MWh over the locked v0.20 final window to about £15.1/MWh after 15 August. A causal 48h residual mean is therefore a targeted level-adaptation mechanism, not a new high-capacity model.

Previously inspected development diagnostics are useful for design but are **not new independent evidence**:

| Segment | Frozen 2h MAE | Adaptive candidate MAE | Previous-day reference MAE | Adaptive vs reference |
|---|---:|---:|---:|---:|
| locked v0.20 final | 17.087 | 15.475 | 24.048 | 35.7% better |
| post-lock to candidate freeze | 16.875 | 10.698 | 15.885 | 32.6% better |

## Versioned forward boundary

The rule was frozen with a forward boundary of **2026-08-21 11:30 UTC**. Observations before that timestamp are development diagnostics. Observations at or after it belong to the v0.25 segment.

The first successful network run (`32500771812`) saw six new half-hours, 11:30–14:30 UTC (end exclusive):

- unchanged frozen v0.20 2h MAE: **13.185 £/MWh**;
- previous-settlement-day reference MAE: **9.227 £/MWh**;
- v0.25 adaptive candidate MAE: **3.859 £/MWh**;
- adaptive improvement versus reference: **58.2%**;
- adaptive improvement versus frozen model: **70.7%**;
- candidate beat the reference on **5/6** targets;
- mean causal correction: **+9.763 £/MWh**.

Six half-hours are far too few for a new headline performance claim. They are retained only as the first immutable forward-monitoring checkpoint.

## Versioning rule

If subsequent diagnosis changes the 48h lookback, residual statistic, minimum history, base model or feature family, that changed model receives a new version and a new forward start. The six observations above remain attached to v0.25 and are never recycled as fresh evidence for the changed candidate.

Machine-readable snapshot: [`reports/monitoring/V0_25_2H_ADAPTIVE_FORWARD_2026-08-21.json`](../reports/monitoring/V0_25_2H_ADAPTIVE_FORWARD_2026-08-21.json).

These are public-market forecasting diagnostics, not realised trading P&L.
