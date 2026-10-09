#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import pandas as pd

from gb_power_market.v27_prediction_freeze import build_first_frozen_target_row, freeze_first_prediction
from gb_power_market.v27_pretarget_recovery import (
    recovery_prediction_timing_lock,
    verify_recovery_prediction_window,
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--implementation-lock", default="reports/locked/V0_27_IMPLEMENTATION_LOCK.json")
    ap.add_argument("--recovery-lock", default="reports/forward/v27/V0_27_PRETARGET_RECOVERY_LOCK.json")
    ap.add_argument("--model-state", default="reports/locked/V0_21_FROZEN_MODEL_STATE.json")
    ap.add_argument("--reference-history", required=True)
    ap.add_argument("--neso-current", required=True)
    ap.add_argument("--historical-frozen-rows", required=True)
    ap.add_argument("--out", default="reports/forward/v27/V0_27_PRETARGET_RECOVERY_PREDICTION.json")
    ap.add_argument("--provenance", default="reports/forward/v27/V0_27_PRETARGET_RECOVERY_PREDICTION_PROVENANCE.json")
    args = ap.parse_args()

    implementation_path = Path(args.implementation_lock)
    recovery_path = Path(args.recovery_lock)
    implementation = json.loads(implementation_path.read_text(encoding="utf-8"))
    recovery = json.loads(recovery_path.read_text(encoding="utf-8"))
    timing = verify_recovery_prediction_window(recovery_lock=recovery, now_utc=datetime.now(timezone.utc))
    target_lock = recovery_prediction_timing_lock(
        implementation_lock=implementation,
        recovery_lock=recovery,
    )

    model_path = Path(args.model_state)
    model_bundle = json.loads(model_path.read_text(encoding="utf-8"))
    reference = pd.read_parquet(args.reference_history)
    neso = pd.read_parquet(args.neso_current)
    history = pd.read_csv(args.historical_frozen_rows)

    decision = pd.Timestamp(recovery["recovery_decision_time_utc"])
    target = pd.Timestamp(recovery["recovery_target_start_utc"])
    pubs = pd.to_datetime(neso["publish_time_utc"], utc=True, errors="raise")
    if (pubs > decision).any():
        raise ValueError("recovery prediction input contains NESO vintages published after decision")

    target_row = build_first_frozen_target_row(
        reference_history=reference,
        neso_current=neso,
        model_bundle=model_bundle,
        implementation_lock=target_lock,
    )
    prediction = freeze_first_prediction(
        historical_frozen_rows=history,
        first_target_row=target_row,
        implementation_lock=target_lock,
    )

    now_after = datetime.now(timezone.utc)
    verify_recovery_prediction_window(recovery_lock=recovery, now_utc=now_after)
    prediction.update(
        {
            "schema": "gb-power-market-v27-pretarget-recovery-prediction-v1",
            "status": "RECOVERY_PREDICTION_FROZEN_BEFORE_TARGET_OUTCOME",
            "original_forward_start_utc": implementation["forward_start_utc"],
            "original_forward_boundary_changed": False,
            "recovery_lock_timestamp_utc": recovery["recovery_lock_timestamp_utc"],
            "recovery_decision_time_utc": recovery["recovery_decision_time_utc"],
            "recovery_target_start_utc": recovery["recovery_target_start_utc"],
            "recovery_lock_sha256": _sha256(recovery_path),
            "freeze_completed_utc": now_after.isoformat(),
            "evidence_class": "PRE_TARGET_GIT_COMMITTED_PREDICTION_NOT_YET_SCORED",
        }
    )
    if pd.Timestamp(prediction["target_start_utc"]) != target:
        raise RuntimeError("recovery prediction target changed")
    if pd.Timestamp(prediction["decision_time_utc"]) != decision:
        raise RuntimeError("recovery prediction decision changed")
    if pd.Timestamp(prediction["freeze_completed_utc"]) >= target:
        raise RuntimeError("recovery freeze completed after target start")
    if prediction["target_label_status"] != "UNOBSERVED_NOT_ACCESSED":
        raise RuntimeError("recovery prediction target label state changed")
    if prediction["realised_price_in_prediction_record"] is not False:
        raise RuntimeError("recovery prediction contains realised target price")

    out = Path(args.out)
    provenance_path = Path(args.provenance)
    if out.exists() or provenance_path.exists():
        raise FileExistsError("v0.27 recovery prediction already exists; refusing rewrite")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(prediction, indent=2) + "\n", encoding="utf-8")

    provenance = {
        "schema": "gb-power-market-v27-pretarget-recovery-prediction-provenance-v1",
        "status": "PRE_TARGET_RECOVERY_PREDICTION_FROZEN",
        "implementation_lock_path": implementation_path.as_posix(),
        "implementation_lock_sha256": _sha256(implementation_path),
        "recovery_lock_path": recovery_path.as_posix(),
        "recovery_lock_sha256": _sha256(recovery_path),
        "model_state_path": model_path.as_posix(),
        "model_state_sha256": _sha256(model_path),
        "reference_history_path": str(args.reference_history),
        "reference_history_sha256": _sha256(Path(args.reference_history)),
        "neso_asof_path": str(args.neso_current),
        "neso_asof_sha256": _sha256(Path(args.neso_current)),
        "historical_frozen_rows_path": str(args.historical_frozen_rows),
        "historical_frozen_rows_sha256": _sha256(Path(args.historical_frozen_rows)),
        "prediction_path": out.as_posix(),
        "prediction_sha256": _sha256(out),
        "timing_preflight": timing,
        "freeze_completed_utc": prediction["freeze_completed_utc"],
        "target_start_utc": prediction["target_start_utc"],
        "target_label_accessed": False,
        "original_forward_boundary_changed": False,
        "evidence_class": "PRE_TARGET_GIT_COMMITTED_PREDICTION_NOT_YET_SCORED",
    }
    provenance_path.write_text(json.dumps(provenance, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"prediction": prediction, "provenance": provenance}, indent=2))


if __name__ == "__main__":
    main()
