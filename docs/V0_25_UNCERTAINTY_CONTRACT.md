# v0.25 adaptive uncertainty contract

v0.25 changes the 2h **level** forecast but does not perform a second conformal calibration on forward labels.

Let the frozen v0.20 point forecast be `p_t`, its frozen conformal interval be `[l_t, u_t]`, and the v0.25 causal residual correction be `c_t`. The adaptive outputs are defined mechanically as:

```text
adaptive point = p_t + c_t
adaptive lower = l_t + c_t
adaptive upper = u_t + c_t
```

Therefore:

```text
adaptive interval width = u_t - l_t
```

The frozen calibration residual quantile, interval width and calibration data remain unchanged.

## Information boundary

For a 2h target starting at `t`, the decision is made at `t - 120 minutes`. A residual from historical target `s` may enter `c_t` only if its realised outcome is available by that decision time, conservatively represented as:

```text
s + 30 minutes <= decision_time(t)
```

Consequently the target being forecast and the most recent 150 minutes of target labels cannot affect either its adaptive point forecast or its adaptive interval endpoints.

The test suite explicitly changes current/future realised prices and verifies that the corresponding already-decided adaptive point and interval endpoints do not move.

## Monitoring

When frozen interval fields are present, every v0.25 monitor run reports adaptive interval coverage and mean width in the same cumulative and rolling windows as the point-forecast metrics. Frozen interval coverage is retained as a comparator.

Coverage is diagnostic at this stage. The repository does not claim that the translated interval has been independently recalibrated for the adaptive model, and it does not tune a new coverage threshold after observing the v0.25 forward segment.

If a later version recalibrates interval width or quantiles using additional data, that change must receive a new versioned uncertainty contract and an appropriate data boundary.

These are forecasting uncertainty diagnostics on public market data, not realised trading P&L or risk limits for live trading.
