#!/usr/bin/env python3
"""One live cycle: score previously committed predictions, then freeze a new one."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess

import pandas as pd

from gb_power_market.prospective_v28 import (
    SCHEMA, canonical_reference, iso, predict_shadow, score_shadow,
    sha256_file, summarise_scores, utc, write_json_new,
)


def _committed_before_target(path: Path, target: pd.Timestamp) -> bool:
    """Do not score untracked/reconstructed or post-target committed predictions."""
    result = subprocess.run(
        ["git", "log", "-1", "--format=%cI", "--", str(path)],
        capture_output=True, text=True, check=True,
    )
    if not result.stdout.strip():
        return False
    return utc(result.stdout.strip()) < target


def run_cycle(
    *,
    reference_path: Path,
    out_dir: Path,
    input_end_exclusive: pd.Timestamp,
    now: pd.Timestamp,
    minimum_delay_minutes: int,
    download_manifest: Path | None = None,
) -> dict:
    frame = canonical_reference(pd.read_parquet(reference_path))
    if frame.empty or frame["target_start_utc"].max() >= input_end_exclusive:
        raise ValueError("source data are empty or exceed predeclared input cutoff")
    price_by_time = dict(zip(frame["target_start_utc"],
                             frame["reference_market_price_gbp_mwh"], strict=True))
    prediction_dir = out_dir / "predictions"
    score_dir = out_dir / "scores"
    run_dir = out_dir / "runs"
    source = {
        "reference_parquet_sha256": sha256_file(reference_path),
        "download_manifest_sha256": sha256_file(download_manifest) if download_manifest else None,
        "price_input_end_exclusive_utc": iso(input_end_exclusive),
        "source_snapshot_observed_before_prediction": True,
        "source_snapshot_reconstruction_not_used": True,
    }

    newly_scored = []
    pending = []
    blocked = []
    for prediction_path in sorted(prediction_dir.glob("*.json")):
        prediction = json.loads(prediction_path.read_text(encoding="utf-8"))
        target = utc(prediction["target_start_utc"])
        score_path = score_dir / prediction_path.name
        if score_path.exists():
            continue
        if prediction.get("schema") != SCHEMA or not _committed_before_target(prediction_path, target):
            blocked.append({"target": iso(target), "reason": "NOT_COMMITTED_BEFORE_TARGET"})
            continue
        if now < target + pd.Timedelta(minutes=30 + minimum_delay_minutes):
            pending.append(iso(target))
            continue
        if target not in price_by_time:
            pending.append(iso(target))
            continue
        score = score_shadow(
            prediction, observed_price=float(price_by_time[target]),
            scored_at=now, scoring_delay_minutes=minimum_delay_minutes,
        )
        score["prediction_sha256"] = sha256_file(prediction_path)
        score["prediction_path"] = str(prediction_path)
        score["source"] = source
        write_json_new(score_path, score)
        newly_scored.append(iso(target))

    prediction_path_str = None
    prediction_state = "NOT_ATTEMPTED"
    try:
        prediction = predict_shadow(
            frame,
            decision=now,
            input_end_exclusive=input_end_exclusive,
            delay_minutes=minimum_delay_minutes,
        )
        target = utc(prediction["target_start_utc"])
        filename = target.strftime("%Y%m%dT%H%MZ") + ".json"
        target_path = prediction_dir / filename
        if target_path.exists():
            prediction_state = "TARGET_ALREADY_FROZEN"
        else:
            prediction["freeze_completed_utc"] = iso(pd.Timestamp(datetime.now(timezone.utc)))
            prediction["source"] = source
            prediction["code_commit_sha"] = os.environ.get("GITHUB_SHA", "LOCAL_NON_PROSPECTIVE")
            prediction["github_run_id"] = os.environ.get("GITHUB_RUN_ID")
            # GitHub-pushed evidence is required before this record is scored.
            write_json_new(target_path, prediction)
            prediction_path_str = str(target_path)
            prediction_state = "PREDICTION_FILE_CREATED_AWAITING_GIT_PUSH"
    except ValueError as error:
        prediction_state = "BLOCKED_FAIL_CLOSED: " + str(error)

    scores = []
    for path in sorted(score_dir.glob("*.json")):
        obj = json.loads(path.read_text(encoding="utf-8"))
        if obj.get("schema") == SCHEMA:
            scores.append(obj)
    summary = summarise_scores(scores)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "latest.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    run_record = {
        "schema": SCHEMA,
        "run_started_utc": iso(now),
        "run_completed_utc": iso(pd.Timestamp(datetime.now(timezone.utc))),
        "prediction_state": prediction_state,
        "new_prediction_path": prediction_path_str,
        "new_scores": newly_scored,
        "pending_scores": pending,
        "blocked_scores": blocked,
        "source": source,
        "current_scored_rows": summary["all"]["rows"],
        "automatic_promotion": False,
    }
    run_path = run_dir / pd.Timestamp.now(tz="UTC").strftime("%Y%m%dT%H%M%S%fZ.json")
    write_json_new(run_path, run_record)
    return run_record


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reference-market", type=Path, required=True)
    ap.add_argument("--out-dir", type=Path, default=Path("reports/forward/v28"))
    ap.add_argument("--input-end-exclusive-utc", required=True)
    ap.add_argument("--download-manifest", type=Path)
    ap.add_argument("--run-state", type=Path, default=Path(".v28_run_state.json"))
    ap.add_argument("--minimum-delay-minutes", type=int, default=90)
    args = ap.parse_args()
    if args.minimum_delay_minutes < 90:
        raise SystemExit("v0.28 prospective evidence requires >=90 min post-period buffer")
    record = run_cycle(
        reference_path=args.reference_market,
        out_dir=args.out_dir,
        input_end_exclusive=utc(args.input_end_exclusive_utc),
        now=pd.Timestamp(datetime.now(timezone.utc)),
        minimum_delay_minutes=args.minimum_delay_minutes,
        download_manifest=args.download_manifest,
    )
    args.run_state.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(record, indent=2))


if __name__ == "__main__":
    main()
