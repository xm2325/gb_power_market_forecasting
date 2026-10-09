from __future__ import annotations

import numpy as np
import pandas as pd


def select_latest_and_previous_asof_revision(
    revisions: pd.DataFrame,
    targets: pd.DataFrame,
    *,
    forecast_col: str,
    target_col: str = "target_start_utc",
    publish_col: str = "publish_time_utc",
    decision_col: str = "decision_time_utc",
) -> pd.DataFrame:
    """Return the last two forecast vintages known at each decision time.

    This supports a real-time revision feature without reading any publication
    after the simulated decision time.
    """
    r = revisions.copy()
    t = targets.copy()
    for frame, col in [(r, target_col), (r, publish_col), (t, target_col), (t, decision_col)]:
        frame[col] = pd.to_datetime(frame[col], utc=True, errors="raise")
    if r.duplicated([target_col, publish_col]).any():
        raise ValueError("duplicate target/publish forecast revisions")
    if forecast_col not in r.columns:
        raise ValueError(f"missing forecast column: {forecast_col}")

    joined = t[[target_col, decision_col]].merge(
        r[[target_col, publish_col, forecast_col]], on=target_col, how="left"
    )
    eligible = joined[
        joined[publish_col].notna() & (joined[publish_col] <= joined[decision_col])
    ].copy()
    rows = []
    for (target, decision), g in eligible.groupby([target_col, decision_col], sort=True):
        g = g.sort_values(publish_col)
        latest = g.iloc[-1]
        previous = g.iloc[-2] if len(g) >= 2 else None
        latest_value = float(latest[forecast_col])
        prev_value = float(previous[forecast_col]) if previous is not None else np.nan
        latest_publish = latest[publish_col]
        prev_publish = previous[publish_col] if previous is not None else pd.NaT
        rows.append({
            target_col: target,
            decision_col: decision,
            "latest_publish_time_utc": latest_publish,
            "previous_publish_time_utc": prev_publish,
            "latest_forecast_mw": latest_value,
            "previous_forecast_mw": prev_value,
            "revision_delta_mw": latest_value - prev_value if previous is not None else np.nan,
            "abs_revision_delta_mw": abs(latest_value - prev_value) if previous is not None else np.nan,
            "forecast_age_minutes": (decision - latest_publish).total_seconds() / 60.0,
            "minutes_between_revisions": (
                (latest_publish - prev_publish).total_seconds() / 60.0 if previous is not None else np.nan
            ),
        })
    out = pd.DataFrame(rows)
    if out.empty:
        return pd.DataFrame(columns=[
            target_col, decision_col, "latest_publish_time_utc", "previous_publish_time_utc",
            "latest_forecast_mw", "previous_forecast_mw", "revision_delta_mw",
            "abs_revision_delta_mw", "forecast_age_minutes", "minutes_between_revisions",
        ])
    if (out["latest_publish_time_utc"] > out[decision_col]).any():
        raise AssertionError("future revision selected")
    return out.sort_values([target_col, decision_col]).reset_index(drop=True)


def fit_large_revision_threshold(
    calibration_features: pd.DataFrame,
    *,
    abs_revision_col: str = "abs_revision_delta_mw",
    quantile: float = 0.90,
) -> dict:
    if not 0 < quantile < 1:
        raise ValueError("quantile must be in (0, 1)")
    x = pd.to_numeric(calibration_features[abs_revision_col], errors="coerce").dropna()
    if x.empty:
        raise ValueError("no revision deltas in calibration population")
    return {
        "abs_revision_col": abs_revision_col,
        "quantile": float(quantile),
        "large_revision_threshold_mw": float(x.quantile(quantile)),
        "n_calibration_rows": int(len(x)),
        "fit_population": "pre-final calibration only",
    }


def label_revision_regime(
    frame: pd.DataFrame,
    threshold: dict,
    *,
    delta_col: str = "revision_delta_mw",
    out_col: str = "revision_regime",
) -> pd.DataFrame:
    df = frame.copy()
    delta = pd.to_numeric(df[delta_col], errors="coerce")
    tau = float(threshold["large_revision_threshold_mw"])
    label = np.select(
        [delta <= -tau, delta >= tau, delta.notna()],
        ["large_downward", "large_upward", "other"],
        default="missing",
    )
    df[out_col] = pd.Categorical(
        label,
        categories=["other", "large_downward", "large_upward", "missing"],
    )
    return df


def revision_market_diagnostics(
    frame: pd.DataFrame,
    *,
    spread_col: str = "absolute_spread_gbp_mwh",
    regime_col: str = "revision_regime",
    stress_threshold_gbp_mwh: float | None = None,
) -> dict:
    """Descriptive association between forecast revisions and later price stress.

    This is explicitly not a causal estimate and should not be presented as a
    trading rule without a pre-final selection and independent replay.
    """
    df = frame[[spread_col, regime_col]].dropna().copy()
    if df.empty:
        raise ValueError("no complete revision/market rows")
    out = {}
    for label in ["other", "large_downward", "large_upward"]:
        g = df[df[regime_col].astype(str) == label]
        if g.empty:
            continue
        row = {
            "n_rows": int(len(g)),
            "mean_abs_spread_gbp_mwh": float(g[spread_col].mean()),
            "median_abs_spread_gbp_mwh": float(g[spread_col].median()),
        }
        if stress_threshold_gbp_mwh is not None:
            row["share_above_pre_final_stress_threshold"] = float(
                (g[spread_col] >= stress_threshold_gbp_mwh).mean()
            )
        out[label] = row
    return {
        "analysis_type": "descriptive association; not causal and not a validated trading rule",
        "by_revision_regime": out,
    }
