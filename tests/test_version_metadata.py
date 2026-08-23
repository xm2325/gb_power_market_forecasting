from pathlib import Path
import re


def test_repository_version_matches_pyproject() -> None:
    version = Path("VERSION").read_text(encoding="utf-8").strip()
    pyproject = Path("pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'^version\s*=\s*"([^"]+)"$', pyproject, flags=re.MULTILINE)
    assert match is not None
    assert version == match.group(1)
    assert version == "0.26.0"
