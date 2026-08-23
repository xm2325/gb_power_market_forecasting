# Rejected EWMA 2h development experiment — 2026-08-22

This record preserves a development experiment that was run after the v0.25 66-row degradation result. It is **not v0.26 forward evidence** and it is **not an alternative definition of v0.26**. The official v0.26 candidate remains `2H_FROZEN_PLUS_CAUSAL_6H_48H_CONSENSUS_CLIPPED_RESIDUAL`, with its independent forward boundary at `2026-08-22T20:30:00Z`.

## Why this record is retained

The experiment tested whether a causal exponentially weighted residual correction could react faster than the fixed 48h mean used by v0.25. The tested grid was fixed before chronological validation:

- half-life: 3h, 6h, 12h, 24h;
- shrinkage: 0.5 or 1.0;
- minimum causal history: 24 completed outcomes;
- selection objective: lowest MAE among candidates with non-worse frozen-model P95 absolute error and absolute signed bias;
- final gate: the selected rule must beat frozen and previous-day reference MAE on a later 96-row validation block, while also having non-worse frozen-model P95 absolute error and absolute signed bias.

All observations used here end no later than `2026-08-22T20:30:00Z`. They had already been observed and therefore remain development evidence only.

## Selection result

The selection block contained 266 chronological half-hours. The selected rule was `EWMA_24h_SHRINK_1`.

| Metric | Selected EWMA | Frozen 2h | Previous-day reference |
|---|---:|---:|---:|
| MAE (£/MWh) | **10.643** | 17.197 | 16.726 |
| P95 absolute error (£/MWh) | **27.712** | 38.412 | 36.813 |
| Signed bias (£/MWh) | **-0.659** | 15.901 | 1.330 |

On this selection block the EWMA rule reduced MAE by 38.1% relative to frozen and satisfied all selection guards.

## Chronological validation result

The final 96 rows were withheld from rule selection and then evaluated once.

| Metric | Selected EWMA | Frozen 2h | Previous-day reference |
|---|---:|---:|---:|
| MAE (£/MWh) | 19.440 | **18.188** | 29.821 |
| P95 absolute error (£/MWh) | 52.717 | **47.738** | 116.960 |
| Signed bias (£/MWh) | -10.497 | **-2.372** | -28.300 |

The selected EWMA remained 34.8% better than the previous-day reference on MAE, but it was 6.9% worse than the frozen model on MAE, 10.4% worse on P95 absolute error, and its absolute signed bias was more than four times the frozen-model value.

The predeclared validation gate therefore failed:

- `mae_better_than_frozen = false`;
- `mae_better_than_reference = true`;
- `p95_non_worse_than_frozen = false`;
- `absolute_bias_non_worse_than_frozen = false`;
- `forward_test_allowed = false`.

## Interpretation

This is useful negative evidence. A rule that looked much stronger on the earlier chronological selection block did not remain better than the unchanged frozen model after the regime moved. Starting a new forward test from this selected EWMA rule would therefore violate the development gate.

The experiment is archived as rejected development work. It must not be presented as a successful v0.26 model, must not use a new forward start, and must not replace or modify the official v0.26 consensus-clipped forward sequence.

## Source provenance

- development source run: `32602423009`;
- source artifact ID: `9483291389`;
- source artifact SHA-256: `eb2585458aaddb15a2485b4f5c349e8f90917cfc97bbdbe179cf95009e90ab95`;
- source input latest target: `2026-08-22T20:00:00Z`;
- original development decision status: `BLOCKED_BY_CHRONOLOGICAL_DEVELOPMENT_VALIDATION`.

The original experimental branch used the temporary name `feat/v026-causal-ewma-2h`. That name is historical only; the experiment did not become v0.26.
