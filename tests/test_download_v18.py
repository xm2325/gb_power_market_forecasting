from __future__ import annotations
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('v18_download', ROOT / 'scripts' / 'download_neso_v18_bundle.py')
MOD = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MOD
assert SPEC.loader is not None
SPEC.loader.exec_module(MOD)


def test_immutable_snapshot_requires_exact_total():
    assert MOD.snapshot_consistent(live=False, before=100, downloaded=100, after=100)
    assert not MOD.snapshot_consistent(live=False, before=100, downloaded=99, after=100)


def test_live_snapshot_may_grow_during_download_but_not_shrink():
    assert MOD.snapshot_consistent(live=True, before=100, downloaded=103, after=105)
    assert not MOD.snapshot_consistent(live=True, before=100, downloaded=99, after=105)
    assert not MOD.snapshot_consistent(live=True, before=105, downloaded=104, after=100)
