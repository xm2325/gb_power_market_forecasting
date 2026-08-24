import json
import shutil
from pathlib import Path

from scripts.update_readme_v26_status import update_readme


REGISTRY = Path("reports/monitoring/V0_26_FORWARD_SNAPSHOT_REGISTRY.json")


def _latest_locked_evidence() -> tuple[dict, dict]:
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    latest = registry["snapshots"][-1]
    checkpoint = json.loads(Path(latest["checkpoint_path"]).read_text(encoding="utf-8"))
    return latest, checkpoint


def test_update_readme_uses_latest_locked_v26_snapshot(tmp_path: Path) -> None:
    readme = tmp_path / "README.md"
    shutil.copyfile("README.md", readme)
    latest, checkpoint = _latest_locked_evidence()
    forward = checkpoint["forward_segment"]
    monitor = checkpoint["monitor"]

    updated = update_readme(readme_path=readme, registry_path=REGISTRY)

    assert f"### Latest locked forward snapshot — sequence {latest['sequence']}" in updated
    assert f"**{forward['rows']} genuine forward half-hours**" in updated
    assert f"**{forward['candidate_mae_gbp_mwh']:.3f}**" in updated
    assert f"**{forward['frozen_mae_gbp_mwh']:.3f}**" in updated
    assert f"{forward['v25_mae_gbp_mwh']:.3f}" in updated
    assert f"{forward['reference_mae_gbp_mwh']:.3f}" in updated
    assert f"`{latest['run_id']}`" in updated
    assert latest["ledger_chain_tip_sha256"] in updated
    assert f"Alert status: `{monitor['alert_status']}`" in updated
    for alert in monitor.get("alerts", []):
        assert f"`{alert}`" in updated
    assert "## Earlier prospective/blinding experiments" in updated


def test_update_readme_is_idempotent(tmp_path: Path) -> None:
    readme = tmp_path / "README.md"
    shutil.copyfile("README.md", readme)

    first = update_readme(readme_path=readme, registry_path=REGISTRY)
    second = update_readme(readme_path=readme, registry_path=REGISTRY)

    assert second == first
    assert second.count("## v0.26 — causal 6h/48h consensus-clipped 2h adaptation") == 1
    assert second.count("## Earlier prospective/blinding experiments") == 1
