# v0.27 sealed development-validation result

Candidate: `2H_FROZEN_PLUS_CAUSAL_6H_48H_CONSENSUS_WITH_FROZEN_DIRECTION_VETO`.

Validation block: `2026-08-23T22:00:00+00:00` to `2026-08-24T22:00:00+00:00` end-exclusive (**48 half-hours**).

| Metric | Candidate | Frozen |
|---|---:|---:|
| MAE (£/MWh) | 15.189 | 15.542 |
| P95 abs error (£/MWh) | 33.850 | 38.604 |
| Signed bias (£/MWh) | -12.253 | -13.630 |

Previous-day reference MAE: **32.788 £/MWh**.

Gates:

- `candidate_mae_strictly_better_than_frozen`: **PASS**;
- `candidate_p95_abs_error_non_worse_than_frozen`: **PASS**;
- `candidate_absolute_signed_bias_non_worse_than_frozen`: **PASS**;
- `candidate_mae_strictly_better_than_previous_day_reference`: **PASS**;

Overall validation: **PASS**.
Forward eligibility state: `ELIGIBLE_TO_CREATE_FRESH_V27_FORWARD_LOCK`.

This result is development validation only. It never auto-launches forward evidence. A failed candidate cannot be retuned on these labels; a passing candidate still requires a new implementation lock and a strictly later unseen forward boundary.
