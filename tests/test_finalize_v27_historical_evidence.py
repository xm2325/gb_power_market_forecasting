from __future__ import annotations

from pathlib import Path

from scripts.finalize_v27_historical_evidence import (
    EVIDENCE_CLASS,
    LOCK_STATUS,
    README_END,
    README_START,
    build_manifest,
    render_readme_section,
    update_readme_text,
)


def test_manifest_pins_complete_historical_scope_and_negative_v26_comparison() -> None:
    manifest = build_manifest(Path('.'))
    assert manifest['status'] == LOCK_STATUS
    assert manifest['evidence_class'] == EVIDENCE_CLASS
    assert manifest['scope']['rows'] == 5516
    assert manifest['scope']['start_utc'] == '2026-05-01T00:00:00+00:00'
    assert manifest['scope']['end_exclusive_utc'] == '2026-08-23T22:00:00+00:00'
    assert abs(manifest['headline_metrics']['v0.27_mae_gbp_mwh'] - 18.578152729094757) < 1e-9
    assert abs(manifest['headline_metrics']['v0.26_mae_gbp_mwh'] - 18.380394170256366) < 1e-9
    assert manifest['headline_metrics']['v0.27_improvement_vs_causal_base_pct'] > 0
    assert manifest['headline_metrics']['v0.27_improvement_vs_v0.26_pct'] < 0
    assert manifest['weekly_consistency']['causal_base']['v27_better_folds'] == 12
    assert manifest['weekly_consistency']['v0.26']['v27_better_folds'] == 7
    assert manifest['automatic_promotion'] is False
    assert manifest['automatic_model_change'] is False
    assert manifest['retuning_authorized'] is False
    for entry in manifest['files'].values():
        assert len(entry['sha256']) == 64
        assert len(entry['git_blob_sha1']) == 40
        assert entry['bytes'] > 0


def test_readme_section_states_uncertainty_and_no_v27_overclaim() -> None:
    section = render_readme_section(build_manifest(Path('.')))
    assert '5,516 contiguous half-hours' in section
    assert 'HISTORICAL_ASOF_ROLLING_ORIGIN_NOT_LIVE_FORWARD' in section
    assert '18.578' in section
    assert '18.380' in section
    assert 'does **not** claim that v0.27 historically dominates v0.26' in section
    assert '12/17' in section
    assert '7/17' in section
    assert README_START in section and README_END in section


def test_readme_update_is_idempotent() -> None:
    section = 'START\ncontrolled section\nEND'
    source = '# title\n\n## Repository layout\nbody\n'
    first = update_readme_text(source, section)
    assert section in first
    # Exercise the real marker replacement path separately.
    marked = '# title\n\n' + README_START + '\nold\n' + README_END + '\n\n## Repository layout\nbody\n'
    replacement = README_START + '\nnew\n' + README_END
    second = update_readme_text(marked, replacement)
    third = update_readme_text(second, replacement)
    assert second == third
    assert '\nold\n' not in second
