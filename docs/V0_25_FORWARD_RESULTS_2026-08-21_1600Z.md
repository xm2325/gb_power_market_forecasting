# v0.25 adaptive 2h forward results — 2026-08-21 16:00 UTC

This is the second immutable v0.25 forward snapshot. The candidate rule is unchanged from the first six observations: the frozen v0.20 2h ridge forecast plus the mean causally available `realised - frozen_prediction` residual over the preceding 48 hours.

The network-enabled rerun used the same original v0.25 workflow/model commit and extended the safe scoring boundary from 14:30 to 16:00 UTC (end exclusive). It produced artifact `9456405888`, SHA-256 `846545d52b4ff0c290a63f2c81059396f79d7c6c5e7edb9dbcef4815aa6ddb0d`.

## Integrity before accuracy

The original six forward rows were reconstructed first. Their canonical row hashes and complete hash-chain prefix exactly match `reports/monitoring/V0_25_FORWARD_LEDGER_FIRST6.csv`; the locked first-six chain tip remains:

`b27a99b21466c8a4cbf58d29ad9c980a174b278cee1a741582a978af747789f2`

Three later targets were then appended at 14:30, 15:00 and 15:30 UTC. The nine-row chain tip is:

`f857a1f7f069961624cc3cb5d1f4e544e942d06658882ed56f519b09429257c6`

The full nine-row ledger is `reports/monitoring/V0_25_FORWARD_LEDGER_2026-08-21_1600Z.csv`, SHA-256 `2394a0932d7a048abe2ba4181798212a4cbe69ec560ff3837c0af1cf32a5617a`.

## Cumulative nine-row view

| Forecast | MAE (£/MWh) | P95 absolute error (£/MWh) | Signed bias (£/MWh) |
|---|---:|---:|---:|
| adaptive v0.25 | **5.357** | **14.512** | +0.493 |
| frozen v0.20 2h | 11.241 | 16.583 | -9.254 |
| previous-settlement-day reference | 8.670 | 15.620 | +8.670 |

Across all nine rows, adaptive MAE is 38.2% lower than the reference and 52.3% lower than the frozen model. It has lower absolute error than each baseline on 7/9 targets.

These cumulative values are still `EARLY_ONLY` and are not a headline model-performance claim.

## The three newly appended rows are weaker

The latest increment must be inspected separately rather than hidden inside the favourable first six rows:

| Forecast | MAE (£/MWh) | P95 absolute error (£/MWh) | Signed bias (£/MWh) |
|---|---:|---:|---:|
| adaptive v0.25 | **8.353** | 17.355 | +8.323 |
| frozen v0.20 2h | **7.352** | 9.638 | -1.391 |
| previous-settlement-day reference | **7.557** | 9.236 | +7.557 |

On these three observations alone, adaptive MAE is 10.5% worse than the reference and 13.6% worse than the frozen model. The correction still beat the previous-day reference on 2/3 targets, but it beat the frozen point forecast on only 1/3.

The 15:30 UTC target is especially informative: the frozen forecast had moved above the realised price, but the still-positive 48-hour level correction pushed the adaptive forecast further upward. This is a concrete example of correction lag/overshoot during a changing level regime.

No v0.25 rule is changed in response to these observations. They remain part of the same forward evidence stream.

## Uncertainty diagnostic

The adaptive interval is the frozen conformal interval translated by the same causal level correction. It is not recalibrated using v0.25 forward labels.

Across the nine observed rows, both frozen and translated adaptive intervals cover 9/9 targets. Mean interval width is unchanged at 69.447 £/MWh. With only nine targets this is descriptive only and provides no independent coverage claim.

## Evidence state

- maturity: `EARLY_ONLY`;
- degradation alerts: `INSUFFICIENT_SAMPLE_FOR_ALERTS` because fewer than 48 forward rows exist;
- promotion readiness: `NOT_ELIGIBLE_INSUFFICIENT_ROWS`;
- promotion minimum: 336 rows;
- rows still needed before promotion criteria may even be evaluated: 327.

The monitoring policy is deliberately unchanged after observing this weaker increment. The next evidence stages are determined by sample size, not by whether accuracy happens to improve.

Source and lineage records:

- `reports/monitoring/V0_25_MONITOR_STATE_2026-08-21_1600Z.json`;
- `reports/monitoring/V0_25_FORWARD_LEDGER_2026-08-21_1600Z.csv`;
- `reports/monitoring/V0_25_FORWARD_SNAPSHOT_REGISTRY.json`;
- `docs/V0_25_MONITORING_POLICY.md`;
- `docs/V0_25_UNCERTAINTY_CONTRACT.md`.

These are forecasting diagnostics on public market data, not realised trading P&L.
