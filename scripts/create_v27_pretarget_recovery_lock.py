#!/usr/bin/env python3
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path

from gb_power_market.v27_pretarget_recovery import build_pretarget_recovery_lock


IMPLEMENTATION = Path("reports/locked/V0_27_IMPLEMENTATION_LOCK.json")
MISS = Path("reports/forward/v27/V0_27_FIRST_PRETARGET_FREEZE_MISSED.json")
OUT = Path("reports/forward/v27/V0_27_PRETARGET_RECOVERY_LOCK.json")
FORBIDDEN_RETRO = Path("reports/forward/v27/V0_27_FIRST_FORWARD_PREDICTION_2026-08-25_0230Z.json")


def main() -> None:
    if OUT.exists():
        raise SystemExit("v0.27 pre-target recovery lock already exists; refusing rewrite")
    if FORBIDDEN_RETRO.exists():
        raise SystemExit("retrospective 02:30 prediction exists; refusing recovery lock")

    implementation = json.loads(IMPLEMENTATION.read_text(encoding="utf-8"))
    miss = json.loads(MISS.read_text(encoding="utf-8"))
    payload = build_pretarget_recovery_lock(
        implementation_lock=implementation,
        miss_record=miss,
        recovery_lock_timestamp_utc=datetime.now(timezone.utc),
    )
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
