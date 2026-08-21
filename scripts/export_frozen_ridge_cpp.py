#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from gb_power_market.compiled_export import serialise_frozen_ridge_text


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model-state", default="reports/locked/V0_21_FROZEN_MODEL_STATE.json")
    ap.add_argument("--horizon", default="2h", choices=("30m", "2h", "6h", "12h"))
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    payload = json.loads(Path(args.model_state).read_text(encoding="utf-8"))
    state = payload["states"][args.horizon]
    text = serialise_frozen_ridge_text(state)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    print(json.dumps({
        "horizon": args.horizon,
        "features": len(state["features"]),
        "selected_family": state["selected_family"],
        "output": str(out),
    }, indent=2))


if __name__ == "__main__":
    main()
