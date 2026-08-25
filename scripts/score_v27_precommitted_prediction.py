#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from gb_power_market.v27_precommitted_scoring import (
    score_precommitted_prediction,
    verify_scoring_maturity,
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--prediction", required=True)
    ap.add_argument("--reference-market", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--provenance", required=True)
    args = ap.parse_args()

    prediction_path = Path(args.prediction)
    reference_path = Path(args.reference_market)
    out = Path(args.out)
    provenance_path = Path(args.provenance)
    if out.exists() or provenance_path.exists():
        raise FileExistsError("v0.27 precommitted score already exists; refusing rewrite")

    prediction = json.loads(prediction_path.read_text(encoding="utf-8"))
    maturity = verify_scoring_maturity(prediction=prediction, now_utc=datetime.now(timezone.utc))

    ref = pd.read_parquet(reference_path).copy()
    ref["target_start_utc"] = pd.to_datetime(ref["target_start_utc"], utc=True, errors="raise")
    target = pd.Timestamp(prediction["target_start_utc"])
    row = ref[ref["target_start_utc"] == target]
    if len(row) != 1:
        raise ValueError(f"expected exactly one realised market row for {target.isoformat()}, got {len(row)}")
    realised = float(row.iloc[0]["reference_market_price_gbp_mwh"])

    score = score_precommitted_prediction(
        prediction=prediction,
        realised_price_gbp_mwh=realised,
    )
    score["prediction_path"] = prediction_path.as_posix()
    score["prediction_sha256"] = sha256(prediction_path)
    score["scoring_completed_utc"] = datetime.now(timezone.utc).isoformat()
    score["maturity_preflight"] = maturity

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(score, indent=2) + "\n", encoding="utf-8")
    provenance = {
        "schema": "gb-power-market-v27-precommitted-outcome-score-provenance-v1",
        "prediction_path": prediction_path.as_posix(),
        "prediction_sha256": sha256(prediction_path),
        "reference_market_path": reference_path.as_posix(),
        "reference_market_sha256": sha256(reference_path),
        "score_path": out.as_posix(),
        "score_sha256": sha256(out),
        "target_start_utc": prediction["target_start_utc"],
        "target_outcome_accessed_only_after_maturity_gate": True,
        "prediction_recomputed_during_scoring": False,
        "promotion_eligible": False,
        "evidence_class": "SINGLE_PRECOMMITTED_FORWARD_OUTCOME_DESCRIPTIVE_ONLY",
    }
    provenance_path.write_text(json.dumps(provenance, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"score": score, "provenance": provenance}, indent=2))


if __name__ == "__main__":
    main()
