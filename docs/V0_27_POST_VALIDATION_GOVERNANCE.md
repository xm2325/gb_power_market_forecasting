# v0.27 post-validation governance

This document governs what may happen **after** the single sealed v0.27 development-validation block is evaluated. It does not change the byte-locked development candidate or its validation labels.

## Result locking

The `validate-v27-development` artifact is not authoritative merely because a workflow completed. A separate `lock-v27-development-result` workflow must:

1. verify the source GitHub Actions run is exactly `validate-v27-development` and concluded successfully;
2. verify the unique artifact name, artifact ID, non-expired state and GitHub SHA-256 digest;
3. verify the embedded candidate lock is byte-identical to the repository lock;
4. verify exactly 48 contiguous targets in `[2026-08-23T22:00:00Z, 2026-08-24T22:00:00Z)`;
5. verify the four predeclared gates and provenance are internally consistent;
6. copy the result, provenance and rows byte-for-byte into immutable monitoring paths;
7. derive the next state rather than accepting it as user input.

The lock refuses to overwrite an existing validation result.

## Two possible states

If **any** validation gate fails, the derived state is:

`CANDIDATE_REJECTED_ON_SEALED_BLOCK`

The same candidate cannot be retuned and re-evaluated on those 48 labels. A later candidate would require a new structure and a later independent development-validation block.

If **all** gates pass, the derived state is:

`ELIGIBLE_TO_CREATE_FRESH_V27_FORWARD_LOCK`

This is permission to create a separately versioned `0.27.0` implementation lock only. It is not forward evidence and does not auto-launch anything.

## Deterministic forward boundary

A passing candidate cannot choose its forward start by inspecting later prices. After the new `0.27.0` implementation lock has a timestamp, the boundary is deterministic:

1. take the next 30-minute decision grid **strictly after** the implementation-lock timestamp;
2. add the fixed 120-minute forecast horizon;
3. use that target as the first forward target.

For example, a lock at `2026-08-24T23:42:10Z` gives a first decision at `2026-08-25T00:00:00Z` and a first target at `2026-08-25T02:00:00Z`.

This guarantees that the first forward decision occurs after the candidate is formally locked and prevents cherry-picking the start time from already observed post-validation prices.

Machine-enforced implementation: `src/gb_power_market/v27_forward_governance.py`.

## Claim boundary

The 48 validation labels become development evidence immediately after evaluation. They can never be relabelled as fresh v0.27 forward evidence. Public market-data metrics remain forecasting evidence rather than realised trading P&L.
