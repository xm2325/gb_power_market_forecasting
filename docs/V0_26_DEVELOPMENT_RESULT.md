# v0.26 causal EWMA development decision

Status: **`BLOCKED_BY_CHRONOLOGICAL_DEVELOPMENT_VALIDATION`**.

v0.26 was developed only on observations already available through `2026-08-22T20:30Z`. The last 96 observed half-hours were excluded from half-life/shrinkage selection and used only as chronological development validation.

Selection winner: **`EWMA_24h_SHRINK_1`**.

## Selection block

| Model | MAE £/MWh | P95 abs error £/MWh | Signed bias £/MWh |
|---|---:|---:|---:|
| EWMA_24h_SHRINK_1 | 10.642641 | 27.712209 | -0.659387 |
| Frozen 2h | 17.196856 | 38.411709 | 15.901212 |
| Previous-day reference | 16.725901 | 36.812500 | 1.330000 |

## Held-out 96-row development validation

| Model | MAE £/MWh | P95 abs error £/MWh | Signed bias £/MWh |
|---|---:|---:|---:|
| EWMA_24h_SHRINK_1 | 19.440194 | 52.717243 | -10.496837 |
| Frozen 2h | 18.188225 | 47.738227 | -2.371513 |
| Previous-day reference | 29.820625 | 116.960000 | -28.300208 |

Validation gates:

- MAE better than frozen: **False**;
- MAE better than previous-day reference: **True**;
- P95 non-worse than frozen: **False**;
- absolute signed bias non-worse than frozen: **False**;
- all guards passed: **False**.

Because the selected EWMA rule failed the frozen-model MAE, tail and bias safeguards, **no v0.26 forward test is launched**. Changing the candidate family after opening this validation block requires a new version and a new future boundary; these 96 rows cannot be reused as independent validation.

## Locked source

- workflow run: `32603302586`;
- development artifact ID: `9483484608`;
- development artifact SHA-256: `b4d5b9e3f72da959d1a7f2a3786c5e87951e285efb8506d534f4c5305643af1d`;
- source v0.25 artifact SHA-256: `eb2585458aaddb15a2485b4f5c349e8f90917cfc97bbdbe179cf95009e90ab95`;
- latest input target: `2026-08-22T20:00:00+00:00`;
- development end exclusive: `2026-08-22T20:30:00+00:00`;
- originally proposed forward start (not activated): `2026-08-23T02:00:00+00:00`.

This is development/model-governance evidence, not an accuracy claim and not trading P&L.
