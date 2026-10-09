from __future__ import annotations

import tomllib
from pathlib import Path


def test_duckdb_timezone_runtime_dependency_is_declared():
    cfg = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    live = cfg["project"]["optional-dependencies"]["live"]
    names = {spec.split(">=")[0].split("==")[0].strip() for spec in live}
    assert "duckdb" in names
    assert "pytz" in names
