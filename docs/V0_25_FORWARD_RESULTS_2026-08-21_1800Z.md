# v0.25 2h forward snapshot — 21 August 2026 18:00 UTC

This is the third append-only snapshot for the unchanged `2H_FROZEN_PLUS_CAUSAL_48H_RESIDUAL_MEAN` candidate. It extends the prior 9-row ledger without changing the frozen ridge model, NESO feature family, 48-hour residual-mean correction, minimum-history rule or forward start.

## Run identity

- GitHub Actions run: `32518932578`
- artifact ID: `9459873801`
- artifact SHA-256: `351fe39863798a5a711489c157b8429a015c0b020115ed898aad701bbdc1e6d2`
- forward window: `2026-08-21T11:30Z` to `2026-08-21T18:00Z` (end exclusive)
- rows: **13**
- maturity: `EARLY_ONLY`
- promotion: `NOT_ELIGIBLE_INSUFFICIENT_ROWS` (323 rows still needed before the 336-row review gate)

## Cumulative 13-row monitoring

| Metric | Adaptive v0.25 | Frozen 2h | Previous-day reference |
|---|---:|---:|---:|
| MAE (£/MWh) | **6.828** | 10.832 | 9.621 |
| P95 abs error (£/MWh) | 19.035 | **15.949** | 16.780 |
| Signed bias (£/MWh) | 3.041 | -6.618 | 8.807 |

Adaptive cumulative MAE is **29.0% lower than the reference** and **37.0% lower than the frozen model**, but this is still only 13 half-hours and is not a headline claim.

## New increment since the 16:00 snapshot

The four new targets from 16:00 to 18:00 UTC show the trade-off more clearly:

- adaptive MAE: **10.137 £/MWh**;
- frozen MAE: **9.913 £/MWh**;
- previous-day reference MAE: **11.760 £/MWh**;
- adaptive is **13.8% better than the reference** but **2.3% worse than frozen**;
- adaptive P95 is **19.465 £/MWh**, worse than frozen (11.685) and reference (16.671).

This is consistent with correction lag: the causal correction remained around +9.46 £/MWh while the frozen model's signed bias over these four rows was only 0.69 £/MWh. The rule is **not changed** in response.

## Append-only integrity

The original six-row genesis chain and all nine rows from the previous snapshot were reproduced exactly before four new rows were appended.

- previous 9-row chain tip: `f857a1f7f069961624cc3cb5d1f4e544e942d06658882ed56f519b09429257c6`
- current 13-row chain tip: `5852d70b1a18acc0ff9ae46de71c372fc9d8878e8e2ecab8d2b2427dae997745`

The runner has also been upgraded so future runs automatically verify the **latest ledger in the snapshot registry**, while retaining the original six-row ledger as a permanent genesis anchor.

These are public-data forecasting diagnostics, not realised trading P&L.
