# Prospective holdout policy

The v0.20 real benchmark is now frozen.

## Locked benchmark

- Final price target-start window: `2026-07-12T12:00:00Z` to `2026-08-15T07:30:00Z` exclusive.
- Number of final targets: 1,623.
- Evidence run: `32469293682`.
- Evidence fingerprint: `7c5f78b98c8ed877ab4c5cefa8a40b3068abb74cb2062ecf677f319d74a14661`.

## What is allowed

The locked final labels may be used for:

- error analysis and root-cause diagnosis;
- plots and post-hoc descriptive analysis clearly labelled as diagnostic;
- later model training **only after** a new, later holdout has been reserved.

## What is not allowed

Do not:

1. inspect the locked 1,623 final labels;
2. change features, model family, hyperparameters, promotion thresholds or calibration rules because of those labels;
3. evaluate the changed model on the same 1,623 labels; and
4. describe that result as independent held-out evidence.

Once final labels influence model selection, that window is no longer an unbiased test for the changed model.

## Next numerical claim

Any post-v0.20 model improvement requires a later prospective holdout with target starts no earlier than `2026-08-15T07:30:00Z`.

The exact next development/calibration/test boundaries should be fixed **before** reading the corresponding test labels. The new window should also retain the same publication-time and label-availability rules used in v0.20.

## Negative results remain locked

The 6h and 12h failures are part of the benchmark record. Future work may explain or improve them, but the v0.20 result must remain visible:

- 6h: 34.437 vs 24.048 £/MWh reference MAE, 43.2% worse;
- 12h: 50.974 vs 24.048 £/MWh reference MAE, 112.0% worse.

This prevents later development from silently rewriting the project history.
