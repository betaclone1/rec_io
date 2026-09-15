# Position Risk Engine — Stage 1 (observe-only)

**Status:** Local Stage 1 implemented. Not for production.  
**Alignment:** `.cursor/plans/ats-auto-stop-modernization-alignment.md`, `.cursor/plans/position-risk-engine-stage1.md`

## Safety statement

- **`active_trade_supervisor` remains the sole stop / close authority.**
- This process is **observe-only**: no `EXIT_INTENT`, no TM close commands, no Kalshi order place/cancel.
- **Default OFF.** Requires `REC_ENABLE_POSITION_RISK_ENGINE=1` and `REC_POSITION_RISK_MODE=observe`.
- **Hard-disabled on production** with **no escape hatch** (`REC_IS_PRODUCTION=1`, project root / cwd under `/opt/rec_io_server`, or known prod DB/SSH host markers). Obsolete allow-prod env vars are ignored. Includes supervisord autostart generation.
- Do **not** deploy, enable on prod, commit-enable, or wire to the executor.

## Local start / stop

```bash
# From repo root
export REC_ENABLE_POSITION_RISK_ENGINE=1
export REC_POSITION_RISK_MODE=observe
export REC_POSITION_RISK_STATUS_PATH=backend/data/position_risk/status.json
# Ensure DB_HOST is local, not prod
PYTHONPATH=. .venv/bin/python backend/position_risk_engine.py
# Stop: SIGINT/SIGTERM
```

Status JSON (all enrolled open HWS positions, leases, health, shadow features, latency):

```bash
PYTHONPATH=. .venv/bin/python scripts/position_risk/cli.py status
PYTHONPATH=. .venv/bin/python scripts/position_risk/cli.py enroll-scan
```

Supervisord: program `position_risk_engine` is generated with **autostart=false** unless `REC_ENABLE_POSITION_RISK_ENGINE=1` at generate time **and** not production. Prefer manual CLI for Stage 1 testing.

## Fixtures and provenance

Authoritative trade rows: `~/Downloads/10058_full_09_07.csv` (monitor 10058 export).  
Extracted rows: `tests/fixtures/position_risk/historical/10058_rows_59597_59721_59863.csv`  
Manifest (paths + sha256): `tests/fixtures/position_risk/manifest.json`

| ID | Role | L2 | Public tape |
|----|------|----|-------------|
| 59597 | gradual_loss | RESOLVED (local `.tar.xz` hashed) | UNKNOWN (no cache) |
| 59721 | flash_loss | RESOLVED | UNKNOWN |
| 59863 | supplemental | SUPPLEMENTAL L2 | UNKNOWN |
| 59860/59847/59838/59835 | win_control | RESOLVED | UNKNOWN |

**Synthetic scenarios (not those trade IDs):**

- `tests/fixtures/position_risk/synthetic/gradual_collapse_reference_v1.json`
- `tests/fixtures/position_risk/synthetic/flash_collapse_reference_v1.json`

```bash
PYTHONPATH=. .venv/bin/python scripts/position_risk/cli.py write-fixtures
PYTHONPATH=. .venv/bin/python scripts/position_risk/cli.py replay-synthetic \
  --path tests/fixtures/position_risk/synthetic/gradual_collapse_reference_v1.json
PYTHONPATH=. .venv/bin/python scripts/position_risk/cli.py replay-historical --trade-id 59597
```

Local `users_*` trade id space may differ from the 10058 CSV — join historical fixtures by **ticker + timestamps + package hash**, not by assuming local DB `id` equality.

## Tests

```bash
PYTHONPATH=. .venv/bin/python -m pytest tests/unit/position_risk/ -q
```

Coverage includes: safety gates, quiet vs stale book, seq gap, tape UNKNOWN, synthetic timelines, persistence grid (analysis-only), lease re-enroll, watchdog uncovered, provenance naming, no executor path in engine source.

## Stage 1 scope exclusions

Public-trade WS ingest, durable risk Redis Stream, exit coordinator, flip-sell, money authority, hourly markets.

## Stage 2 (local)

See `docs/POSITION_RISK_ENGINE_STAGE2_LOCAL.md` for ATS consume, paper arming env vars, HWS controls, and audit UI.
