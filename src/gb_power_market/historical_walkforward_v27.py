from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

import numpy as np
import pandas as pd

from gb_power_market.adaptive_bias_v25 import apply_causal_bias_correction
from gb_power_market.adaptive_consensus_v26 import apply_causal_consensus_correction
from gb_power_market.adaptive_direction_v27_candidate import apply_causal_direction_veto_candidate
from gb_power_market.fixed_market_experiment import FAMILIES
from gb_power_market.price_forecasting import NumpyRidge


EVIDENCE_CLASS = "HISTORICAL_ASOF_ROLLING_ORIGIN_NOT_LIVE_FORWARD"


@dataclass(frozen=True)
class WalkForwardConfig:
    train_start_utc: str = "2026-01-08T00:00:00Z"
    score_start_utc: str = "2026-05-01T00:00:00Z"
    score_end_exclusive_utc: str = "2026-08-23T22:00:00Z"
    fold_days: int = 7
    selection_days: int = 14
    calibration_days: int = 14
    adaptation_warmup_hours: int = 72
    horizon_minutes: int = 120


def _utc(value: str | pd.Timestamp) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    if ts.tzinfo is None:
        raise ValueError("walk-forward timestamps must be timezone-aware")
    return ts.tz_convert("UTC")


def build_fold_schedule(config: WalkForwardConfig = WalkForwardConfig()) -> list[dict[str, Any]]:
    if config.fold_days <= 0 or config.selection_days <= 0 or config.calibration_days <= 0:
        raise ValueError("fold/selection/calibration durations must be positive")
    if config.adaptation_warmup_hours < 51:
        raise ValueError("adaptation warm-up must cover the full 48h residual window plus horizon/delay")

    train_start = _utc(config.train_start_utc)
    score_start = _utc(config.score_start_utc)
    score_end = _utc(config.score_end_exclusive_utc)
    if score_end <= score_start:
        raise ValueError("score end must be after score start")

    folds: list[dict[str, Any]] = []
    cursor = score_start
    i = 1
    while cursor < score_end:
        fold_score_end = min(cursor + pd.Timedelta(days=config.fold_days), score_end)
        final_start = cursor - pd.Timedelta(hours=config.adaptation_warmup_hours)
        calibration_start = final_start - pd.Timedelta(days=config.calibration_days)
        selection_start = calibration_start - pd.Timedelta(days=config.selection_days)
        if selection_start <= train_start:
            raise ValueError("first rolling fold leaves no training interval before selection")
        folds.append(
            {
                "fold": i,
                "train_start_utc": train_start.isoformat(),
                "selection_start_utc": selection_start.isoformat(),
                "calibration_start_utc": calibration_start.isoformat(),
                "adaptation_warmup_start_utc": final_start.isoformat(),
                "score_start_utc": cursor.isoformat(),
                "score_end_exclusive_utc": fold_score_end.isoformat(),
                "evidence_class": EVIDENCE_CLASS,
            }
        )
        cursor = fold_score_end
        i += 1
    return folds


def _purge_for_next(block: pd.DataFrame, next_block: pd.DataFrame) -> pd.DataFrame:
    if block.empty or next_block.empty:
        raise ValueError("rolling-origin development block is empty")
    first_next_decision = pd.to_datetime(next_block["decision_time_utc"], utc=True).min()
    available = pd.to_datetime(block["target_start_utc"], utc=True) + pd.Timedelta(minutes=30)
    return block.loc[available <= first_next_decision].copy()


def build_deployed_base_rows(
    frame: pd.DataFrame,
    *,
    fold: dict[str, Any],
    selection: dict[str, Any],
    horizon_minutes: int = 120,
    target_col: str = "reference_market_price_gbp_mwh",
) -> pd.DataFrame:
    """Reconstruct the selected base on all rows supported by the deployed family.

    Family/alpha selection remains on the original all-family common support. After
    deployment is fixed, a row is not discarded merely because an *unused* revision
    feature is absent (notably at the legacy/current NESO transition).
    """
    df = frame.copy()
    df["target_start_utc"] = pd.to_datetime(df["target_start_utc"], utc=True, errors="raise")
    df["decision_time_utc"] = pd.to_datetime(df["decision_time_utc"], utc=True, errors="raise")
    df = df.sort_values("target_start_utc").reset_index(drop=True)

    final_start = _utc(fold["adaptation_warmup_start_utc"])
    final_end = _utc(fold["score_end_exclusive_utc"])
    final = df[(df["target_start_utc"] >= final_start) & (df["target_start_utc"] < final_end)].copy()
    core = [target_col, "target_start_utc", "decision_time_utc", "price_lag_1d_same_target", "price_lag_last_completed"]

    deployed = selection["deployed_source"]
    if deployed == "PREVIOUS_SETTLEMENT_DAY_FALLBACK":
        final = final.dropna(subset=core).copy()
        prediction = final["price_lag_1d_same_target"].to_numpy(float)
    else:
        family = selection["selected_family"]
        if deployed != family:
            raise ValueError("historical deployed source disagrees with selected family")
        features = FAMILIES[family]
        final_required = list(dict.fromkeys([*core, *features]))
        if family != "PRICE_HISTORY_ONLY":
            final_required.append("neso_publish_time_utc")
        final = final.dropna(subset=final_required).copy()
        if family != "PRICE_HISTORY_ONLY":
            pub = pd.to_datetime(final["neso_publish_time_utc"], utc=True, errors="raise")
            if (pub > final["decision_time_utc"]).any():
                raise ValueError("post-decision NESO vintage entered deployed-family scoring")

        common_required = list(dict.fromkeys([
            target_col,
            "target_start_utc",
            "decision_time_utc",
            "neso_publish_time_utc",
            "price_lag_1d_same_target",
            "price_lag_last_completed",
            *FAMILIES["PRICE_PLUS_NESO_LEVELS_AND_REVISIONS"],
        ]))
        common = df.dropna(subset=common_required).copy()
        train_start = _utc(fold["train_start_utc"])
        selection_start = _utc(fold["selection_start_utc"])
        calibration_start = _utc(fold["calibration_start_utc"])
        raw_train = common[(common["target_start_utc"] >= train_start) & (common["target_start_utc"] < selection_start)]
        raw_selection = common[(common["target_start_utc"] >= selection_start) & (common["target_start_utc"] < calibration_start)]
        raw_calibration = common[(common["target_start_utc"] >= calibration_start) & (common["target_start_utc"] < final_start)]
        train = _purge_for_next(raw_train, raw_selection)
        selected_rows = _purge_for_next(raw_selection, raw_calibration)
        point_fit = pd.concat([train, selected_rows], ignore_index=True)
        alpha = float(selection["by_family"][family]["selected_alpha"])
        point = NumpyRidge(alpha).fit(point_fit[features].to_numpy(float), point_fit[target_col].to_numpy(float))
        prediction = point.predict(final[features].to_numpy(float))

    return pd.DataFrame(
        {
            "target_start_utc": final["target_start_utc"].to_numpy(),
            "decision_time_utc": final["decision_time_utc"].to_numpy(),
            "realised_price_gbp_mwh": final[target_col].to_numpy(float),
            "frozen_prediction_gbp_mwh": prediction,
            "previous_settlement_day_reference_gbp_mwh": final["price_lag_1d_same_target"].to_numpy(float),
        }
    )


def apply_candidate_suite(base_rows: pd.DataFrame) -> pd.DataFrame:
    """Apply v0.25, v0.26 and v0.27 independently to one causal base sequence."""
    required = {
        "target_start_utc",
        "decision_time_utc",
        "realised_price_gbp_mwh",
        "frozen_prediction_gbp_mwh",
        "previous_settlement_day_reference_gbp_mwh",
    }
    missing = sorted(required - set(base_rows.columns))
    if missing:
        raise ValueError(f"historical base rows missing columns: {missing}")

    base = base_rows.copy()
    base["target_start_utc"] = pd.to_datetime(base["target_start_utc"], utc=True, errors="raise")
    base["decision_time_utc"] = pd.to_datetime(base["decision_time_utc"], utc=True, errors="raise")
    base = base.sort_values("target_start_utc").reset_index(drop=True)

    v25 = apply_causal_bias_correction(base)
    v26 = apply_causal_consensus_correction(base)
    v27 = apply_causal_direction_veto_candidate(base)

    out = base.copy()
    for col in ["bias_correction_gbp_mwh", "bias_history_rows", "bias_history_latest_target_utc", "adaptive_prediction_gbp_mwh", "adaptive_abs_error_gbp_mwh"]:
        out[col] = v25[col].to_numpy()
    for col in ["v26_short_residual_mean_gbp_mwh", "v26_long_residual_mean_gbp_mwh", "v26_short_history_rows", "v26_long_history_rows", "v26_history_latest_target_utc", "v26_gate_reason", "v26_correction_gbp_mwh", "v26_prediction_gbp_mwh", "v26_abs_error_gbp_mwh"]:
        out[col] = v26[col].to_numpy()
    for col in ["v27_base_v26_correction_gbp_mwh", "v27_direction_anchor_frozen_prediction_gbp_mwh", "v27_frozen_direction_delta_gbp_mwh", "v27_gate_reason", "v27_correction_gbp_mwh", "v27_prediction_gbp_mwh", "v27_abs_error_gbp_mwh"]:
        out[col] = v27[col].to_numpy()
    return out


def _metrics(y: np.ndarray, p: np.ndarray) -> dict[str, float]:
    err = p - y
    ae = np.abs(err)
    return {"mae_gbp_mwh": float(ae.mean()), "p95_abs_error_gbp_mwh": float(np.quantile(ae, 0.95)), "signed_bias_gbp_mwh": float(err.mean())}


def summarise_score_rows(rows: pd.DataFrame) -> dict[str, Any]:
    if rows.empty:
        raise ValueError("cannot summarise empty historical score rows")
    y = rows["realised_price_gbp_mwh"].to_numpy(float)
    cols = {"causal_base": "frozen_prediction_gbp_mwh", "v0.25": "adaptive_prediction_gbp_mwh", "v0.26": "v26_prediction_gbp_mwh", "v0.27": "v27_prediction_gbp_mwh", "previous_day": "previous_settlement_day_reference_gbp_mwh"}
    models = {name: _metrics(y, rows[col].to_numpy(float)) for name, col in cols.items()}
    base_abs = np.abs(y - rows[cols["causal_base"]].to_numpy(float))
    ref_abs = np.abs(y - rows[cols["previous_day"]].to_numpy(float))
    v27_abs = np.abs(y - rows[cols["v0.27"]].to_numpy(float))
    models["v0.27"].update({
        "improvement_vs_causal_base_pct": float(100.0 * (models["causal_base"]["mae_gbp_mwh"] - models["v0.27"]["mae_gbp_mwh"]) / models["causal_base"]["mae_gbp_mwh"]),
        "improvement_vs_previous_day_pct": float(100.0 * (models["previous_day"]["mae_gbp_mwh"] - models["v0.27"]["mae_gbp_mwh"]) / models["previous_day"]["mae_gbp_mwh"]),
        "win_rate_vs_causal_base": float((v27_abs < base_abs).mean()),
        "win_rate_vs_previous_day": float((v27_abs < ref_abs).mean()),
    })
    return {
        "rows": int(len(rows)),
        "start_utc": pd.to_datetime(rows["target_start_utc"], utc=True).min().isoformat(),
        "end_exclusive_utc": (pd.to_datetime(rows["target_start_utc"], utc=True).max() + pd.Timedelta(minutes=30)).isoformat(),
        "models": models,
        "v27_correction_applied_rate": float((rows["v27_correction_gbp_mwh"].astype(float) != 0.0).mean()),
        "v27_direction_veto_rate": float(rows["v27_gate_reason"].eq("FROZEN_DIRECTION_VETO_FALLBACK_FROZEN").mean()),
        "evidence_class": EVIDENCE_CLASS,
    }


def config_payload(config: WalkForwardConfig = WalkForwardConfig()) -> dict[str, Any]:
    return {
        **asdict(config),
        "evidence_class": EVIDENCE_CLASS,
        "claim_boundary": (
            "This is retrospective historical as-of rolling-origin evidence. Every fold refits/selects its causal "
            "base using only data available before that fold, then uses a pre-score adaptation warm-up. The v0.27 "
            "structure itself was designed later, so these rows are robustness/backtest evidence, not live forward "
            "evidence and not an untouched confirmatory validation set."
        ),
    }
