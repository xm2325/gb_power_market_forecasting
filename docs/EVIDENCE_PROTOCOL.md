# v0.20 real-run evidence protocol

## Question

After the network-enabled NESO + Elexon workflow finishes, which numerical results are safe to use in an application, which are real but negative/fallback findings, and which remain blocked by evidence quality?

## Inputs

The evidence builder reads the exact network-run outputs under `reports/v19_real_market/`:

- Elexon coverage audit;
- real price benchmark for 30 min, 2 h, 6 h and 12 h;
- real NESO physical forecast benchmark when present;
- NESO download manifest;
- NESO materialisation manifest;
- Elexon download manifest.

Every present input is hashed with SHA-256. `evidence_id_sha256` is derived from the sorted source fingerprints and is independent of report-generation time.

## Claim classes

`REAL_CLAIMABLE_POSITIVE` means the complete real-data gate passed, the model was actually promoted, and final-window MAE improved against the fixed previous-settlement-day reference.

`REAL_NEGATIVE_RESULT` means the real-data gate passed and a promoted candidate reached the independent final window but did not improve it. It is valid held-out evidence but not a positive CV win.

`REAL_FALLBACK_RESULT` means the real-data gate passed but the deployment rule selected the previous-settlement-day fallback. This is a valid governance outcome, not a model-performance improvement.

`BLOCKED_EVIDENCE` means a required evidence component is absent or failed. Numerical claims remain prohibited.

## Output boundary

The CV-safe summary only emits new positive numerical claims for `REAL_CLAIMABLE_POSITIVE` horizons. The interview-safe summary preserves positive, negative and fallback real-data outcomes with their evidence class. Synthetic rehearsal numbers never enter either path as real claims.

No result is described as Volcore trading P&L because positions, nominations, execution, fees and portfolio netting are not public inputs to this project.
