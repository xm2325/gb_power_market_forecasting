# v0.26 gate-effectiveness diagnostic — locked sequence 2

This note explains the behaviour of the already-frozen v0.26 consensus gate on the **23 genuine forward rows** locked as snapshot sequence 2. It is a descriptive monitoring analysis, not a new candidate-selection exercise.

## Locked forward context

- candidate: `2H_FROZEN_PLUS_CAUSAL_6H_48H_CONSENSUS_CLIPPED_RESIDUAL`;
- forward start: `2026-08-22T20:30:00Z`;
- snapshot end exclusive: `2026-08-23T08:00:00Z`;
- rows: **23**;
- source run: `32632409230`;
- artifact ID: `9491420056`;
- artifact SHA-256: `06d21cd67b40d3143ba472f412e2e2e3f403691d43f01ba71b810b96bddda249`;
- locked ledger chain tip: `487f1e33478f9c07a25b088b1297d8aa170db9959642e108388bebd613765ca2`.

Across these 23 rows, v0.26 MAE is **7.623 £/MWh**, compared with **7.569** for the unchanged frozen 2h model, **9.219** for v0.25 and **18.799** for the previous-day reference. v0.26 is therefore not yet better than frozen: it trails by about **0.7%**. It is, however, **17.3% better than v0.25** and **59.4% better than the previous-day reference** on this early forward segment.

## What the consensus gate actually did

Only **1 of 23 rows** applied a non-zero consensus correction. The remaining **22 rows** were `REGIME_DISAGREEMENT_FALLBACK_FROZEN`, giving a 95.7% fallback rate. The sequence ends with **22 consecutive disagreement fallbacks**.

The single applied correction had magnitude **1.248 £/MWh** and was worse than frozen on that observation. The important behaviour is therefore not that the correction itself has demonstrated an accuracy gain; it has not. The current value of v0.26 is that disagreement between the recent 6h residual and the slower 48h residual prevents the stale v0.25 correction from being carried forward.

## Did fallback avoid the v0.25 failure mode?

Yes on most of the observed fallback rows. Among the 22 rows where v0.26 reverted to frozen:

- v0.25 had larger absolute error than frozen on **19 rows**;
- v0.25 was better than frozen on **3 rows**;
- the fallback decisions avoided **36.151 £/MWh** of aggregate absolute error versus continuing v0.25;
- that equals **1.643 £/MWh per fallback row** on average.

Across all 23 rows, v0.26 avoided **36.705 £/MWh** of aggregate absolute error versus v0.25, or **1.596 £/MWh per row** on average.

These numbers explain why v0.26 is materially better than v0.25 while still being almost identical to frozen: the gate is mostly acting as a conservative safety mechanism during a residual-regime reversal rather than as an active correction model.

## Claim boundary

This diagnostic was derived **after snapshot sequence 2 had already been locked**. It does not alter the append-only registry, predictive source, frozen model state, alert thresholds, promotion rules, or forward boundary. It must not be used to retune v0.26 and then reuse these same 23 observations as fresh evidence.

Performance alerts remain unavailable before **48 forward rows**. Promotion review remains unavailable before **336 half-hours / 7 days**, and no rule auto-promotes a model.

Machine-readable companion: `reports/monitoring/V0_26_GATE_DIAGNOSTIC_2026-08-23_0800Z.json`.
