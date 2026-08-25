# v0.27 pre-target evidence recovery

This note separates three different things that must not be conflated:

1. the original v0.27 fresh-forward boundary;
2. whether a numerical prediction was Git-committed before a target outcome existed;
3. later scoring of an already committed prediction.

The predictive candidate remains byte-identical throughout:

`3c361dbb0e1665bbbad2e1097b8580ce062a203f`

## Original forward boundary

The v0.27 implementation lock was created at `2026-08-25T00:11:28.620570Z`. Its deterministic first decision was `00:30Z` and first target was `02:30Z`.

That original `02:30Z` forward start is never moved. The pre-target freeze window for the first numerical prediction was missed, so the repository deliberately does not contain a reconstructed `02:30Z` prediction.

## Recovery sequence 1

A zero-outcome recovery lock was created at `2026-08-25T09:44:34.562278Z`, which deterministically selected:

- decision: `2026-08-25T10:00:00Z`;
- target: `2026-08-25T12:00:00Z`.

Live run `32833780952` waited until the locked decision before network access. It then successfully completed:

- bounded NESO download;
- decision-time NESO as-of filtering;
- exact Elexon history cutoff before `10:00Z`;
- decision-time market materialisation;
- frozen 2h replay through the latest causally available target.

The run failed only when the prediction adapter concatenated historical CSV timestamps formatted with a space and a new ISO timestamp formatted with `T`. Pandas 3 rejected the mixed string representation before candidate arithmetic was applied. No prediction was committed.

The adapter was fixed by normalising both timestamp representations to UTC timestamps before concatenation. CI run `32835320286` passed after the fix. The predictive candidate itself was not modified.

Because the `12:00Z` target then passed, it was not reconstructed retrospectively. `V0_27_PRETARGET_RECOVERY_1_MISSED.json` records the miss and explicitly forbids retrospective substitution.

## Recovery sequence 2

A second atomic recovery advancement was created only after the first miss was immutable. Runtime lock timestamp:

`2026-08-25T12:47:06.253146Z`

The same deterministic rule selected:

- decision: **`2026-08-25T13:00:00Z`**;
- target: **`2026-08-25T15:00:00Z`**.

The original `02:30Z` forward start remains unchanged. No outcome was used to select the new boundary and no model/rule change was made.

The one-shot sequence-2 freeze run is `32849635253`. Before `13:00Z` it is required to remain at the timing barrier with all market-data steps pending. After the decision it may read only decision-time information, hard-filter NESO publications to `publish_time <= 13:00Z`, and cap Elexon history at `target_start < 13:00Z`. If a prediction is successfully produced, it must be committed before `15:00Z` with the target marked `UNOBSERVED_NOT_ACCESSED`.

## Scoring boundary

Scoring is a separate operation. For the `15:00Z` target, the 90-minute safety policy means the first allowed scoring time is **`2026-08-25T16:30:00Z`**.

The scorer is pre-registered before the outcome is read. It joins the realised target to the already Git-committed prediction; it does not recompute the prediction. A single scored row is classified `SINGLE_PRECOMMITTED_FORWARD_OUTCOME_DESCRIPTIVE_ONLY` and is never sufficient for promotion, tuning, or an automatic model change.
