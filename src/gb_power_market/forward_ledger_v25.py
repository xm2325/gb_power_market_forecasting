from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd


LEDGER_VERSION = "v0.25-forward-ledger-v1"
LEDGER_SEED_SHA256 = hashlib.sha256(LEDGER_VERSION.encode("utf-8")).hexdigest()
LEDGER_COLUMNS = (
    "target_start_utc",
    "decision_time_utc",
    "realised_price_gbp_mwh",
    "frozen_prediction_gbp_mwh",
    "previous_settlement_day_reference_gbp_mwh",
    "bias_correction_gbp_mwh",
    "bias_history_rows",
    "bias_history_latest_target_utc",
    "adaptive_prediction_gbp_mwh",
)


def _canonical_timestamp(value: object) -> str:
    ts = pd.Timestamp(value)
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    else:
        ts = ts.tz_convert("UTC")
    return ts.strftime("%Y-%m-%dT%H:%M:%SZ")


def _canonical_float(value: object) -> str:
    return f"{float(value):.9f}"


def _canonical_payload(row: pd.Series) -> dict[str, str]:
    return {
        "target_start_utc": _canonical_timestamp(row["target_start_utc"]),
        "decision_time_utc": _canonical_timestamp(row["decision_time_utc"]),
        "realised_price_gbp_mwh": _canonical_float(row["realised_price_gbp_mwh"]),
        "frozen_prediction_gbp_mwh": _canonical_float(row["frozen_prediction_gbp_mwh"]),
        "previous_settlement_day_reference_gbp_mwh": _canonical_float(
            row["previous_settlement_day_reference_gbp_mwh"]
        ),
        "bias_correction_gbp_mwh": _canonical_float(row["bias_correction_gbp_mwh"]),
        "bias_history_rows": str(int(row["bias_history_rows"])),
        "bias_history_latest_target_utc": _canonical_timestamp(row["bias_history_latest_target_utc"]),
        "adaptive_prediction_gbp_mwh": _canonical_float(row["adaptive_prediction_gbp_mwh"]),
    }


def build_forward_ledger(
    corrected_rows: pd.DataFrame,
    *,
    forward_start_utc: str | pd.Timestamp,
) -> pd.DataFrame:
    """Create a deterministic row hash-chain for the unchanged v0.25 candidate."""
    missing = sorted(set(LEDGER_COLUMNS) - set(corrected_rows.columns))
    if missing:
        raise ValueError(f"forward-ledger input missing columns: {missing}")

    x = corrected_rows.copy()
    x["target_start_utc"] = pd.to_datetime(x["target_start_utc"], utc=True, errors="raise")
    x["decision_time_utc"] = pd.to_datetime(x["decision_time_utc"], utc=True, errors="raise")
    x["bias_history_latest_target_utc"] = pd.to_datetime(
        x["bias_history_latest_target_utc"], utc=True, errors="raise"
    )
    start = pd.Timestamp(forward_start_utc)
    if start.tzinfo is None:
        raise ValueError("forward_start_utc must be timezone-aware")
    x = x[x["target_start_utc"] >= start].sort_values("target_start_utc").reset_index(drop=True)
    if x["target_start_utc"].duplicated().any():
        raise ValueError("forward-ledger input contains duplicate targets")

    records: list[dict[str, str]] = []
    previous = LEDGER_SEED_SHA256
    for _, row in x.iterrows():
        payload = _canonical_payload(row)
        canonical_json = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        row_sha = hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()
        chain_sha = hashlib.sha256(f"{previous}\n{row_sha}".encode("utf-8")).hexdigest()
        records.append({**payload, "row_sha256": row_sha, "chain_sha256": chain_sha})
        previous = chain_sha

    return pd.DataFrame(records, columns=[*LEDGER_COLUMNS, "row_sha256", "chain_sha256"])


def verify_ledger_chain(ledger: pd.DataFrame) -> None:
    """Fail closed if a committed ledger has been edited or reordered."""
    required = {*LEDGER_COLUMNS, "row_sha256", "chain_sha256"}
    missing = sorted(required - set(ledger.columns))
    if missing:
        raise ValueError(f"locked ledger missing columns: {missing}")

    previous = LEDGER_SEED_SHA256
    last_target: pd.Timestamp | None = None
    for i, row in ledger.iterrows():
        payload = {key: str(row[key]) for key in LEDGER_COLUMNS}
        canonical_json = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        expected_row = hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()
        if str(row["row_sha256"]) != expected_row:
            raise ValueError(f"locked ledger row digest mismatch at row {i}")
        expected_chain = hashlib.sha256(f"{previous}\n{expected_row}".encode("utf-8")).hexdigest()
        if str(row["chain_sha256"]) != expected_chain:
            raise ValueError(f"locked ledger chain digest mismatch at row {i}")
        target = pd.Timestamp(row["target_start_utc"])
        if target.tzinfo is None:
            raise ValueError("locked ledger target timestamps must be timezone-aware")
        if last_target is not None and target <= last_target:
            raise ValueError("locked ledger targets must be strictly increasing")
        last_target = target
        previous = expected_chain


def verify_locked_prefix(current: pd.DataFrame, locked: pd.DataFrame) -> dict:
    """Require every previously locked row to be reproduced byte-for-byte canonically."""
    verify_ledger_chain(locked)
    if len(current) < len(locked):
        raise ValueError(
            f"current forward ledger is shorter than locked prefix: {len(current)} < {len(locked)}"
        )

    for i in range(len(locked)):
        if str(current.iloc[i]["row_sha256"]) != str(locked.iloc[i]["row_sha256"]):
            target = locked.iloc[i]["target_start_utc"]
            raise ValueError(f"current replay changed locked forward row {i} ({target})")
        if str(current.iloc[i]["chain_sha256"]) != str(locked.iloc[i]["chain_sha256"]):
            raise ValueError(f"current replay changed locked forward chain at row {i}")

    return {
        "status": "LOCKED_PREFIX_REPRODUCED",
        "locked_rows": int(len(locked)),
        "current_rows": int(len(current)),
        "locked_chain_tip_sha256": str(locked.iloc[-1]["chain_sha256"]) if len(locked) else LEDGER_SEED_SHA256,
        "current_chain_tip_sha256": str(current.iloc[-1]["chain_sha256"]) if len(current) else LEDGER_SEED_SHA256,
        "new_rows_after_locked_prefix": int(len(current) - len(locked)),
    }


def load_locked_ledger(path: str | Path) -> pd.DataFrame:
    return pd.read_csv(path, dtype=str, keep_default_na=False)
