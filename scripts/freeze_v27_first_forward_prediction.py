#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from gb_power_market.v27_prediction_freeze import (
    build_first_frozen_target_row,
    freeze_first_prediction,
    verify_freeze_window,
)


EXPECTED_IMPLEMENTATION_LOCK_SHA256: str | None = None


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--implementation-lock", default="reports/locked/V0_27_IMPLEMENTATION_LOCK.json")
    ap.add_argument("--model-state", default="reports/locked/V0_21_FROZEN_MODEL_STATE.json")
    ap.add_argument("--reference-history", required=True)
    ap.add_argument("--neso-current", required=True)
    ap.add_argument("--historical-frozen-rows", required=True)
    ap.add_argument("--out", default="reports/forward/v27/V0_27_FIRST_FORWARD_PREDICTION_2026-08-25_0230Z.json")
    ap.add_argument("--provenance", default="reports/forward/v27/V0_27_FIRST_FORWARD_PREDICTION_PROVENANCE.json")
    args = ap.parse_args()

    lock_path = Path(args.implementation_lock)
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    timing = verify_freeze_window(implementation_lock=lock, now_utc=datetime.now(timezone.utc))

    model_path = Path(args.model_state)
    model_bundle = json.loads(model_path.read_text(encoding="utf-8"))
    reference = pd.read_parquet(args.reference_history)
    neso = pd.read_parquet(args.neso_current)
    history = pd.read_csv(args.historical_frozen_rows)

    target_row = build_first_frozen_target_row(
        reference_history=reference,
        neso_current=neso,
        model_bundle=model_bundle,
        implementation_lock=lock,
    )
    prediction = freeze_first_prediction(
        historical_frozen_rows=history,
        first_target_row=target_row,
        implementation_lock=lock,
    )

    now_after = datetime.now(timezone.utc)
    verify_freeze_window(implementation_lock=lock, now_utc=now_after)
    prediction["freeze_completed_utc"] = now_after.isoformat()
    if pd.Timestamp(prediction["freeze_completed_utc"]) >= pd.Timestamp(prediction["target_start_utc"]):
        raise RuntimeError("prediction freeze completed after target start; refusing retrospective record")
    if prediction.get("realised_price_in_prediction_record") is not False:
        raise RuntimeError("prediction record unexpectedly contains realised target price")

    out = Path(args.out)
    provenance_path = Path(args.provenance)
    if out.exists() or provenance_path.exists():
        raise FileExistsError("first v0.27 forward prediction is already frozen; refusing rewrite")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(prediction, indent=2) + "\n", encoding="utf-8")

    provenance = {
        "schema": "gb-power-market-v27-first-forward-prediction-provenance-v1",
        "status": "PRE_TARGET_PREDICTION_FROZEN",
        "implementation_lock_path": lock_path.as_posix(),
        "implementation_lock_sha256": _sha256(lock_path),
        "model_state_path": model_path.as_posix(),
        "model_state_sha256": _sha256(model_path),
        "reference_history_path": str(args.reference_history),
        "reference_history_sha256": _sha256(Path(args.reference_history)),
        "neso_current_path": str(args.neso_current),
        "neso_current_sha256": _sha256(Path(args.neso_current)),
        "historical_frozen_rows_path": str(args.historical_frozen_rows),
        "historical_frozen_rows_sha256": _sha256(Path(args.historical_frozen_rows)),
        "prediction_path": out.as_posix(),
        "prediction_sha256": _sha256(out),
        "timing_preflight": timing,
        "freeze_completed_utc": prediction["freeze_completed_utc"],
        "target_start_utc": prediction["target_start_utc"],
        "target_label_accessed": False,
        "evidence_class": "PRE_TARGET_PREDICTION_NOT_YET_SCORED",
    }
    provenance_path.write_text(json.dumps(provenance, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"prediction": prediction, "provenance": provenance}, indent=2))


if __name__ == "__main__":
    main()
