from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import pandas as pd


def test_filter_neso_asof_removes_post_decision_publications(tmp_path: Path) -> None:
    src = tmp_path / "source.parquet"
    out = tmp_path / "asof.parquet"
    manifest = tmp_path / "manifest.json"
    pd.DataFrame(
        {
            "target_end_utc": pd.to_datetime(["2026-08-25T12:30:00Z"] * 3, utc=True),
            "publish_time_utc": pd.to_datetime(
                ["2026-08-25T09:00:00Z", "2026-08-25T10:00:00Z", "2026-08-25T10:00:01Z"],
                utc=True,
            ),
            "wind_mw": [1.0, 2.0, 3.0],
        }
    ).to_parquet(src, index=False)

    subprocess.run(
        [
            sys.executable,
            "scripts/filter_neso_asof.py",
            "--input",
            str(src),
            "--cutoff-utc",
            "2026-08-25T10:00:00Z",
            "--out",
            str(out),
            "--manifest",
            str(manifest),
        ],
        check=True,
    )

    filtered = pd.read_parquet(out)
    audit = json.loads(manifest.read_text(encoding="utf-8"))
    assert len(filtered) == 2
    assert pd.to_datetime(filtered["publish_time_utc"], utc=True).max() == pd.Timestamp("2026-08-25T10:00:00Z")
    assert audit["source_rows"] == 3
    assert audit["kept_rows"] == 2
    assert audit["removed_post_cutoff_rows"] == 1
    assert pd.Timestamp(audit["max_kept_publish_time_utc"]) <= pd.Timestamp(audit["cutoff_utc"])
