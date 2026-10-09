# Paired v0.28 / v0.29 effect tracking

This report is derived from *two existing Git-frozen and separately scored*
forward streams. It does **not** reconstruct missing predictions, score targets
before their maturity boundary or edit locked v0.20-v0.27 evidence.

A pair is accepted only if:

- the UTC target start is identical;
- each stream has both a pretarget prediction and its scored outcome;
- v0.29 scoring explicitly verified the original prediction's pretarget Git
  commit; v0.28 and v0.29 score files contain prediction fingerprints;
- both retrieved observed market outcomes are numerically identical within
  1e-8 GBP/MWh;
- the previous-settlement-day baseline is identical within 1e-8 GBP/MWh;
- both decision timestamps precede the target and differ by at most **15 minutes**.

Excluded records are counted with a specific reason. Targets missing from
either stream are never added to the matched sample. Previous-day mismatches
can arise from data versions, publication/update timing or data defects and
should be audited rather than forcibly reconciled.

The six displayed models are previous_day, v28_consensus, v28_direction_veto,
v29_ridge_delay_safe, v29_ridge_consensus and v29_ridge_direction_veto. The
report shows matched-row MAE, P95 absolute error, signed bias, and MAE gain
against the common previous-day reference. It never automatically selects or
promotes a model.

The first review maturity threshold is 336 matched half-hours. This is a
review threshold only, not a significance threshold. Even within the 15-minute
issue-time gate, model inputs and observation snapshots may differ between
the two workflow runs. Consequently this is **descriptive same-target forward
evidence, not an identical-information-set causal comparison**.

Machine-readable derived report:

reports/forward/v29/paired_v28_v29_latest.json

This file can be updated from eligible source records. Original prediction
and score JSON files remain immutable. On an empty intersection, the report
must be WAIT_FOR_MATCHED_SCORES and all numerical metrics must be null.
