import json
from pathlib import Path
import re


def test_repository_version_matches_pyproject_and_lock_state() -> None:
    version = Path("VERSION").read_text(encoding="utf-8").strip()
    pyproject = Path("pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'^version\s*=\s*"([^"]+)"$', pyproject, flags=re.MULTILINE)
    assert match is not None
    assert version == match.group(1)

    implementation_lock = Path("reports/locked/V0_27_IMPLEMENTATION_LOCK.json")
    if implementation_lock.is_file():
        lock = json.loads(implementation_lock.read_text(encoding="utf-8"))
        assert lock["schema"] == "gb-power-market-v27-forward-implementation-lock-v1"
        assert lock["status"] == "FRESH_FORWARD_CANDIDATE_LOCKED_NOT_YET_EVALUATED"
        assert version == lock["version"] == "0.27.0"
    else:
        assert version == "0.26.0"
