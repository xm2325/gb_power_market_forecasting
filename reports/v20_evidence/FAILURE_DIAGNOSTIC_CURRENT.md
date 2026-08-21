# v0.20 failure diagnostic

## Global blockers

- Elexon coverage audit is missing or not PASS_REAL
- missing provenance source: neso_download_manifest
- missing provenance source: neso_materialise_manifest
- missing provenance source: elexon_download_manifest
- missing real_price_benchmark_all.json

## Blocked horizons

- 30m: missing horizon result
- 2h: missing horizon result
- 6h: missing horizon result
- 12h: missing horizon result

## Source inventory

- real_price_benchmark: MISSING — `reports/v19_real_market/real_price_benchmark_all.json`
- elexon_coverage_audit: MISSING — `reports/v19_real_market/elexon_coverage_audit.json`
- neso_physical_benchmark: MISSING — `reports/v19_real_market/neso_physical_benchmark/real_neso_asof_benchmark.json`
- neso_download_manifest: MISSING — `reports/v19_real_market/neso_download_manifest.json`
- neso_materialise_manifest: MISSING — `reports/v19_real_market/neso_materialise_manifest.json`
- elexon_download_manifest: MISSING — `reports/v19_real_market/elexon_download_manifest.json`
