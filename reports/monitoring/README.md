# Continuous monitoring snapshots

This directory stores **dated, immutable monitoring snapshots** produced by frozen-model forward validation.

Rules:

1. A successful monitoring run creates a new dated record; it does not overwrite an older snapshot.
2. The frozen model-state SHA and source/run identity are recorded with each snapshot.
3. Historical locked-test rows, recent-regime rows, post-lock forward rows and rolling operational windows retain distinct evidence roles.
4. Monitoring outcomes may be inspected and used for diagnosis.
5. If diagnosis leads to a model change, the changed model receives a new model/version identifier and a new forward segment beginning after that model is frozen. Previously observed rows are not relabelled as fresh prospective evidence.
6. Monitoring results are forecasting diagnostics on public market data, not realised trading P&L.

Current snapshot:

- [`V0_24_CONTINUOUS_FORWARD_2026-08-21.json`](V0_24_CONTINUOUS_FORWARD_2026-08-21.json)
