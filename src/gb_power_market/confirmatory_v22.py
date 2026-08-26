from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

import pandas as pd

from .prospective_v21 import ProspectiveGate, model_from_frozen_state, score_prospective_shadow

CONFIRMATORY_START_UTC = pd.Timestamp("2026-08-20T23:00:00Z")
CONFIRMATORY_ROWS = 672
CONFIRMATORY_END_EXCLUSIVE_UTC = CONFIRMATORY_START_UTC + pd.Timedelta(minutes=30 * CONFIRMATORY_ROWS)


@dataclass(frozen=True)
class ConfirmatoryProtocol:
    minimum_rows: int = CONFIRMATORY_ROWS
    minimum_target_coverage: float = 0.95
    future_neso_publications_allowed: int = 0
    bootstrap_replicates: int = 5000
    bootstrap_seed: int = 20260821


def _normalise_boundary(value: str | pd.Timestamp) -> pd.Timestamp:
    t = pd.Timestamp(value)
    if t.tzinfo is None:
        raise ValueError("confirmatory boundaries must be timezone-aware")
    return t.tz_convert("UTC")


def blinded_availability(
    frame: pd.DataFrame,
    *,
    frozen_state: dict[str, Any],
    available_end_exclusive_utc: str | pd.Timestamp,
    target_col: str = "reference_market_price_gbp_mwh",
    protocol: ConfirmatoryProtocol = ConfirmatoryProtocol(),
) -> dict[str, Any]:
    """Report whether the fixed confirmatory window is ready without scoring it.

    Before the exact 672-half-hour window is fully available this function may
    inspect timestamps, missingness and publication timing only. It deliberately
    does not calculate any loss, interval or directional performance metric.
    """
    model_from_frozen_state(frozen_state)  # validate immutable model identity
    available_end = _normalise_boundary(available_end_exclusive_utc)
    if available_end <= CONFIRMATORY_START_UTC:
        expected_so_far = 0
    else:
        bounded_end = min(available_end, CONFIRMATORY_END_EXCLUSIVE_UTC)
        expected_so_far = len(
            pd.date_range(CONFIRMATORY_START_UTC, bounded_end, freq="30min", inclusive="left")
        )

    features = list(frozen_state["features"])
    required = [
        "target_start_utc",
        "decision_time_utc",
        target_col,
        "price_lag_1d_same_target",
        "price_lag_last_completed",
        *features,
    ]
    df = frame.copy()
    df["target_start_utc"] = pd.to_datetime(df["target_start_utc"], utc=True, errors="raise")
    df["decision_time_utc"] = pd.to_datetime(df["decision_time_utc"], utc=True, errors="raise")
    bounded_end = min(max(available_end, CONFIRMATORY_START_UTC), CONFIRMATORY_END_EXCLUSIVE_UTC)
    df = df[
        (df["target_start_utc"] >= CONFIRMATORY_START_UTC)
        & (df["target_start_utc"] < bounded_end)
    ].copy()
    complete = df.dropna(subset=list(dict.fromkeys(required))).copy()

    future_neso = 0
    if str(frozen_state["selected_family"]) == "PRICE_PLUS_NESO_LEVELS":
        if "neso_publish_time_utc" not in complete.columns:
            raise ValueError("NESO-level frozen model requires neso_publish_time_utc")
        pub = pd.to_datetime(complete["neso_publish_time_utc"], utc=True, errors="coerce")
        future_neso = int((pub.notna() & (pub > complete["decision_time_utc"])).sum())

    coverage = float(len(complete) / expected_so_far) if expected_so_far else 0.0
    fixed_window_elapsed = available_end >= CONFIRMATORY_END_EXCLUSIVE_UTC
    full_expected = int(protocol.minimum_rows)
    rows_remaining = max(0, full_expected - len(complete))

    if future_neso > protocol.future_neso_publications_allowed:
        status = "BLOCKED_EVIDENCE"
        reason = "future NESO publication entered the confirmatory feature frame"
    elif expected_so_far and coverage < protocol.minimum_target_coverage:
        status = "BLOCKED_EVIDENCE"
        reason = "target/feature coverage below the predeclared minimum"
    elif not fixed_window_elapsed or len(complete) < protocol.minimum_rows:
        status = "BLINDED_ACCUMULATION"
        reason = "fixed 672-half-hour reveal window is not complete"
    else:
        status = "REVEAL_ELIGIBLE"
        reason = "fixed confirmatory window is complete and information gates pass"

    return {
        "version": "0.22.0",
        "status": status,
        "reason": reason,
        "source_evidence_id_sha256": frozen_state["source_evidence_id_sha256"],
        "horizon_minutes": int(frozen_state["horizon_minutes"]),
        "selected_family": str(frozen_state["selected_family"]),
        "alpha": float(frozen_state["alpha"]),
        "confirmatory_window": {
            "start_utc": CONFIRMATORY_START_UTC.isoformat(),
            "fixed_end_exclusive_utc": CONFIRMATORY_END_EXCLUSIVE_UTC.isoformat(),
            "available_end_exclusive_utc": available_end.isoformat(),
            "expected_rows_so_far": int(expected_so_far),
            "complete_rows_so_far": int(len(complete)),
            "coverage_so_far": coverage,
            "rows_required_for_reveal": int(protocol.minimum_rows),
            "rows_remaining_to_reveal": int(rows_remaining),
        },
        "information_audit": {
            "future_neso_publications": int(future_neso),
            "allowed": int(protocol.future_neso_publications_allowed),
        },
        "protocol": asdict(protocol),
        "blinding_boundary": (
            "Before REVEAL_ELIGIBLE, output contains counts/coverage/publication timing only. "
            "No MAE, improvement, interval, direction or bootstrap performance is computed."
        ),
    }


def _confirmatory_classification(scored: dict[str, Any]) -> dict[str, Any]:
    bootstrap = scored.get("daily_block_bootstrap", {})
    if bootstrap.get("status") != "PASS":
        return {
            "status": "CONFIRMATORY_INCONCLUSIVE",
            "reason": "daily-block bootstrap unavailable",
        }
    lo = float(bootstrap["ci95_low_gbp_mwh"])
    hi = float(bootstrap["ci95_high_gbp_mwh"])
    if hi < 0.0:
        status = "CONFIRMATORY_POSITIVE"
        reason = "95% daily-block bootstrap interval for model-minus-reference MAE is entirely below zero"
    elif lo > 0.0:
        status = "CONFIRMATORY_NEGATIVE"
        reason = "95% daily-block bootstrap interval for model-minus-reference MAE is entirely above zero"
    else:
        status = "CONFIRMATORY_INCONCLUSIVE"
        reason = "95% daily-block bootstrap interval crosses zero"
    return {
        "status": status,
        "reason": reason,
        "ci95_low_gbp_mwh": lo,
        "ci95_high_gbp_mwh": hi,
        "decision_rule": "negative interval favours frozen model; positive interval favours previous-settlement-day reference",
    }


def evaluate_blinded_confirmatory(
    frame: pd.DataFrame,
    *,
    frozen_state: dict[str, Any],
    available_end_exclusive_utc: str | pd.Timestamp,
    target_col: str = "reference_market_price_gbp_mwh",
    protocol: ConfirmatoryProtocol = ConfirmatoryProtocol(),
) -> dict[str, Any]:
    """Accumulate blindly, then reveal exactly one predeclared 14-day window."""
    audit = blinded_availability(
        frame,
        frozen_state=frozen_state,
        available_end_exclusive_utc=available_end_exclusive_utc,
        target_col=target_col,
        protocol=protocol,
    )
    if audit["status"] != "REVEAL_ELIGIBLE":
        return audit

    gate = ProspectiveGate(
        minimum_rows=protocol.minimum_rows,
        minimum_target_coverage=protocol.minimum_target_coverage,
        future_neso_publications_allowed=protocol.future_neso_publications_allowed,
        minimum_complete_utc_days_for_block_bootstrap=7,
        bootstrap_replicates=protocol.bootstrap_replicates,
        bootstrap_seed=protocol.bootstrap_seed,
    )
    scored = score_prospective_shadow(
        frame,
        frozen_state=frozen_state,
        start_utc=CONFIRMATORY_START_UTC,
        end_exclusive_utc=CONFIRMATORY_END_EXCLUSIVE_UTC,
        target_col=target_col,
        gate=gate,
    )
    if scored["status"] != "PROSPECTIVE_EVIDENCE_READY":
        raise RuntimeError(f"confirmatory reveal unexpectedly blocked: {scored['status']}")
    return {
        "version": "0.22.0",
        "status": "CONFIRMATORY_REVEALED",
        "availability_gate": audit,
        "classification": _confirmatory_classification(scored),
        "scored_window": scored,
        "reveal_boundary": (
            "Exactly 672 predeclared half-hours are revealed once. Later observations do not change this confirmatory window."
        ),
    }
