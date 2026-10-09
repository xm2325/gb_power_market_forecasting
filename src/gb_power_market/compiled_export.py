from __future__ import annotations

from typing import Any

import numpy as np


def serialise_frozen_ridge_text(state: dict[str, Any]) -> str:
    """Serialise a validated frozen ridge state for the tiny C++17 inference kernel."""
    if state.get("schema") != "gb-power-market-frozen-ridge-v1":
        raise ValueError("unsupported frozen ridge schema")

    features = list(state["features"])
    mean = np.asarray(state["mean"], dtype=float)
    scale = np.asarray(state["scale"], dtype=float)
    coef = np.asarray(state["coef"], dtype=float)
    n = len(features)
    if n == 0 or len(mean) != n or len(scale) != n or len(coef) != n + 1:
        raise ValueError("invalid frozen ridge dimensions")
    if not np.isfinite(mean).all() or not np.isfinite(scale).all() or not np.isfinite(coef).all():
        raise ValueError("frozen ridge state must be finite")
    if (scale <= 0).any():
        raise ValueError("frozen ridge scale must be positive")

    def line(values: np.ndarray) -> str:
        return " ".join(format(float(v), ".17g") for v in values)

    return f"{n}\n{line(mean)}\n{line(scale)}\n{line(coef)}\n"
