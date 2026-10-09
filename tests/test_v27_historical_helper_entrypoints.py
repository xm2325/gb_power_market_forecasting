from __future__ import annotations

import subprocess
import sys


def _help(path: str) -> None:
    proc = subprocess.run(
        [sys.executable, path, '--help'],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert 'usage:' in proc.stdout.lower()


def test_legacy_neso_downloader_executes_as_script() -> None:
    _help('scripts/download_neso_legacy_walkforward.py')


def test_neso_walkforward_materialiser_executes_as_script() -> None:
    _help('scripts/materialise_neso_walkforward.py')


def test_corrected_historical_runner_executes_as_script() -> None:
    _help('scripts/run_v27_historical_walkforward_v2.py')
