# v0.27 development protocol — independent validation before any new forward candidate

v0.26 crossed its first predeclared 48-row degradation-alert gate. Snapshot sequence 3 contains 51 genuine forward rows and shows that the consensus-clipped residual correction is 8.2% worse than the unchanged frozen 2h model. The root cause is a jointly stale same-sign residual episode across a sharp price turning point.

That 51-row window is therefore **failure-discovery data**. It may motivate a different v0.27 structure, but it cannot also be used as v0.27 validation or fresh v0.27 forward evidence.

## Champion remains unchanged

The unchanged frozen v0.20 2h model remains the champion. v0.26 is an alerted challenger and is not retuned after the sequence-3 alert.

## Single candidate now frozen before validation

One development candidate has now been selected and byte-locked before the independent validation workflow reads any later target labels:

`2H_FROZEN_PLUS_CAUSAL_6H_48H_CONSENSUS_WITH_FROZEN_DIRECTION_VETO`

It retains the unchanged v0.26 6h/48h causal consensus proposal and adds one sign-only safety veto. A proposed residual correction is applied only when its sign agrees with the direction of the frozen model from the latest causally available historical target to the current 2h target. If the frozen model has already turned in the opposite direction, the candidate falls back exactly to frozen.

There is **no magnitude threshold, no parameter sweep and no new residual lookback**. The structure directly addresses the sequence-3 failure mode: both residual windows can remain jointly stale even after the frozen model has turned.

Candidate lock: [`reports/locked/V0_27_CANDIDATE_LOCK.json`](../reports/locked/V0_27_CANDIDATE_LOCK.json).

The candidate is a **development candidate only**. Software version remains `0.26.0`; there is no v0.27 forward experiment yet.

## Independent development validation

The exact block for this candidate is now sealed as:

- start: `2026-08-23T22:00:00Z`;
- end-exclusive: `2026-08-24T22:00:00Z`;
- exactly **48 later half-hours / 24 hours**.

No alternative candidate may be tried on this block. Its equations, features, constants, information boundary and source identity are already fixed. After any row from this block is evaluated, changing the candidate requires a later independent block.

The validation workflow is manual and fails **before any network download** until the full block is mature under the existing 90-minute market-data safety lag.

The Elexon validation path also uses an exact start-time query rather than settlement-period filtering. The final API request stops at `2026-08-24T21:30:00Z` inclusive, so prices at or after the sealed `22:00Z` end are not written into validation inputs. This preserves later targets for any possible fresh forward experiment.

## Validation gate

All conditions are required:

1. candidate MAE is strictly lower than the unchanged frozen model;
2. candidate P95 absolute error is no worse than frozen;
3. absolute signed bias is no worse than frozen;
4. candidate MAE is strictly lower than the previous-settlement-day reference.

Passing this gate does **not** establish a production or CV performance claim. It only permits a separately versioned v0.27 forward experiment.

If the candidate fails, it is rejected for this block. It cannot be retuned and re-evaluated on these labels.

## New forward boundary

Only after the independent validation gate passes may the project create:

- software/candidate version `0.27.0`;
- a new forward implementation lock;
- a forward boundary strictly after the validation block and any labels accessed by validation;
- a fresh append-only ledger containing only outcomes unseen when the forward candidate is locked.

No candidate auto-promotes.

Machine-readable governing protocol: [`reports/locked/V0_27_DEVELOPMENT_PROTOCOL.json`](../reports/locked/V0_27_DEVELOPMENT_PROTOCOL.json).

The purpose of this protocol is to prevent the project from turning a genuine v0.26 failure into a post-hoc v0.27 success by reusing the same rows for discovery, tuning and validation.
