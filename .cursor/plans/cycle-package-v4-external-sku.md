# Cycle package v4 + external SKU

## Goal
Seal every 15m cycle with book, tape, underlying, rich market meta, volume path, quality footer; tag proprietary members for post-hoc external export; keep Drive upload on seal.

## Steps
1. cycle_packager schema v4: enrich market_meta, volume_path.csv, quality.json, proprietary_members in meta
2. export_cycle_package_variant (full → external)
3. Loader + tests + docs; confirm gdrive hook unchanged

## Done when
- New seals are schema_version 4 with required members
- External export strips strike_table + metrics_ring only
- Unit tests pass

## Status
- [x] cycle_packager v4 + cycle_package_members helpers
- [x] export_cycle_package_variant.py CLI
- [x] loader / docs / unit tests
- Drive hook unchanged (post `package_due_cycles`)
