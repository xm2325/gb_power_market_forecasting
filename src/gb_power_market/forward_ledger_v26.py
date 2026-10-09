from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd


LEDGER_VERSION = "v0.26-forward-ledger-v1"
LEDGER_SEED_SHA256 = hashlib.sha256(LEDGER_VERSION.encode("utf-8")).hexdigest()
LEDGER_COLUMNS = (
    "target_start_utc",
    "decision_time_utc",
    "realised_price_gbp_mwh",
    "frozen_prediction_gbp_mwh",
    "previous_settlement_day_reference_gbp_mwh",
    "v26_short_residual_mean_gbp_mwh",
    "v26_long_residual_mean_gbp_mwh",
    "v26_gate_reason",
    "v26_correction_gbp_mwh",
    "v26_prediction_gbp_mwh",
)


def _timestamp(value: object) -> str:
    ts = pd.Timestamp(value)
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    else:
        ts = ts.tz_convert("UTC")
    return ts.strftime("%Y-%m-%dT%H:%M:%SZ")


def _float(value: object) -> str:
    return f"{float(value):.9f}"


def _payload(row: pd.Series) -> dict[str, str]:
    return {
        "target_start_utc": _timestamp(row["target_start_utc"]),
        "decision_time_utc": _timestamp(row["decision_time_utc"]),
        "realised_price_gbp_mwh": _float(row["realised_price_gbp_mwh"]),
        "frozen_prediction_gbp_mwh": _float(row["frozen_prediction_gbp_mwh"]),
        "previous_settlement_day_reference_gbp_mwh": _float(
            row["previous_settlement_day_reference_gbp_mwh"]
        ),
        "v26_short_residual_mean_gbp_mwh": _float(row["v26_short_residual_mean_gbp_mwh"]),
        "v26_long_residual_mean_gbp_mwh": _float(row["v26_long_residual_mean_gbp_mwh"]),
        "v26_gate_reason": str(row["v26_gate_reason"]),
        "v26_correction_gbp_mwh": _float(row["v26_correction_gbp_mwh"]),
        "v26_prediction_gbp_mwh": _float(row["v26_prediction_gbp_mwh"]),
    }


def build_v26_forward_ledger(
    corrected_rows: pd.DataFrame,
    *,
    forward_start_utc: str | pd.Timestamp,
) -> pd.DataFrame:
    missing = sorted(set(LEDGER_COLUMNS) - set(corrected_rows.columns))
    if missing:
        raise ValueError(f"v0.26 ledger input missing columns: {missing}")

    x = corrected_rows.copy()
    x["target_start_utc"] = pd.to_datetime(x["target_start_utc"], utc=True, errors="raise")
    start = pd.Timestamp(forward_start_utc)
    if start.tzinfo is None:
        raise ValueError("v0.26 ledger start must be timezone-aware")
    x = x[x["target_start_utc"] >= start].sort_values("target_start_utc").reset_index(drop=True)
    if x["target_start_utc"].duplicated().any():
        raise ValueError("v0.26 ledger contains duplicate targets")

    previous = LEDGER_SEED_SHA256
    records: list[dict[str, str]] = []
    for _, row in x.iterrows():
        payload = _payload(row)
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        row_sha = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
        chain_sha = hashlib.sha256(f"{previous}\n{row_sha}".encode("utf-8")).hexdigest()
        records.append({**payload, "row_sha256": row_sha, "chain_sha256": chain_sha})
        previous = chain_sha
    return pd.DataFrame(records, columns=[*LEDGER_COLUMNS, "row_sha256", "chain_sha256"])


def verify_v26_ledger_chain(ledger: pd.DataFrame) -> None:
    missing = sorted({*LEDGER_COLUMNS, "row_sha256", "chain_sha256"} - set(ledger.columns))
    if missing:
        raise ValueError(f"v0.26 locked ledger missing columns: {missing}")
    previous = LEDGER_SEED_SHA256
    previous_target: pd.Timestamp | None = None
    for i, row in ledger.iterrows():
        payload = {key: str(row[key]) for key in LEDGER_COLUMNS}
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        row_sha = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
        if str(row["row_sha256"]) != row_sha:
            raise ValueError(f"v0.26 ledger row digest mismatch at {i}")
        chain_sha = hashlib.sha256(f"{previous}\n{row_sha}".encode("utf-8")).hexdigest()
        if str(row["chain_sha256"]) != chain_sha:
            raise ValueError(f"v0.26 ledger chain digest mismatch at {i}")
        target = pd.Timestamp(row["target_start_utc"])
        if target.tzinfo is None:
            raise ValueError("v0.26 ledger target must be timezone-aware")
        if previous_target is not None and target <= previous_target:
            raise ValueError("v0.26 ledger targets must be strictly increasing")
        previous_target = target
        previous = chain_sha


def verify_v26_locked_prefix(current: pd.DataFrame, locked: pd.DataFrame) -> dict:
    verify_v26_ledger_chain(locked)
    if len(current) < len(locked):
        raise ValueError("current v0.26 ledger is shorter than locked prefix")
    for i in range(len(locked)):
        if str(current.iloc[i]["row_sha256"]) != str(locked.iloc[i]["row_sha256"]):
            raise ValueError(f"v0.26 replay changed locked row {i}")
        if str(current.iloc[i]["chain_sha256"]) != str(locked.iloc[i]["chain_sha256"]):
            raise ValueError(f"v0.26 replay changed locked chain at row {i}")
    return {
        "status": "LOCKED_PREFIX_REPRODUCED",
        "locked_rows": int(len(locked)),
        "current_rows": int(len(current)),
        "locked_chain_tip_sha256": (
            str(locked.iloc[-1]["chain_sha256"]) if len(locked) else LEDGER_SEED_SHA256
        ),
        "current_chain_tip_sha256": (
            str(current.iloc[-1]["chain_sha256"]) if len(current) else LEDGER_SEED_SHA256
        ),
        "new_rows_after_locked_prefix": int(len(current) - len(locked)),
    }


def load_v26_locked_ledger(path: str | Path) -> pd.DataFrame:
    return pd.read_csv(path, dtype=str, keep_default_na=False)
