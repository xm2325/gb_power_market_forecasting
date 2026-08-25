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

## Recovery sequence 1 — preserved miss

A zero-outcome recovery lock was created at `2026-08-25T09:44:34.562278Z`, mechanically selecting:

- decision: `2026-08-25T10:00:00Z`;
- target: `2026-08-25T12:00:00Z`.

Live run `32833780952` waited until the locked decision before network access. It successfully completed bounded NESO download, decision-time NESO as-of filtering, exact Elexon history cutoff before `10:00Z`, market materialisation and frozen 2h replay.

The run then failed before writing a prediction because the adapter concatenated historical CSV timestamps using a space with a new ISO timestamp using `T`; Pandas 3 rejected the mixed string representation. The adapter was fixed by normalising both forms to UTC timestamps before concatenation. CI run `32835320286` passed. The predictive candidate itself was not modified.

Because the `12:00Z` target subsequently passed, it was not reconstructed retrospectively. `V0_27_PRETARGET_RECOVERY_1_MISSED.json` records `prediction_file_present=false` and `retrospective_prediction_reconstruction_allowed=false`.

## Recovery sequence 2 — successful pre-target Git prediction

A second atomic recovery advancement was created only after the first miss was immutable. Runtime lock timestamp:

`2026-08-25T12:47:06.253146Z`

The same deterministic rule selected:

- decision: **`2026-08-25T13:00:00Z`**;
- target: **`2026-08-25T15:00:00Z`**.

The original `02:30Z` forward start remains unchanged. No outcome was used to select the recovery boundary and no model/rule change was made.

One-shot run **`32849635253`** stayed at the no-network timing barrier until the locked 13:00 decision. It then completed every step successfully:

- bounded NESO download;
- hard as-of filtering to publications at or before the locked decision;
- exact Elexon history cutoff at `13:00Z` end-exclusive;
- decision-time market materialisation;
- unchanged frozen 2h replay;
- v0.27 direction-veto prediction;
- pre-target/no-label contract verification;
- Git commit and push before the target period began.

The frozen record is `reports/forward/v27/V0_27_PRETARGET_RECOVERY_2_PREDICTION.json`:

| Field | Frozen value |
|---|---:|
| decision time | `2026-08-25T13:00:00Z` |
| target start | `2026-08-25T15:00:00Z` |
| freeze completed | `2026-08-25T13:01:19.290770Z` |
| frozen 2h prediction | **92.923330 £/MWh** |
| v0.27 prediction | **97.513431 £/MWh** |
| v0.27 correction | **+4.590101 £/MWh** |
| previous-day reference | **118.320000 £/MWh** |
| v0.27 gate | `CONSENSUS_DIRECTION_ALIGNED_CORRECTION` |
| NESO selected publication | `2026-08-25T11:54:29Z` |
| target-label state | `UNOBSERVED_NOT_ACCESSED` |

The short causal residual mean was +4.590101 £/MWh over 12 rows and the long mean was +12.323757 £/MWh over 96 rows. The frozen model direction delta was +0.451149 £/MWh, so the positive residual correction was direction-aligned and the sign-only v0.27 veto allowed it.

The prediction file SHA-256 is `a94aa1c3f410c196bee4ab8276dd3f166b78a921ee7ada0cee0ba8c6633a6822`. Provenance records the implementation lock, recovery lock, frozen model state, Elexon history, NESO as-of file and historical frozen-row hashes and explicitly states `target_label_accessed=false`.

A repository-level regression test requires this exact prediction SHA and verifies the locked decision/target, pre-target freeze time, unchanged candidate blob, correction arithmetic and causal NESO publication time.

## First scored precommitted forward outcome

Scoring was a separate operation. For the `15:00Z` target, the 90-minute safety policy first allowed outcome access at **`2026-08-25T16:30:00Z`**. The scoring run `32871267883` stayed behind a no-network maturity barrier until that time, then downloaded only `[15:00Z, 15:30Z)`, joined the realised price to the existing Git-committed prediction, and did not recompute the forecast.

The realised market price was **133.73 £/MWh**. The single-row errors are:

| Model / reference | Prediction (£/MWh) | Absolute error (£/MWh) |
|---|---:|---:|
| v0.27 direction-veto candidate | **97.513431** | **36.216569** |
| unchanged frozen v0.20 2h | 92.923330 | 40.806670 |
| previous-settlement-day reference | 118.320000 | **15.410000** |

On this one row, the v0.27 correction reduced absolute error versus the frozen model by **4.590101 £/MWh**, exactly the size of the positive correction, but remained **20.806569 £/MWh worse than the previous-day reference**.

This result is intentionally mixed rather than presented as a win. It shows that the direction-aligned correction moved the frozen prediction in the correct direction for this target, while both model predictions still materially underpredicted the realised price and the simple previous-day reference was substantially closer.

The score is classified `SINGLE_PRECOMMITTED_FORWARD_OUTCOME_DESCRIPTIVE_ONLY`. `promotion_eligible=false` and `automatic_model_change=false`. Score provenance records `target_outcome_accessed_only_after_maturity_gate=true` and `prediction_recomputed_during_scoring=false`.

Score SHA-256: `6f1a8e0e75734c7bbb78715b35c91fd94544eb2a55e4a6b63e5cdaa00a39dff8`.

One genuinely precommitted scored row is useful evidence of the end-to-end causal process, but it is not sufficient to establish v0.27 superiority, trigger promotion, tune the candidate, or change the frozen comparison model.
