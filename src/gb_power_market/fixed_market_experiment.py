from __future__ import annotations

from dataclasses import dataclass, asdict

import numpy as np
import pandas as pd

from .price_feature_families import (
    FeatureFamilyRule,
    HISTORY_FEATURES,
    LEVEL_FEATURES,
    REVISION_FEATURES,
)
from .price_forecasting import NumpyRidge, price_metrics
from .price_tail import TailGuardRule, evaluate_tail_guard, fit_large_move_threshold, tail_metrics
from .probabilistic_price import (
    ProbabilisticRule,
    abstention_metrics,
    finite_sample_conformal_quantile,
    interval_metrics,
)

FAMILIES = {
    "PRICE_HISTORY_ONLY": HISTORY_FEATURES,
    "PRICE_PLUS_NESO_LEVELS": HISTORY_FEATURES + LEVEL_FEATURES,
    "PRICE_PLUS_NESO_LEVELS_AND_REVISIONS": HISTORY_FEATURES + LEVEL_FEATURES + REVISION_FEATURES,
}


@dataclass(frozen=True)
class FixedMarketWindows:
    train_start_utc: str = "2026-01-08T00:00:00Z"
    selection_start_utc: str = "2026-05-15T00:00:00Z"
    calibration_start_utc: str = "2026-06-15T00:00:00Z"
    final_start_utc: str = "2026-07-12T12:00:00Z"
    final_end_exclusive_utc: str = "2026-08-15T07:30:00Z"

    def parsed(self) -> dict[str, pd.Timestamp]:
        x = {k: pd.Timestamp(v) for k, v in asdict(self).items()}
        vals = list(x.values())
        if not all(t.tzinfo is not None for t in vals):
            raise ValueError("all fixed windows must be timezone-aware")
        if not (vals[0] < vals[1] < vals[2] < vals[3] < vals[4]):
            raise ValueError("fixed market windows are not strictly increasing")
        return x


@dataclass(frozen=True)
class RealPriceClaimGate:
    minimum_final_target_coverage: float = 0.95
    future_publications_allowed: int = 0


def _best_ridge(train: pd.DataFrame, selection: pd.DataFrame, features: list[str], target_col: str, alpha_grid):
    rows = []
    for alpha in alpha_grid:
        m = NumpyRidge(alpha).fit(train[features].to_numpy(float), train[target_col].to_numpy(float))
        pred = m.predict(selection[features].to_numpy(float))
        rows.append({"alpha": float(alpha), "selection_mae_gbp_mwh": float(np.abs(selection[target_col].to_numpy(float) - pred).mean())})
    return min(rows, key=lambda r: (r["selection_mae_gbp_mwh"], r["alpha"])), rows


def _purge_for_next(block: pd.DataFrame, next_block: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    if block.empty or next_block.empty:
        raise ValueError("fixed window produced empty development block")
    first_next_decision = pd.to_datetime(next_block["decision_time_utc"], utc=True).min()
    available = pd.to_datetime(block["target_start_utc"], utc=True) + pd.Timedelta(minutes=30)
    keep = available <= first_next_decision
    cleaned = block.loc[keep].copy()
    return cleaned, {
        "raw_rows": int(len(block)),
        "kept_rows": int(keep.sum()),
        "purged_rows": int((~keep).sum()),
        "next_first_decision_time_utc": first_next_decision.isoformat(),
        "rule": "target label available at target_start+30m <= next block first decision time",
    }


def run_fixed_window_real_price_experiment(
    frame: pd.DataFrame,
    *,
    horizon_minutes: int,
    target_col: str = "reference_market_price_gbp_mwh",
    windows: FixedMarketWindows = FixedMarketWindows(),
    alpha_grid: tuple[float, ...] = (0.0, 1.0, 10.0, 100.0),
    family_rule: FeatureFamilyRule = FeatureFamilyRule(),
    tail_rule: TailGuardRule = TailGuardRule(),
    probabilistic_rule: ProbabilisticRule = ProbabilisticRule(),
    claim_gate: RealPriceClaimGate = RealPriceClaimGate(),
    return_row_level: bool = False,
) -> dict:
    if horizon_minutes <= 0 or horizon_minutes % 30:
        raise ValueError("horizon_minutes must be a positive multiple of 30")
    required = list(dict.fromkeys([
        target_col, "target_start_utc", "decision_time_utc", "neso_publish_time_utc",
        "price_lag_1d_same_target", "price_lag_last_completed",
        *FAMILIES["PRICE_PLUS_NESO_LEVELS_AND_REVISIONS"],
    ]))
    w = windows.parsed()
    df = frame.copy()
    df["target_start_utc"] = pd.to_datetime(df["target_start_utc"], utc=True, errors="raise")
    df["decision_time_utc"] = pd.to_datetime(df["decision_time_utc"], utc=True, errors="raise")
    pub = pd.to_datetime(df["neso_publish_time_utc"], utc=True, errors="coerce")
    future = int((pub.notna() & (pub > df["decision_time_utc"])).sum())
    df = df.dropna(subset=required).sort_values("target_start_utc").reset_index(drop=True)
    df = df[(df["target_start_utc"] >= w["train_start_utc"]) & (df["target_start_utc"] < w["final_end_exclusive_utc"])].copy()

    raw_train = df[(df["target_start_utc"] >= w["train_start_utc"]) & (df["target_start_utc"] < w["selection_start_utc"])].copy()
    raw_sel = df[(df["target_start_utc"] >= w["selection_start_utc"]) & (df["target_start_utc"] < w["calibration_start_utc"])].copy()
    raw_cal = df[(df["target_start_utc"] >= w["calibration_start_utc"]) & (df["target_start_utc"] < w["final_start_utc"])].copy()
    final = df[(df["target_start_utc"] >= w["final_start_utc"]) & (df["target_start_utc"] < w["final_end_exclusive_utc"])].copy()
    train, purge_train = _purge_for_next(raw_train, raw_sel)
    selection, purge_sel = _purge_for_next(raw_sel, raw_cal)
    calibration, purge_cal = _purge_for_next(raw_cal, final)

    y_sel = selection[target_col].to_numpy(float)
    baseline_sel = selection["price_lag_1d_same_target"].to_numpy(float)
    last_sel = selection["price_lag_last_completed"].to_numpy(float)
    ref_sel_mae = float(np.abs(y_sel - baseline_sel).mean())
    tail_threshold = fit_large_move_threshold(
        train[target_col].to_numpy(float), train["price_lag_last_completed"].to_numpy(float), tail_rule.large_move_quantile
    )

    by_family: dict[str, dict] = {}
    selection_predictions: dict[str, np.ndarray] = {}
    for name, features in FAMILIES.items():
        best, candidates = _best_ridge(train, selection, features, target_col, alpha_grid)
        m = NumpyRidge(best["alpha"]).fit(train[features].to_numpy(float), train[target_col].to_numpy(float))
        pred = m.predict(selection[features].to_numpy(float))
        selection_predictions[name] = pred
        improvement = 100.0 * (ref_sel_mae - best["selection_mae_gbp_mwh"]) / ref_sel_mae if ref_sel_mae else np.nan
        tg = evaluate_tail_guard(y_sel, pred, baseline_sel, last_sel, threshold_gbp_mwh=tail_threshold, rule=tail_rule)
        by_family[name] = {
            "features": features,
            "selected_alpha": best["alpha"],
            "selection_mae_gbp_mwh": best["selection_mae_gbp_mwh"],
            "improvement_vs_previous_settlement_day_pct": float(improvement),
            "tail_guard": tg,
            "alpha_candidates": candidates,
        }

    simple = ["PRICE_HISTORY_ONLY", "PRICE_PLUS_NESO_LEVELS"]
    simple_pass = [n for n in simple if by_family[n]["tail_guard"]["status"] == "PASS"]
    best_simple = min(simple_pass if simple_pass else simple, key=lambda n: by_family[n]["selection_mae_gbp_mwh"])
    rev = "PRICE_PLUS_NESO_LEVELS_AND_REVISIONS"
    simple_mae = by_family[best_simple]["selection_mae_gbp_mwh"]
    rev_mae = by_family[rev]["selection_mae_gbp_mwh"]
    rev_margin = 100.0 * (simple_mae - rev_mae) / simple_mae if simple_mae else np.nan
    rev_eligible = rev_margin >= family_rule.minimum_margin_to_add_revision_pct and by_family[rev]["tail_guard"]["status"] == "PASS"
    selected_family = rev if rev_eligible else best_simple
    selected = by_family[selected_family]
    promoted = (
        len(selection) >= family_rule.minimum_validation_rows
        and selected["improvement_vs_previous_settlement_day_pct"] >= family_rule.minimum_improvement_vs_previous_day_pct
        and selected["tail_guard"]["status"] == "PASS"
    )

    point_fit = pd.concat([train, selection], ignore_index=True)
    features = FAMILIES[selected_family]
    if promoted:
        point = NumpyRidge(selected["selected_alpha"]).fit(point_fit[features].to_numpy(float), point_fit[target_col].to_numpy(float))
        cal_pred = point.predict(calibration[features].to_numpy(float))
        final_pred = point.predict(final[features].to_numpy(float))
        deployed_source = selected_family
    else:
        cal_pred = calibration["price_lag_1d_same_target"].to_numpy(float)
        final_pred = final["price_lag_1d_same_target"].to_numpy(float)
        deployed_source = "PREVIOUS_SETTLEMENT_DAY_FALLBACK"

    y_cal = calibration[target_col].to_numpy(float)
    cal_scores = np.abs(y_cal - cal_pred)
    conformal_q = finite_sample_conformal_quantile(cal_scores, probabilistic_rule.nominal_coverage)
    final_lower = final_pred - conformal_q
    final_upper = final_pred + conformal_q
    y_final = final[target_col].to_numpy(float)
    last_final = final["price_lag_last_completed"].to_numpy(float)
    baseline_final = final["price_lag_1d_same_target"].to_numpy(float)
    pre_final = pd.concat([train, selection, calibration], ignore_index=True)
    final_tail_threshold = fit_large_move_threshold(
        pre_final[target_col].to_numpy(float), pre_final["price_lag_last_completed"].to_numpy(float), tail_rule.large_move_quantile
    )

    expected_final_rows = len(pd.date_range(w["final_start_utc"], w["final_end_exclusive_utc"], freq="30min", inclusive="left"))
    final_coverage = float(len(final) / expected_final_rows) if expected_final_rows else 0.0
    claim_status = "PASS_REAL" if (
        final_coverage >= claim_gate.minimum_final_target_coverage
        and future <= claim_gate.future_publications_allowed
        and len(final) > 0
    ) else "BLOCKED"

    result = {
        "version": "0.19.0",
        "data_status": "REAL_ELEXON_PLUS_REAL_NESO_REQUIRED",
        "horizon_minutes": int(horizon_minutes),
        "windows": {k: v.isoformat() for k, v in w.items()},
        "rows": {
            "common_complete": int(len(df)),
            "train": int(len(train)), "selection": int(len(selection)),
            "calibration": int(len(calibration)), "final": int(len(final)),
            "expected_final": int(expected_final_rows), "final_coverage": final_coverage,
        },
        "purge": {"train": purge_train, "selection": purge_sel, "calibration": purge_cal},
        "information_audit": {"future_neso_publications": future},
        "selection": {
            "reference_selection_mae_gbp_mwh": ref_sel_mae,
            "by_family": by_family,
            "best_simple_family": best_simple,
            "revision_margin_vs_best_simple_pct": float(rev_margin),
            "selected_family": selected_family,
            "promoted": bool(promoted),
            "deployed_source": deployed_source,
            "family_rule": asdict(family_rule),
            "tail_rule": asdict(tail_rule),
        },
        "calibration": {
            "method": "fixed-window split conformal absolute residual",
            "nominal_coverage": probabilistic_rule.nominal_coverage,
            "absolute_residual_quantile_gbp_mwh": float(conformal_q),
            "n_rows": int(len(calibration)),
        },
        "final_test": {
            "previous_settlement_day_reference": price_metrics(y_final, baseline_final, last_final),
            "deployed": price_metrics(y_final, final_pred, last_final),
            "deployed_tail": tail_metrics(y_final, final_pred, last_final, large_move_threshold_gbp_mwh=final_tail_threshold),
            "interval": interval_metrics(y_final, final_lower, final_upper, probabilistic_rule.nominal_coverage),
            "abstention": abstention_metrics(y_final, final_pred, final_lower, final_upper, last_final),
            "large_move_threshold_gbp_mwh": float(final_tail_threshold),
        },
        "claim_gate": {
            "status": claim_status,
            "rule": asdict(claim_gate),
            "claim": "price-forecast numerical result eligible for application review" if claim_status == "PASS_REAL" else "price-forecast numerical result blocked",
        },
        "claim_boundary": "Market-price forecasting evidence only. It is not Volcore trading P&L and does not include positions, execution, fees, nominations or portfolio netting.",
    }
    if return_row_level:
        result["row_level_final"] = pd.DataFrame({
            "target_start_utc": final["target_start_utc"].astype(str),
            "actual_gbp_mwh": y_final,
            "prediction_gbp_mwh": final_pred,
            "lower_gbp_mwh": final_lower,
            "upper_gbp_mwh": final_upper,
            "previous_settlement_day_gbp_mwh": baseline_final,
            "last_completed_gbp_mwh": last_final,
        }).to_dict(orient="records")
    return result
