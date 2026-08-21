from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
from typing import Any

import pandas as pd

from .prospective_v21 import ProspectiveGate, model_from_frozen_state, score_prospective_shadow

# v0.22 metrics were blinded, but its pre-gate artifact also contained a
# price-bearing Parquet file through target_start=2026-08-21T11:00:00Z.
# v0.23 therefore begins at the next half-hour and treats the previous window
# as engineering/shadow evidence only.
SEALED_CONFIRMATORY_START_UTC = pd.Timestamp("2026-08-21T11:30:00Z")
SEALED_CONFIRMATORY_ROWS = 672
SEALED_CONFIRMATORY_END_EXCLUSIVE_UTC = SEALED_CONFIRMATORY_START_UTC + pd.Timedelta(
    minutes=30 * SEALED_CONFIRMATORY_ROWS
)

_FORBIDDEN_PRE_REVEAL_KEY_FRAGMENTS = (
    "mae",
    "rmse",
    "improvement",
    "abs_error",
    "prediction",
    "frozen_model",
    "reference_metric",
    "interval_coverage",
    "abstention",
    "classification",
)
_ALLOWED_PROTOCOL_RESAMPLING_KEYS = {"bootstrap_replicates", "bootstrap_seed"}


@dataclass(frozen=True)
class SealedConfirmatoryProtocol:
    exact_rows: int = SEALED_CONFIRMATORY_ROWS
    minimum_target_coverage: float = 0.95
    future_neso_publications_allowed: int = 0
    bootstrap_replicates: int = 5000
    bootstrap_seed: int = 20260821


def _normalise_boundary(value: str | pd.Timestamp) -> pd.Timestamp:
    t = pd.Timestamp(value)
    if t.tzinfo is None:
        raise ValueError("sealed confirmatory boundaries must be timezone-aware")
    return t.tz_convert("UTC")


def sealed_target_grid() -> pd.DatetimeIndex:
    return pd.date_range(
        SEALED_CONFIRMATORY_START_UTC,
        SEALED_CONFIRMATORY_END_EXCLUSIVE_UTC,
        freq="30min",
        inclusive="left",
    )


def _timestamp_grid_sha256(grid: pd.DatetimeIndex) -> str:
    payload = "\n".join(pd.Timestamp(x).isoformat() for x in grid).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def sealed_target_grid_sha256() -> str:
    return _timestamp_grid_sha256(sealed_target_grid())


def frozen_state_sha256(state: dict[str, Any]) -> str:
    payload = json.dumps(
        state,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _find_forbidden_keys(value: Any, path: tuple[str, ...] = ()) -> list[str]:
    found: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            key_str = str(key)
            key_text = key_str.lower()
            is_allowed_protocol_resampling = (
                bool(path)
                and path[-1] == "protocol"
                and key_text in _ALLOWED_PROTOCOL_RESAMPLING_KEYS
            )
            if not is_allowed_protocol_resampling:
                if "bootstrap" in key_text or any(
                    fragment in key_text for fragment in _FORBIDDEN_PRE_REVEAL_KEY_FRAGMENTS
                ):
                    found.append(".".join((*path, key_str)))
            found.extend(_find_forbidden_keys(child, (*path, key_str)))
    elif isinstance(value, list):
        for i, child in enumerate(value):
            found.extend(_find_forbidden_keys(child, (*path, str(i))))
    return found


def assert_pre_reveal_payload_safe(payload: dict[str, Any]) -> None:
    """Fail if a blinded payload contains performance-bearing key names.

    The check is recursive so a metric cannot be hidden in a nested object.
    Predeclared resampling configuration is allowed only under ``protocol``;
    a bootstrap result or similarly named field anywhere else remains forbidden.
    """
    if payload.get("status") == "SEALED_CONFIRMATORY_REVEALED":
        return
    leaked = sorted(set(_find_forbidden_keys(payload)))
    if leaked:
        raise ValueError(f"pre-reveal payload contains forbidden performance keys: {leaked}")


def sealed_blinded_availability(
    frame: pd.DataFrame,
    *,
    frozen_state: dict[str, Any],
    available_end_exclusive_utc: str | pd.Timestamp,
    target_col: str = "reference_market_price_gbp_mwh",
    protocol: SealedConfirmatoryProtocol = SealedConfirmatoryProtocol(),
) -> dict[str, Any]:
    """Audit a fixed confirmatory window without computing performance.

    Pre-reveal code may inspect row identity, feature completeness and
    publication timing only. Target values are required for completeness but are
    never aggregated, compared with predictions or serialised in this payload.
    """
    model_from_frozen_state(frozen_state)
    available_end = _normalise_boundary(available_end_exclusive_utc)
    fixed_grid = sealed_target_grid()
    if len(fixed_grid) != protocol.exact_rows:
        raise AssertionError("sealed confirmatory grid does not match protocol row count")

    bounded_end = min(max(available_end, SEALED_CONFIRMATORY_START_UTC), SEALED_CONFIRMATORY_END_EXCLUSIVE_UTC)
    expected_grid = fixed_grid[fixed_grid < bounded_end]
    expected_rows_so_far = len(expected_grid)

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
    df = df[
        (df["target_start_utc"] >= SEALED_CONFIRMATORY_START_UTC)
        & (df["target_start_utc"] < bounded_end)
    ].copy()
    complete = df.dropna(subset=list(dict.fromkeys(required))).copy()

    target_series = complete["target_start_utc"]
    duplicate_rows = int(target_series.duplicated(keep=False).sum())
    on_grid_mask = target_series.isin(expected_grid)
    off_grid_rows = int((~on_grid_mask).sum())
    unique_on_grid = pd.DatetimeIndex(
        target_series.loc[on_grid_mask].drop_duplicates().sort_values().tolist()
    )
    missing_grid = expected_grid.difference(unique_on_grid)
    complete_rows = len(unique_on_grid)
    coverage = float(complete_rows / expected_rows_so_far) if expected_rows_so_far else 0.0

    future_neso = 0
    if str(frozen_state["selected_family"]) == "PRICE_PLUS_NESO_LEVELS" and not complete.empty:
        if "neso_publish_time_utc" not in complete.columns:
            raise ValueError("NESO-level frozen model requires neso_publish_time_utc")
        pub = pd.to_datetime(complete["neso_publish_time_utc"], utc=True, errors="coerce")
        future_neso = int((pub.notna() & (pub > complete["decision_time_utc"])).sum())

    fixed_window_elapsed = available_end >= SEALED_CONFIRMATORY_END_EXCLUSIVE_UTC
    rows_remaining = max(0, protocol.exact_rows - complete_rows)

    if duplicate_rows:
        status = "BLOCKED_EVIDENCE"
        reason = "duplicate target timestamps entered the sealed confirmatory frame"
    elif off_grid_rows:
        status = "BLOCKED_EVIDENCE"
        reason = "off-grid target timestamps entered the sealed confirmatory frame"
    elif future_neso > protocol.future_neso_publications_allowed:
        status = "BLOCKED_EVIDENCE"
        reason = "future NESO publication entered the sealed confirmatory feature frame"
    elif expected_rows_so_far and coverage < protocol.minimum_target_coverage:
        status = "BLOCKED_EVIDENCE"
        reason = "target/feature coverage below the predeclared minimum"
    elif not fixed_window_elapsed or complete_rows < protocol.exact_rows:
        status = "SEALED_ACCUMULATION"
        reason = "fixed 672-half-hour reveal window is not complete"
    elif missing_grid.size:
        status = "BLOCKED_EVIDENCE"
        reason = "fixed reveal grid is incomplete"
    else:
        status = "SEALED_REVEAL_ELIGIBLE"
        reason = "fixed sealed window is complete and information gates pass"

    payload = {
        "version": "0.23.0",
        "status": status,
        "reason": reason,
        "source_evidence_id_sha256": frozen_state["source_evidence_id_sha256"],
        "horizon_minutes": int(frozen_state["horizon_minutes"]),
        "selected_family": str(frozen_state["selected_family"]),
        "alpha": float(frozen_state["alpha"]),
        "model_identity": {
            "state_sha256": frozen_state_sha256(frozen_state),
            "model_changed": False,
        },
        "sealed_window": {
            "start_utc": SEALED_CONFIRMATORY_START_UTC.isoformat(),
            "fixed_end_exclusive_utc": SEALED_CONFIRMATORY_END_EXCLUSIVE_UTC.isoformat(),
            "available_end_exclusive_utc": available_end.isoformat(),
            "expected_rows_so_far": int(expected_rows_so_far),
            "complete_rows_so_far": int(complete_rows),
            "coverage_so_far": coverage,
            "rows_required_for_reveal": int(protocol.exact_rows),
            "rows_remaining_to_reveal": int(rows_remaining),
        },
        "grid_audit": {
            "fixed_grid_sha256": sealed_target_grid_sha256(),
            "available_grid_sha256": _timestamp_grid_sha256(expected_grid),
            "duplicate_complete_rows": duplicate_rows,
            "off_grid_complete_rows": off_grid_rows,
            "missing_expected_rows": int(len(missing_grid)),
        },
        "information_audit": {
            "future_neso_publications": int(future_neso),
            "allowed": int(protocol.future_neso_publications_allowed),
        },
        "protocol": asdict(protocol),
        "seal_boundary": (
            "Before SEALED_REVEAL_ELIGIBLE, output contains only row identity, completeness, source/model identity and publication timing. "
            "No point-loss, interval, action, direction or bootstrap performance is computed or serialised."
        ),
    }
    assert_pre_reveal_payload_safe(payload)
    return payload


def _confirmatory_classification(scored: dict[str, Any]) -> dict[str, Any]:
    block = scored.get("daily_block_bootstrap", {})
    if block.get("status") != "PASS":
        return {"status": "CONFIRMATORY_INCONCLUSIVE", "reason": "daily-block bootstrap unavailable"}
    lo = float(block["ci95_low_gbp_mwh"])
    hi = float(block["ci95_high_gbp_mwh"])
    if hi < 0.0:
        status = "CONFIRMATORY_POSITIVE"
        reason = "95% daily-block interval for model-minus-reference MAE is entirely below zero"
    elif lo > 0.0:
        status = "CONFIRMATORY_NEGATIVE"
        reason = "95% daily-block interval for model-minus-reference MAE is entirely above zero"
    else:
        status = "CONFIRMATORY_INCONCLUSIVE"
        reason = "95% daily-block interval crosses zero"
    return {
        "status": status,
        "reason": reason,
        "ci95_low_gbp_mwh": lo,
        "ci95_high_gbp_mwh": hi,
        "decision_rule": "negative interval favours frozen model; positive interval favours previous-settlement-day reference",
    }


def evaluate_sealed_confirmatory(
    frame: pd.DataFrame,
    *,
    frozen_state: dict[str, Any],
    available_end_exclusive_utc: str | pd.Timestamp,
    target_col: str = "reference_market_price_gbp_mwh",
    protocol: SealedConfirmatoryProtocol = SealedConfirmatoryProtocol(),
) -> dict[str, Any]:
    audit = sealed_blinded_availability(
        frame,
        frozen_state=frozen_state,
        available_end_exclusive_utc=available_end_exclusive_utc,
        target_col=target_col,
        protocol=protocol,
    )
    if audit["status"] != "SEALED_REVEAL_ELIGIBLE":
        return audit

    gate = ProspectiveGate(
        minimum_rows=protocol.exact_rows,
        minimum_target_coverage=protocol.minimum_target_coverage,
        future_neso_publications_allowed=protocol.future_neso_publications_allowed,
        minimum_complete_utc_days_for_block_bootstrap=7,
        bootstrap_replicates=protocol.bootstrap_replicates,
        bootstrap_seed=protocol.bootstrap_seed,
    )
    scored = score_prospective_shadow(
        frame,
        frozen_state=frozen_state,
        start_utc=SEALED_CONFIRMATORY_START_UTC,
        end_exclusive_utc=SEALED_CONFIRMATORY_END_EXCLUSIVE_UTC,
        target_col=target_col,
        gate=gate,
    )
    if scored["status"] != "PROSPECTIVE_EVIDENCE_READY":
        raise RuntimeError(f"sealed confirmatory reveal unexpectedly blocked: {scored['status']}")
    return {
        "version": "0.23.0",
        "status": "SEALED_CONFIRMATORY_REVEALED",
        "availability_gate": audit,
        "classification": _confirmatory_classification(scored),
        "scored_window": scored,
        "reveal_boundary": (
            "Exactly the predeclared 672 half-hours are revealed once; later observations cannot alter this confirmatory window."
        ),
    }
