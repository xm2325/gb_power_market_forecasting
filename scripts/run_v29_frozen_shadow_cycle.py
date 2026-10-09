#!/usr/bin/env python3
"""One new 2h frozen-coefficient prospective cycle; independent of v0.28."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess

import pandas as pd

from gb_power_market.frozen_shadow_v29 import (
    PREDICTION_SCHEMA, SCORE_SCHEMA, load_unchanged_state,
    predict_frozen_shadow, score_frozen_shadow, summary,
)
from gb_power_market.prospective_v28 import (
    canonical_reference, iso, sha256_file, utc, write_json_new,
)


def first_commit_before_target(prediction_path: Path, target: pd.Timestamp) -> bool:
    # The record must have been Git committed before the period start. No
    # retrospective re-creation is eligible for prospective scoring.
    result = subprocess.run(
        ["git", "log", "--diff-filter=A", "--follow", "--format=%cI", "--", str(prediction_path)],
        capture_output=True, text=True, check=True,
    )
    stamps = [utc(value) for value in result.stdout.splitlines() if value.strip()]
    return bool(stamps) and all(stamp < target for stamp in stamps)


def execute(
    *, reference_path: Path, neso_path: Path, state_path: Path,
    input_end: pd.Timestamp, out_dir: Path, now: pd.Timestamp,
    manifest_elexon: Path | None = None, manifest_neso: Path | None = None,
) -> dict:
    state = load_unchanged_state(state_path)
    reference = canonical_reference(pd.read_parquet(reference_path))
    neso = pd.read_parquet(neso_path)
    price_by_time = dict(zip(
        reference["target_start_utc"], reference["reference_market_price_gbp_mwh"], strict=True,
    ))
    pred_dir = out_dir / "predictions"
    score_dir = out_dir / "scores"
    sources = {
        "elexon_snapshot_sha256": sha256_file(reference_path),
        "neso_snapshot_sha256": sha256_file(neso_path),
        "elexon_manifest_sha256": sha256_file(manifest_elexon) if manifest_elexon else None,
        "neso_manifest_sha256": sha256_file(manifest_neso) if manifest_neso else None,
    }

    newly_scored, pending, blocked = [], [], []
    for pred_path in sorted(pred_dir.glob("*.json")):
        forecast = json.loads(pred_path.read_text(encoding="utf-8"))
        target = utc(forecast["target_start_utc"])
        score_path = score_dir / pred_path.name
        if score_path.exists():
            continue
        if forecast.get("schema") != PREDICTION_SCHEMA or not first_commit_before_target(pred_path, target):
            blocked.append({"target": iso(target), "reason": "NOT_COMMITTED_BEFORE_TARGET"})
            continue
        if now < target + pd.Timedelta(minutes=120) or target not in price_by_time:
            pending.append(iso(target))
            continue
        score = score_frozen_shadow(
            forecast, price=float(price_by_time[target]), scoring_at=now,
        )
        score["prediction_verified_pretarget"] = True
        score["prediction_sha256"] = sha256_file(pred_path)
        score["source"] = sources
        write_json_new(score_path, score)
        newly_scored.append(iso(target))

    scored_rows = []
    for path in sorted(score_dir.glob("*.json")):
        row = json.loads(path.read_text(encoding="utf-8"))
        if row.get("schema") == SCORE_SCHEMA and row.get("prediction_verified_pretarget"):
            scored_rows.append(row)

    new_prediction = None
    prediction_state = "NOT_ATTEMPTED"
    try:
        forecast = predict_frozen_shadow(
            reference, neso, state, decision=now,
            input_end_exclusive=input_end, scored_history=scored_rows,
        )
        target = utc(forecast["target_start_utc"])
        path = pred_dir / (target.strftime("%Y%m%dT%H%MZ") + ".json")
        if path.exists():
            prediction_state = "TARGET_ALREADY_FROZEN"
        else:
            forecast["freeze_completed_utc"] = iso(pd.Timestamp(datetime.now(timezone.utc)))
            forecast["source"] = sources
            forecast["code_commit_sha"] = os.environ.get("GITHUB_SHA", "LOCAL_NON_FORWARD")
            forecast["github_run_id"] = os.environ.get("GITHUB_RUN_ID")
            write_json_new(path, forecast)
            new_prediction = str(path)
            prediction_state = "NEW_PRETARGET_PREDICTION_AWAITING_PUSH"
    except ValueError as exc:
        prediction_state = "BLOCKED_FAIL_CLOSED: " + str(exc)

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "latest.json").write_text(
        json.dumps(summary(scored_rows), indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    run = {
        "schema": PREDICTION_SCHEMA,
        "run_at_utc": iso(now),
        "new_prediction_path": new_prediction,
        "prediction_state": prediction_state,
        "new_scores": newly_scored,
        "pending_scores": pending,
        "blocked_scores": blocked,
        "source": sources,
        "scored_rows": len(scored_rows),
        "automatic_promotion": False,
    }
    write_json_new(
        out_dir / "runs" / pd.Timestamp.now(tz="UTC").strftime("%Y%m%dT%H%M%S%fZ.json"),
        run,
    )
    return run


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reference-market", type=Path, required=True)
    ap.add_argument("--neso-current", type=Path, required=True)
    ap.add_argument("--model-state", type=Path, default=Path("reports/locked/V0_21_FROZEN_MODEL_STATE.json"))
    ap.add_argument("--input-end-exclusive-utc", required=True)
    ap.add_argument("--elexon-manifest", type=Path)
    ap.add_argument("--neso-manifest", type=Path)
    ap.add_argument("--out-dir", type=Path, default=Path("reports/forward/v29"))
    ap.add_argument("--run-state", type=Path, default=Path(".v29_run_state.json"))
    args = ap.parse_args()
    result = execute(
        reference_path=args.reference_market,
        neso_path=args.neso_current,
        state_path=args.model_state,
        input_end=utc(args.input_end_exclusive_utc),
        out_dir=args.out_dir,
        now=pd.Timestamp(datetime.now(timezone.utc)),
        manifest_elexon=args.elexon_manifest,
        manifest_neso=args.neso_manifest,
    )
    args.run_state.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
