from __future__ import annotations

from dataclasses import asdict

import numpy as np
import pandas as pd

from gb_power_market.adaptive_consensus_v26 import (
    ConsensusCorrectionRule,
    apply_causal_consensus_correction,
)


V27_CANDIDATE_ID = "2H_FROZEN_PLUS_CAUSAL_6H_48H_CONSENSUS_WITH_FROZEN_DIRECTION_VETO"
V27_DISCOVERY_END_UTC = pd.Timestamp("2026-08-23T22:00:00Z")
V27_VALIDATION_START_UTC = pd.Timestamp("2026-08-23T22:00:00Z")
V27_VALIDATION_END_UTC = pd.Timestamp("2026-08-24T22:00:00Z")


def apply_causal_direction_veto_candidate(
    rows: pd.DataFrame,
    *,
    rule: ConsensusCorrectionRule = ConsensusCorrectionRule(),
) -> pd.DataFrame:
    """Apply the single pre-validation v0.27 development candidate.

    v0.26 first proposes its unchanged causal 6h/48h consensus correction. This
    candidate adds one sign-only safety veto: the proposed correction is applied
    only when its sign agrees with the direction of the frozen model from the
    latest causally available historical target to the current 2h target.

    No magnitude threshold or parameter search is used. If the frozen model has
    already turned in the opposite direction while both residual windows remain
    jointly stale, the candidate falls back exactly to the frozen prediction.
    """
    x = apply_causal_consensus_correction(rows, rule=rule)
    target = pd.to_datetime(x["target_start_utc"], utc=True, errors="raise")
    frozen = x["frozen_prediction_gbp_mwh"].astype(float)
    frozen_by_target = dict(zip(target, frozen, strict=True))

    proposed = x["v26_correction_gbp_mwh"].astype(float).to_numpy()
    effective = np.zeros(len(x), dtype=float)
    anchor_prediction = np.full(len(x), np.nan, dtype=float)
    direction_delta = np.full(len(x), np.nan, dtype=float)
    gate_reason: list[str] = []

    for i in range(len(x)):
        inherited_reason = str(x.iloc[i]["v26_gate_reason"])
        anchor_raw = x.iloc[i]["v26_history_latest_target_utc"]

        if proposed[i] == 0.0:
            gate_reason.append(f"INHERITED_{inherited_reason}")
            continue
        if anchor_raw is None or pd.isna(anchor_raw):
            gate_reason.append("MISSING_CAUSAL_DIRECTION_ANCHOR_FALLBACK_FROZEN")
            continue

        anchor_target = pd.Timestamp(anchor_raw)
        if anchor_target.tzinfo is None:
            anchor_target = anchor_target.tz_localize("UTC")
        else:
            anchor_target = anchor_target.tz_convert("UTC")
        if anchor_target not in frozen_by_target:
            raise ValueError("v0.27 causal direction anchor is not present in frozen rows")
        if anchor_target >= x.iloc[i]["decision_time_utc"]:
            raise ValueError("v0.27 direction anchor is not causally available at decision time")

        anchor = float(frozen_by_target[anchor_target])
        delta = float(frozen.iloc[i] - anchor)
        anchor_prediction[i] = anchor
        direction_delta[i] = delta

        if delta == 0.0 or np.sign(delta) != np.sign(proposed[i]):
            gate_reason.append("FROZEN_DIRECTION_VETO_FALLBACK_FROZEN")
            continue

        effective[i] = proposed[i]
        gate_reason.append("CONSENSUS_DIRECTION_ALIGNED_CORRECTION")

    x["v27_base_v26_correction_gbp_mwh"] = proposed
    x["v27_direction_anchor_frozen_prediction_gbp_mwh"] = anchor_prediction
    x["v27_frozen_direction_delta_gbp_mwh"] = direction_delta
    x["v27_gate_reason"] = gate_reason
    x["v27_correction_gbp_mwh"] = effective
    x["v27_prediction_gbp_mwh"] = frozen + effective
    y = x["realised_price_gbp_mwh"].astype(float)
    x["v27_abs_error_gbp_mwh"] = np.abs(y - x["v27_prediction_gbp_mwh"])

    if "interval_lower_gbp_mwh" in x.columns:
        lower = x["interval_lower_gbp_mwh"].astype(float)
        upper = x["interval_upper_gbp_mwh"].astype(float)
        x["v27_interval_lower_gbp_mwh"] = lower + effective
        x["v27_interval_upper_gbp_mwh"] = upper + effective
        x["v27_interval_width_gbp_mwh"] = upper - lower
        x["v27_interval_covered"] = (
            (y >= x["v27_interval_lower_gbp_mwh"])
            & (y <= x["v27_interval_upper_gbp_mwh"])
        )

    return x


def summarise_validation_block(
    rows: pd.DataFrame,
    *,
    start_utc: pd.Timestamp = V27_VALIDATION_START_UTC,
    end_utc: pd.Timestamp = V27_VALIDATION_END_UTC,
) -> dict:
    x = rows.copy()
    x["target_start_utc"] = pd.to_datetime(x["target_start_utc"], utc=True, errors="raise")
    segment = x[(x["target_start_utc"] >= start_utc) & (x["target_start_utc"] < end_utc)].copy()
    expected = pd.date_range(start=start_utc, end=end_utc, freq="30min", inclusive="left")

    if len(segment) != len(expected) or not segment["target_start_utc"].reset_index(drop=True).equals(
        pd.Series(expected, name="target_start_utc")
    ):
        return {
            "status": "INCOMPLETE_OR_NONCONTIGUOUS_VALIDATION_BLOCK",
            "rows": int(len(segment)),
            "required_rows": int(len(expected)),
            "validation_start_utc": start_utc.isoformat(),
            "validation_end_exclusive_utc": end_utc.isoformat(),
            "gate_evaluated": False,
            "forward_launch_allowed": False,
        }

    y = segment["realised_price_gbp_mwh"].to_numpy(float)
    candidate = segment["v27_prediction_gbp_mwh"].to_numpy(float)
    frozen = segment["frozen_prediction_gbp_mwh"].to_numpy(float)
    reference = segment["previous_settlement_day_reference_gbp_mwh"].to_numpy(float)
    candidate_abs = np.abs(y - candidate)
    frozen_abs = np.abs(y - frozen)
    reference_abs = np.abs(y - reference)

    candidate_mae = float(candidate_abs.mean())
    frozen_mae = float(frozen_abs.mean())
    reference_mae = float(reference_abs.mean())
    candidate_p95 = float(np.quantile(candidate_abs, 0.95))
    frozen_p95 = float(np.quantile(frozen_abs, 0.95))
    candidate_bias = float((candidate - y).mean())
    frozen_bias = float((frozen - y).mean())

    gates = {
        "candidate_mae_strictly_better_than_frozen": candidate_mae < frozen_mae,
        "candidate_p95_abs_error_non_worse_than_frozen": candidate_p95 <= frozen_p95,
        "candidate_absolute_signed_bias_non_worse_than_frozen": abs(candidate_bias) <= abs(frozen_bias),
        "candidate_mae_strictly_better_than_previous_day_reference": candidate_mae < reference_mae,
    }
    passed = all(gates.values())
    return {
        "status": "VALIDATION_BLOCK_EVALUATED",
        "rows": int(len(segment)),
        "required_rows": int(len(expected)),
        "validation_start_utc": start_utc.isoformat(),
        "validation_end_exclusive_utc": end_utc.isoformat(),
        "candidate_mae_gbp_mwh": candidate_mae,
        "frozen_mae_gbp_mwh": frozen_mae,
        "reference_mae_gbp_mwh": reference_mae,
        "candidate_p95_abs_error_gbp_mwh": candidate_p95,
        "frozen_p95_abs_error_gbp_mwh": frozen_p95,
        "candidate_signed_bias_gbp_mwh": candidate_bias,
        "frozen_signed_bias_gbp_mwh": frozen_bias,
        "candidate_win_rate_vs_frozen": float((candidate_abs < frozen_abs).mean()),
        "direction_veto_rate": float(
            segment["v27_gate_reason"].eq("FROZEN_DIRECTION_VETO_FALLBACK_FROZEN").mean()
        ),
        "gates": gates,
        "all_validation_gates_passed": passed,
        "gate_evaluated": True,
        "forward_launch_allowed": passed,
        "automatic_forward_launch": False,
    }


def candidate_spec(rule: ConsensusCorrectionRule = ConsensusCorrectionRule()) -> dict:
    return {
        "status": "DEVELOPMENT_CANDIDATE_FROZEN_NOT_FORWARD_LAUNCHED",
        "candidate": V27_CANDIDATE_ID,
        "discovery_end_utc": V27_DISCOVERY_END_UTC.isoformat(),
        "validation_start_utc": V27_VALIDATION_START_UTC.isoformat(),
        "validation_end_exclusive_utc": V27_VALIDATION_END_UTC.isoformat(),
        "base_v26_rule": asdict(rule),
        "new_structure": {
            "type": "SIGN_ONLY_FROZEN_DIRECTION_VETO",
            "magnitude_threshold_gbp_mwh": 0.0,
            "parameter_search": False,
            "direction_anchor": "latest residual-history target whose outcome is available by decision time",
            "apply_condition": "sign(v26 proposed correction) == sign(current frozen prediction - anchor frozen prediction)",
            "otherwise": "fallback exactly to unchanged frozen prediction",
        },
        "information_contract": (
            "The veto uses only frozen predictions and the same latest causally available residual-history anchor "
            "already used by v0.26. No target outcome after the current decision time is consulted."
        ),
        "evidence_contract": (
            "Rows through 2026-08-23T22:00:00Z are failure-discovery data only. The exact later 24h block "
            "[2026-08-23T22:00:00Z, 2026-08-24T22:00:00Z) is the only validation block for this candidate. "
            "No parameter change is permitted after any row from that block is inspected."
        ),
    }
