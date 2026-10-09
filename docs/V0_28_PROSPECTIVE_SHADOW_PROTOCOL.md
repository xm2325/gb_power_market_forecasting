# v0.28: prospective shadow forecasting and delayed scoring

## Scope and limits

This is a **new price-history-only shadow experiment**, not a retest of the
byte-locked v0.20-v0.27 NESO/ridge algorithms. The older files, metrics, and
candidate locks must not be altered. A new-source snapshot is collected before
creating each prediction; a later run separately scores the target.

The purpose is to test three **method structures** using the same
live source snapshot and target:

1. **previous_day:** yesterday's GB settlement date at the same SP;
2. **consensus:** previous_day plus the smaller same-sign mean of 6h/48h
   previously observed residual windows; otherwise zero correction;
3. **direction_veto:** consensus correction only if its sign also matches
   the change in previous_day price relative to the latest eligible
   historical residual anchor.

The old v0.26/v0.27 code was built on a different frozen ridge base and
a different assumed release delay. These v0.28 comparator results must
**not** be reported as v0.26/v0.27 forward results.

## Data and timing contract

- Target: volume-weighted APX/N2EX Market Index Data, GBP/MWh,
  from the actual Elexon API snapshot obtained in this workflow.
- Settlement key: GB local settlement date and period, never 48-row
  shifting for a previous-settlement-day reference.
- The input query ends at an end-exclusive settlement-period start,
  limited to price periods whose **end is at least 90 minutes before
  source-query preparation**. This is an explicitly conservative
  delay assumption, not proof of historical publication timestamps.
- The new forecast is created after the API download. The target is
  the first 30-minute GB grid point at least 120 minutes after the
  actual model decision timestamp. The realised lead is saved
  individually and may exceed 120 minutes because workflow starts
  are not exact.
- Historical residuals are used only if their period end plus
  90 minutes is no later than the current decision.
- Missing or incomplete source history, a DST missing previous-day SP,
  or missing previous-day target price **blocks the prediction**.
  There is no interpolation or replacement with invented data.
- The prediction JSON contains no target label or error.
- The workflow checks the target is still in the future before Git
  commit and push; scoring only accepts a prediction whose Git
  commit time is earlier than target start. Commit time is an audit
  control; a later release should also verify GitHub first-push times.
- A separate run, at least 90 minutes after the target period ends,
  obtains the realised outcome. It does not recompute the prediction.

Elexon specification:
https://bscdocs.elexon.co.uk/bsc-module/user-requirements-specifications/balancing-mechanism-reporting-agent
The published service timing is a service rule, **not** row-level
historical first-observation timestamps.

## Evaluation and evidence

Machine-readable outputs:

- reports/forward/v28/predictions/YYYYMMDDTHHMMZ.json
- reports/forward/v28/scores/YYYYMMDDTHHMMZ.json
- reports/forward/v28/runs/YYYYMMDDTHHMMSSffffffZ.json
- reports/forward/v28/latest.json (derived, replaceable summary)

Every original prediction and score has a unique target filename and is
created once. Scores contain a SHA-256 of the stored prediction and
the actual-source manifest hash. Run records include failed, pending,
and blocked outcomes rather than hiding unsuccessful executions.

Compare MAE and paired absolute-error gains against previous_day
on exactly the same scored targets. Produce rolling 48-row alerts for
challengers that trail previous_day. The first review can happen only
after 336 scored half-hours (7 days at full coverage). This is a
**review threshold**, not a significance claim, and never
an automatic promotion. Review also missing schedule runs, forecast
lead-time distribution, P95 error, bias, and paired block uncertainty.

A missed schedule is a missing forecast, not a retrospectively rebuilt
forecast. GitHub cron can be late or omitted; gaps must be reported.
These are forecasting metrics, not realised electricity-trading P&L.

## Activation

The scheduler is **not active on a feature branch**. GitHub Actions
scheduled workflows only run from the repository default branch.
To enable continuous runs, first merge the existing real-data PR and
then merge this v0.28 change into main. The job is scheduled at
11 and 41 minutes of every UTC hour and can run manually.

Before promotion or public performance claims, implement server-side
push-time checks and an independent data revision audit. No old
v0.20-v0.27 headline is revised by v0.28.
