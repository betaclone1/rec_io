# Stage 1 — `position_risk_engine` observe-only (local)

**Goal:** Local observe-only HWS protection instrumentation for all tenants; zero money authority; ATS remains sole stop authority.  
**Status:** done (local Stage 1)  
**Alignment:** `.cursor/plans/ats-auto-stop-modernization-alignment.md` (Stage 0 complete)  
**Hard safety:** No production deploy, no prod config mutation, no commits/pushes, no order place/cancel, no TE/TM exit path wiring. Default OFF; prod hard-disabled.

## Fixture provenance (corrected)

- Authoritative rows: `~/Downloads/10058_full_09_07.csv` (monitor 10058).
- Extract: `tests/fixtures/position_risk/historical/10058_rows_59597_59721_59863.csv`
- Manifest: `tests/fixtures/position_risk/manifest.json`
- 59597/59721: **RESOLVED_L2** (local `.tar.xz` sha256 verified); public tape **UNKNOWN**
- 59863: **SUPPLEMENTAL** L2; tape UNKNOWN
- Synthetic: `gradual_collapse_reference_v1` / `flash_collapse_reference_v1` — **not** named as those trades
- Win controls: 59860, 59847, 59838, 59835 with hashed packages

## Completion criteria

- [x] Fixture manifest with provenance
- [x] Tests pass (`tests/unit/position_risk/`)
- [x] Local CLI status + synthetic/historical replay
- [x] Docs `docs/POSITION_RISK_ENGINE_STAGE1.md`
- [x] Proof: no executor/cancel/TM command needles in PRE modules; default observe; prod disabled

## Out of scope (Stage 1)

EXIT_INTENT, flip-sell, public-trade WS ingest, durable risk Redis Stream (Stage 2), money authority, production enablement.
