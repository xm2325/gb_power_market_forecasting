from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from scripts.ingest_v20_github_artifact import safe_extract


def test_safe_extract_rejects_path_traversal(tmp_path):
    z = tmp_path / "bad.zip"
    with zipfile.ZipFile(z, "w") as f:
        f.writestr("../escape.txt", "bad")
    with pytest.raises(ValueError):
        safe_extract(z, tmp_path / "out")


def test_safe_extract_accepts_normal_artifact(tmp_path):
    z = tmp_path / "ok.zip"
    with zipfile.ZipFile(z, "w") as f:
        f.writestr("reports/v19_real_market/a.json", "{}")
    out = tmp_path / "out"
    safe_extract(z, out)
    assert (out / "reports/v19_real_market/a.json").exists()
