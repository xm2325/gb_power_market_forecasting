import pandas as pd

from gb_power_market.revision_signal import (
    fit_large_revision_threshold,
    label_revision_regime,
    revision_market_diagnostics,
    select_latest_and_previous_asof_revision,
)


def _revisions():
    return pd.DataFrame({
        "target_start_utc": ["2026-08-01T12:00:00Z"] * 4,
        "publish_time_utc": [
            "2026-08-01T08:00:00Z", "2026-08-01T09:00:00Z",
            "2026-08-01T10:00:00Z", "2026-08-01T11:30:00Z",
        ],
        "forecast_mw": [7000.0, 6800.0, 6200.0, 6100.0],
    })


def test_last_two_revisions_are_strictly_asof():
    targets = pd.DataFrame({
        "target_start_utc": ["2026-08-01T12:00:00Z"],
        "decision_time_utc": ["2026-08-01T10:30:00Z"],
    })
    out = select_latest_and_previous_asof_revision(
        _revisions(), targets, forecast_col="forecast_mw"
    )
    assert out.loc[0, "latest_forecast_mw"] == 6200.0
    assert out.loc[0, "previous_forecast_mw"] == 6800.0
    assert out.loc[0, "revision_delta_mw"] == -600.0
    assert out.loc[0, "latest_publish_time_utc"] <= out.loc[0, "decision_time_utc"]


def test_future_revision_is_never_selected():
    targets = pd.DataFrame({
        "target_start_utc": ["2026-08-01T12:00:00Z"],
        "decision_time_utc": ["2026-08-01T09:30:00Z"],
    })
    out = select_latest_and_previous_asof_revision(
        _revisions(), targets, forecast_col="forecast_mw"
    )
    assert out.loc[0, "latest_forecast_mw"] == 6800.0
    assert out.loc[0, "previous_forecast_mw"] == 7000.0


def test_revision_threshold_and_labels_are_pre_final():
    cal = pd.DataFrame({"abs_revision_delta_mw": [10, 20, 30, 100]})
    tau = fit_large_revision_threshold(cal, quantile=0.75)
    final = pd.DataFrame({"revision_delta_mw": [-200.0, 0.0, 200.0]})
    got = label_revision_regime(final, tau)
    assert list(got["revision_regime"].astype(str)) == ["large_downward", "other", "large_upward"]


def test_revision_market_output_says_descriptive_not_causal():
    df = pd.DataFrame({
        "revision_regime": ["other", "large_downward", "large_upward"],
        "absolute_spread_gbp_mwh": [10.0, 100.0, 50.0],
    })
    out = revision_market_diagnostics(df, stress_threshold_gbp_mwh=40.0)
    assert "not causal" in out["analysis_type"]
    assert out["by_revision_regime"]["large_downward"]["share_above_pre_final_stress_threshold"] == 1.0
