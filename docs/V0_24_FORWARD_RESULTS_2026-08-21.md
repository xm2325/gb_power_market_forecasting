# v0.24 continuous forward results — 21 August 2026

This report replays the **unchanged frozen v0.20 models** continuously from the locked historical final period into later market observations. It is an operational/diagnostic monitoring view, not a replacement for the immutable v0.20 benchmark and not realised trading P&L.

## Run identity

- GitHub Actions run: `32485905691`
- artifact: `v24-continuous-forward-32485905691`
- artifact ID: `9447877873`
- artifact SHA-256: `b79f86af22ea62a7c7e3fcccc3f0403353d0350f523ac432ed60d959e9abe6eb`
- frozen model-state SHA-256: `e9952aa88ca56b85f4d595bfe918cdc589ac0048d717d3fb3d9210361eb18918`

The monitoring window is `2026-07-12T12:00Z` to `2026-08-21T11:30Z` (end exclusive), exactly **1,919 half-hours** at every horizon. Coverage is 100%, duplicate/off-grid rows are zero and future NESO publications are zero.

The run downloaded **612,906** bounded current-regime NESO forecast-vintage rows. Elexon MID was downloaded from 1 July to provide the warm-up required by `price_lag_7d_same_target`; the scoring window itself still starts on 12 July.

## Frozen-model performance by monitoring view

### 30 minutes

| View | Rows | Frozen MAE | Previous-day MAE | Relative result | Interval coverage | Model win rate |
|---|---:|---:|---:|---:|---:|---:|
| Locked v0.20 final | 1,623 | 8.939 | 24.048 | **62.8% better** | 89.5% | 69.7% |
| 1 Aug → latest | 983 | 8.831 | 19.300 | **54.2% better** | 89.7% | 69.9% |
| Post-lock → latest | 296 | 7.587 | 15.885 | **52.2% better** | 93.6% | 76.0% |
| Latest 7d | 336 | 7.757 | 15.443 | **49.8% better** | 92.9% | 73.5% |
| Latest 3d | 144 | 7.402 | 14.265 | **48.1% better** | 93.8% | 72.9% |
| Latest 24h | 48 | 7.003 | 10.789 | **35.1% better** | 95.8% | 64.6% |

The 30-minute model is the clearest stability result. It used price history only in v0.20 and remains materially better than the previous-settlement-day reference in every recent aggregate view. Individual days can still be worse; for example 4 August was negative, but the 7-day rolling advantage remained positive.

### 2 hours

| View | Rows | Frozen MAE | Previous-day MAE | Relative result | Interval coverage | Model win rate |
|---|---:|---:|---:|---:|---:|---:|
| Locked v0.20 final | 1,623 | 17.087 | 24.048 | **28.9% better** | 89.5% | 53.7% |
| 1 Aug → latest | 983 | 17.512 | 19.300 | **9.3% better** | 89.3% | 47.2% |
| Post-lock → latest | 296 | 16.875 | 15.885 | **6.2% worse** | 90.9% | 45.6% |
| Latest 7d | 336 | 17.176 | 15.443 | **11.2% worse** | 90.5% | 43.8% |
| Latest 3d | 144 | 15.679 | 14.265 | **9.9% worse** | 94.4% | 45.8% |
| Latest 24h | 48 | 12.639 | 10.789 | **17.1% worse** | 97.9% | 43.8% |

This is the most useful degradation story. The 2-hour model still looks positive when 1 August onward is pooled, but the genuine post-lock segment is already slightly worse than the reference. The rolling 7-day improvement crossed from positive to negative around 15 August and remained negative at the latest checkpoint despite a few individually positive days.

The behaviour is not simply an uncertainty-calibration collapse: post-lock interval coverage is still about 90.9%. The more direct issue is that the point forecast has stopped beating the simple previous-settlement-day reference often enough.

### 6 hours

| View | Rows | Frozen MAE | Previous-day MAE | Relative result | Interval coverage | Model win rate |
|---|---:|---:|---:|---:|---:|---:|
| Locked v0.20 final | 1,623 | 34.437 | 24.048 | **43.2% worse** | 85.9% | 27.4% |
| 1 Aug → latest | 983 | 38.303 | 19.300 | **98.5% worse** | 83.8% | 17.9% |
| Post-lock → latest | 296 | 43.924 | 15.885 | **176.5% worse** | 78.7% | 6.4% |
| Latest 7d | 336 | 43.892 | 15.443 | **184.2% worse** | 78.9% | 6.3% |

The long-horizon failure is persistent rather than confined to the original v0.20 final split. Recent monitoring makes it worse.

### 12 hours

| View | Rows | Frozen MAE | Previous-day MAE | Relative result | Interval coverage | Model win rate |
|---|---:|---:|---:|---:|---:|---:|
| Locked v0.20 final | 1,623 | 50.974 | 24.048 | **112.0% worse** | 83.1% | 17.7% |
| 1 Aug → latest | 983 | 56.670 | 19.300 | **193.6% worse** | 73.8% | 10.1% |
| Post-lock → latest | 296 | 65.906 | 15.885 | **314.9% worse** | 56.4% | 0.3% |
| Latest 7d | 336 | 65.687 | 15.443 | **325.3% worse** | 57.7% | 0.3% |

The 12-hour model is clearly unsuitable in the current form. The issue is visible in both point accuracy and uncertainty coverage. In the post-lock segment it beats the reference in only about 0.3% of half-hours.

## What changed through August?

The continuous view makes the horizon split much clearer than one final MAE table.

- **30m:** stable. The 7-day rolling relative improvement remains strongly positive through the latest point.
- **2h:** unstable. It was positive on 1–2 August, negative on 3–4 August, recovered on several later days, then the 7-day rolling improvement fell below zero around 15 August. It remained negative at the latest checkpoint.
- **6h/12h:** persistent failure. A few isolated days can look better, but the rolling and cumulative picture remains decisively worse than the reference.

This means the next model-development work should not treat all horizons as one problem. The evidence supports keeping the 30-minute model as the stable benchmark, diagnosing the 2-hour regime sensitivity separately, and redesigning rather than lightly tuning the 6-hour/12-hour approach.

## Versioning rule

These monitoring outcomes are intentionally visible. If they are used to change a model, the revised model must receive a new version/segment and can only claim fresh forward evidence after that change is frozen. The old v0.20/v0.24 monitoring series remains unchanged.

Machine-readable snapshot: [`reports/monitoring/V0_24_CONTINUOUS_FORWARD_2026-08-21.json`](../reports/monitoring/V0_24_CONTINUOUS_FORWARD_2026-08-21.json).
