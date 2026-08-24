# v0.27 development candidate lock — sign-only frozen-direction veto

## Status

This is a **frozen development candidate**, not a launched v0.27 forward model and not a performance claim.

Candidate ID:

`2H_FROZEN_PLUS_CAUSAL_6H_48H_CONSENSUS_WITH_FROZEN_DIRECTION_VETO`

The unchanged frozen v0.20 2h model remains champion. v0.26 remains an alerted challenger.

## Why this structure exists

The locked 51-row v0.26 sequence showed a specific failure that the sign-consensus gate did not prevent. During the dominant 16-row failure block, both 6h and 48h residual means stayed negative while the frozen model and realised market price had already turned sharply upward. The residual correction therefore remained jointly stale and amplified underprediction.

The new candidate does not add another residual window and does not tune a threshold. Instead it asks whether the frozen model itself has already turned relative to the latest target whose outcome is causally available at the current decision time.

## Exact rule

1. Compute the unchanged v0.26 causal 6h/48h consensus proposal.
2. Identify the latest residual-history target whose outcome is available by the current 2h decision time.
3. Compute `frozen_direction = current_frozen_prediction - anchor_frozen_prediction`.
4. If the v0.26 proposed correction is zero, inherit the existing v0.26 fallback.
5. If the correction sign and `frozen_direction` sign disagree, or the frozen direction is exactly zero, veto the correction and use the unchanged frozen prediction.
6. Otherwise apply the unchanged v0.26 proposed correction.

There is no learned coefficient, magnitude threshold or parameter search.

## Information boundary

The candidate uses only:

- the byte-locked v0.26 residual-history computation;
- frozen predictions already produced by the unchanged v0.20 model;
- the latest historical target already causally available at decision time.

The current target outcome and future target outcomes cannot affect the current prediction. Synthetic regression tests explicitly perturb current/future realised prices and require the current candidate prediction to remain unchanged.

## Byte lock

- candidate source: `src/gb_power_market/adaptive_direction_v27_candidate.py`;
- candidate source Git blob: `3c361dbb0e1665bbbad2e1097b8580ce062a203f`;
- v0.26 dependency Git blob: `399915c6cdd0d3b016bde73cb0ef92eb2697adf8`;
- frozen model-state SHA-256: `e9952aa88ca56b85f4d595bfe918cdc589ac0048d717d3fb3d9210361eb18918`.

Machine-readable lock: [`reports/locked/V0_27_CANDIDATE_LOCK.json`](../reports/locked/V0_27_CANDIDATE_LOCK.json).

## Sealed validation block

The one permitted independent development-validation block for this candidate is exactly:

`[2026-08-23T22:00:00Z, 2026-08-24T22:00:00Z)`

That is 48 half-hours / 24 hours. The workflow cannot access validation market data until the entire block is mature under the 90-minute safety lag. It then evaluates MAE, P95 absolute error, absolute signed bias and the previous-day reference gate. Pass or fail, these labels immediately become development data and can never become fresh v0.27 forward evidence.

A failure ends this candidate on this block. A pass only permits a new `0.27.0` forward lock with a later unseen boundary; it does not establish a headline result.
