import shutil
from pathlib import Path

from scripts.update_readme_v26_status import update_readme


REGISTRY = Path("reports/monitoring/V0_26_FORWARD_SNAPSHOT_REGISTRY.json")


def test_update_readme_uses_latest_locked_v26_snapshot(tmp_path: Path) -> None:
    readme = tmp_path / "README.md"
    shutil.copyfile("README.md", readme)

    updated = update_readme(readme_path=readme, registry_path=REGISTRY)

    assert "### Latest locked forward snapshot — sequence 2" in updated
    assert "**23 genuine forward half-hours**" in updated
    assert "**7.623**" in updated
    assert "**7.569**" in updated
    assert "9.219" in updated
    assert "18.799" in updated
    assert "`32632409230`" in updated
    assert "487f1e33478f9c07a25b088b1297d8aa170db9959642e108388bebd613765ca2" in updated
    assert "## Earlier prospective/blinding experiments" in updated


def test_update_readme_is_idempotent(tmp_path: Path) -> None:
    readme = tmp_path / "README.md"
    shutil.copyfile("README.md", readme)

    first = update_readme(readme_path=readme, registry_path=REGISTRY)
    second = update_readme(readme_path=readme, registry_path=REGISTRY)

    assert second == first
    assert second.count("## v0.26 — causal 6h/48h consensus-clipped 2h adaptation") == 1
    assert second.count("## Earlier prospective/blinding experiments") == 1
