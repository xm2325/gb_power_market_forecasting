# v0.19 real-market protocol

**Target:** volume-weighted APX/N2EX Market Index Price, £/MWh.

**Exogenous information:** latest and previous NESO embedded wind/solar forecast vintages satisfying `publish_time <= decision_time`.

**Market stress variable:** `|single-cash-out system price - volume-weighted MID|`, used only for conditioned diagnostics. Stress thresholds are fitted on the calibration window, never on final outcomes.

**Seasonal reference:** previous GB settlement date, same Settlement Period. This is intentionally distinct from 24h-UTC lagging around DST.

**Selection boundary:** family, ridge alpha, revision-complexity margin, large-move guard and deployment/fallback decision are fixed before the final window.

**Uncertainty boundary:** split-conformal absolute residual quantile is fitted on the calibration window after the point decision is frozen.

**Final window:** 1,623 half-hours from target-start 2026-07-12 12:00 UTC (inclusive) to 2026-08-15 07:30 UTC (exclusive).

**Claims:** numerical price results require `PASS_REAL`. Forecast metrics are not trading P&L.
