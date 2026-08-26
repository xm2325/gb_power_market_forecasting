# v0.25 forward snapshot 4

Locked unchanged candidate: `2H_FROZEN_PLUS_CAUSAL_48H_RESIDUAL_MEAN`.

- forward rows: **66** (53 new since the preceding locked snapshot);
- end exclusive: `2026-08-22T20:30:00+00:00`;
- adaptive MAE: **21.918 £/MWh**;
- frozen-model MAE: **20.082 £/MWh**;
- previous-day reference MAE: **39.545 £/MWh**;
- cumulative adaptive improvement vs reference: **44.6%**;
- cumulative adaptive improvement vs frozen: **-9.1%**;
- maturity: `INTRADAY_TO_2DAY_MONITORING`;
- alert status: `ALERTS_PRESENT`; alerts: `ADAPTIVE_TRAILS_FROZEN_24H`, `BIAS_CORRECTION_WORSENED_24H`;
- promotion status: `NOT_ELIGIBLE_INSUFFICIENT_ROWS`.

## Predeclared latest-24h monitor

- adaptive MAE: **26.853 £/MWh**;
- frozen MAE: **22.796 £/MWh**;
- reference MAE: **50.780 £/MWh**;
- adaptive signed bias: **16.991 £/MWh**;
- frozen signed bias: **12.754 £/MWh**;
- adaptive P95 absolute error: **60.237 £/MWh**;
- frozen P95 absolute error: **55.844 £/MWh**.

The alert rules were fixed before these 48 rows were available. Triggered alerts are preserved rather than tuned away.

## Integrity

- GitHub Actions run: `32602423009`;
- artifact ID: `9483291389`;
- artifact SHA-256: `eb2585458aaddb15a2485b4f5c349e8f90917cfc97bbdbe179cf95009e90ab95`;
- locked ledger SHA-256: `ef4511c598e8391a3d0ca8d91d116a750c498beafa81cc8ecc0cf85bfd71c558`;
- ledger chain tip: `b618989dcd02f066cc3e6e38444ceb06eee549820a675d4142ed45094d33ba00`.

Public-data metrics are forecasting evidence, not realised trading P&L.
