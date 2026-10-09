import json
import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest

from gb_power_market.compiled_export import serialise_frozen_ridge_text
from gb_power_market.prospective_v21 import model_from_frozen_state


GXX = shutil.which("g++")


@pytest.mark.skipif(GXX is None, reason="g++ not installed")
def test_cpp17_kernel_matches_locked_python_2h_predictions(tmp_path: Path):
    payload = json.loads(Path("reports/locked/V0_21_FROZEN_MODEL_STATE.json").read_text())
    state = payload["states"]["2h"]

    model_path = tmp_path / "model.txt"
    model_path.write_text(serialise_frozen_ridge_text(state), encoding="utf-8")
    binary = tmp_path / "frozen_ridge_infer"
    subprocess.run(
        [GXX, "-std=c++17", "-O3", "-Wall", "-Wextra", "-Wpedantic", "cpp/frozen_ridge_infer.cpp", "-o", str(binary)],
        check=True,
        capture_output=True,
        text=True,
    )

    mean = np.asarray(state["mean"], dtype=float)
    scale = np.asarray(state["scale"], dtype=float)
    rng = np.random.default_rng(20260821)
    x = mean + rng.normal(size=(128, len(mean))) * scale
    python_pred = model_from_frozen_state(state).predict(x)

    rows = "\n".join(",".join(format(float(v), ".17g") for v in row) for row in x) + "\n"
    result = subprocess.run(
        [str(binary), str(model_path)],
        input=rows,
        check=True,
        capture_output=True,
        text=True,
    )
    cpp_pred = np.asarray([float(v) for v in result.stdout.splitlines()], dtype=float)
    assert len(cpp_pred) == len(python_pred)
    np.testing.assert_allclose(cpp_pred, python_pred, rtol=0.0, atol=1e-10)


@pytest.mark.skipif(GXX is None, reason="g++ not installed")
def test_cpp17_kernel_fails_closed_on_wrong_feature_width(tmp_path: Path):
    payload = json.loads(Path("reports/locked/V0_21_FROZEN_MODEL_STATE.json").read_text())
    state = payload["states"]["2h"]
    model_path = tmp_path / "model.txt"
    model_path.write_text(serialise_frozen_ridge_text(state), encoding="utf-8")
    binary = tmp_path / "frozen_ridge_infer"
    subprocess.run(
        [GXX, "-std=c++17", "-O2", "cpp/frozen_ridge_infer.cpp", "-o", str(binary)],
        check=True,
        capture_output=True,
        text=True,
    )

    result = subprocess.run(
        [str(binary), str(model_path)],
        input="1.0,2.0\n",
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "wrong width" in result.stderr or "expected" in result.stderr


def test_compiled_export_rejects_invalid_dimensions():
    bad = {
        "schema": "gb-power-market-frozen-ridge-v1",
        "features": ["a", "b"],
        "mean": [0.0],
        "scale": [1.0, 1.0],
        "coef": [0.0, 1.0, 2.0],
    }
    with pytest.raises(ValueError, match="dimensions"):
        serialise_frozen_ridge_text(bad)
