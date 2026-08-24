# v0.27 development protocol — independent validation before any new forward candidate

v0.26 has now crossed its first predeclared 48-row degradation-alert gate. Snapshot sequence 3 contains 51 genuine forward rows and shows that the consensus-clipped residual correction is 8.2% worse than the unchanged frozen 2h model. The root cause is a jointly stale same-sign residual episode across a sharp price turning point.

That 51-row window is therefore **failure-discovery data**. It may motivate a different v0.27 structure, but it cannot also be used as v0.27 validation or fresh v0.27 forward evidence.

## Champion remains unchanged

The unchanged frozen v0.20 2h model remains the champion. v0.26 is an alerted challenger and is not retuned after the sequence-3 alert.

No v0.27 predictive candidate exists yet.

## Candidate constraint

A future v0.27 proposal must address the observed jointly stale residual-window failure with a genuinely distinct causal structure or signal. Merely adding another residual lookback, sweeping lookback lengths, or tuning a threshold against the 51 alert rows is not sufficient.

At most **one fully specified candidate** may be evaluated on a given independent validation block. Its equations, features, constants, information boundary and implementation identity must be frozen before the validation labels are read.

The frozen v0.20 model state remains unchanged.

## Independent development validation

The validation block must:

- begin no earlier than `2026-08-23T22:00:00Z`, after the sequence-3 discovery window;
- contain at least **48 later half-hours / 24 hours**;
- preserve the same 2h causal decision-time information boundary;
- be untouched by parameter search or candidate selection;
- become development evidence after evaluation and never be relabelled as fresh v0.27 forward evidence.

If the candidate fails, it is rejected for that block. It cannot be retuned and re-evaluated on the same labels.

## Validation gate

All conditions are required:

1. candidate MAE is strictly lower than the unchanged frozen model;
2. candidate P95 absolute error is no worse than frozen;
3. absolute signed bias is no worse than frozen;
4. candidate MAE is strictly lower than the previous-settlement-day reference.

Passing this gate does **not** establish a production or CV performance claim. It only permits a separately versioned v0.27 forward experiment.

## New forward boundary

Only after the independent validation gate passes may the project create:

- software/candidate version `0.27.0`;
- a new candidate ID;
- a new predictive implementation byte lock;
- a forward boundary strictly after the validation block;
- a fresh append-only ledger containing only outcomes unseen when the candidate was frozen.

No candidate auto-promotes.

Machine-readable lock: [`reports/locked/V0_27_DEVELOPMENT_PROTOCOL.json`](../reports/locked/V0_27_DEVELOPMENT_PROTOCOL.json).

The purpose of this protocol is to prevent the project from turning a genuine v0.26 failure into a post-hoc v0.27 success by reusing the same 51 rows for discovery, tuning and validation.
