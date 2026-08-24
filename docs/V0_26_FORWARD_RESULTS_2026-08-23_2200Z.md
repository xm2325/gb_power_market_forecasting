# v0.26 forward snapshot 3

Locked unchanged candidate: `2H_FROZEN_PLUS_CAUSAL_6H_48H_CONSENSUS_CLIPPED_RESIDUAL`.

- forward rows: **51** (28 new since the preceding locked snapshot);
- end exclusive: `2026-08-23T22:00:00+00:00`;
- candidate MAE: **17.102 £/MWh**;
- frozen-model MAE: **15.802 £/MWh**;
- v0.25 MAE: **18.243 £/MWh**;
- previous-day reference MAE: **19.527 £/MWh**;
- candidate improvement vs frozen: **-8.2%**;
- candidate improvement vs reference: **12.4%**;
- maturity: `INTRADAY_TO_2DAY_MONITORING`;
- alert status: `ALERTS_PRESENT`; alerts: `V26_TRAILS_FROZEN_24H`, `V26_BIAS_WORSE_THAN_FROZEN_24H`;
- promotion status: `NOT_ELIGIBLE`.

## Integrity

- GitHub Actions run: `32675196453`;
- execution commit: `a2d536c3ce35a51ec4dc69189c65023bc9e258d5`;
- predictive source blob: `399915c6cdd0d3b016bde73cb0ef92eb2697adf8`;
- frozen model-state SHA-256: `e9952aa88ca56b85f4d595bfe918cdc589ac0048d717d3fb3d9210361eb18918`;
- artifact ID: `9502476322`;
- artifact SHA-256: `a162270d94528429c0d3dcca89152f57fba9ed12654b0a2b70fbb0386fa8af1a`;
- locked checkpoint SHA-256: `86464b385071d516b37ae06a9f1237eb4cda62456b00de9ca7504751c27c58d8`;
- locked provenance SHA-256: `0dabb5f9920de7d693267f146676747846363dcac8757681f8a39ac0e86365b9`;
- locked ledger SHA-256: `529952d0e7dfa6f0446cebecc4ee9733779fde720645556509ca677e04f5b08a`;
- ledger chain tip: `dca4ef5173dcf18a81814a2bcfadaea72c4ed5fa5abc1b1c78555e55129e4a8b`.

Rows before the v0.26 forward boundary are development diagnostics, not fresh v0.26 evidence.
Public-data metrics are forecasting evidence, not realised trading P&L.
