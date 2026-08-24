from pathlib import Path


WORKFLOW = Path(".github/workflows/validate-v27-development.yml")


def test_v27_validation_maturity_gate_precedes_all_market_data_downloads() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    gate = text.index("Fail closed until the full sealed validation block is mature")
    neso = text.index("Download bounded NESO vintages needed for causal replay")
    elexon = text.index("Download Elexon MID with exact sealed end boundary")

    assert gate < neso < elexon
    assert "SEALED_VALIDATION_NOT_MATURE" in text


def test_v27_validation_uses_exact_elexon_end_and_no_auto_forward() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")

    assert "scripts/download_elexon_mid_exact_window.py" in text
    assert "--end-exclusive-utc 2026-08-24T22:00:00Z" in text
    assert "validation['automatic_forward_launch'] is not False" in text
    assert "INDEPENDENT_DEVELOPMENT_VALIDATION_NOT_FORWARD_EVIDENCE" in text
