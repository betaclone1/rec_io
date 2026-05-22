# Pre-deployment check — Kalshi ingest / live_state refactor

**Date:** 2026-05-22  
**Scope:** Staged local changes (82 files) vs production (`165.22.13.146`, commit `51c69da`)  
**Push:** Not performed (audit only)

---

## Verdict

| Area | Status |
|------|--------|
| **Migrations in git** | Was **blocked** — two required pairs were missing from the repo; **restored locally** during this audit (see below). Still need to be **staged and committed** with the deploy. |
| **Production DB vs staged code** | **Blocked until** `20260517_1500` is applied on prod (triggers still active). `20260515_1430` already applied on prod. |
| **Unit tests (refactor)** | **Pass** (22 tests) |
| **Local schema drift** | **OK** (`check_db_schema_drift.py`) |
| **CI tenant touch** | **OK** |
| **Supervisor / deploy shape** | **Breaking change** — dual watchdog → single `market_watchdog_ws_kalshi`; requires `MASTER_RESTART` + config regen |
| **Commit hygiene** | **Review** — large sandbox `.jsonl` files are staged; exclude from production commit |

---

## Migration audit (critical)

### Required for this deploy

| Migration ID | In git (before audit) | Local DB | Prod DB | Prod disk (`/opt/rec_io_server`) | Staged code depends on it |
|----------------|----------------------|----------|---------|----------------------------------|---------------------------|
| `20260515_1430_live_data_strike_tables_fair_price` | **Missing** | Applied | Applied | Untracked files only | Yes — `fair_price` on strike tables |
| `20260517_1500_live_symbol_status_lp_only_drop_price_sync` | **Missing** | Applied | **Not applied** | **Missing** | Yes — drops PG tick sync; AES/tradeflow use `live_state` |

**Restored during audit (workspace only, not pushed):**

- `scripts/migrations/20260515_1430_live_data_strike_tables_fair_price.{up,down}.sql` (copied from prod)
- `scripts/migrations/20260517_1500_live_symbol_status_lp_only_drop_price_sync.{up,down}.sql` (recovered from session transcript)

### Prod verification (2026-05-22)

- `live_data.strike_table_15m.fair_price` — **exists**
- `sync_live_symbol_status_btc_from_price_log` on `live_price_log_1s_btc` — **still exists** (20260517 not run)

### Other migrations applied locally but absent from git (historical)

These were already in `system.schema_migrations` on local before this refactor; not introduced by staged code. Confirm prod state separately if needed:

- `20260310_*` (trade history preferences renames)
- `20260312_1000_kalshi_fills_settlements_dollars`
- `20260318_2000_testing_redis_basic_test_create`
- `20260510_1200_trades_simulated_market_result` (superseded on prod by `20260510_1215` drop — local may still list both)

### Staged diff and migrations

- **No new migration files** were part of the original staged set.
- Staged `database.py` / `MASTER_DB_SCHEMA_REFERENCE.md` **reference** `20260517_1500` without shipping the SQL — that gap caused the deploy risk.

---

## Production deploy checklist (when you push)

1. **Commit** restored migration pairs + staged refactor (exclude soak `.jsonl` unless intentional).
2. **On prod after pull:**
   ```bash
   cd /opt/rec_io_server
   venv/bin/python3 scripts/db/run_migration.py up 20260517_1500_live_symbol_status_lp_only_drop_price_sync
   ```
   (`20260515_1430` should no-op if already applied.)
3. **`bash scripts/MASTER_RESTART.sh`** — regenerates supervisor (single `market_watchdog_ws_kalshi --market all`).
4. **Verify:** health :3000 / :8001, supervisor all `RUNNING`, `market_watchdog_ws_kalshi` (one process), no fresh errors in watchdog / strike / AES logs.
5. **Optional:** `./scripts/prod/prod_cpu_ram_audit.sh` — compare to `docs/perf-audits/PROD_CPU_RAM_BASELINE_PRE_KALSHI_INGEST_REFACTOR_2026-05-22.md`.

---

## Code / config checks

| Check | Result |
|-------|--------|
| `check_db_schema_drift.py` (local) | OK |
| `scripts/ci/check_global_tenant_touch.py` | OK |
| Unit tests (live_state, tradeflow, contract label, expiration) | 22 passed |
| New DDL in staged diff | None (only `database.py` init comment/trigger removal aligned with 20260517) |
| Deleted modules | `market_watchdog.py`, `kalshi_live_orderbook_sidecar.py` — ensure nothing still imports them on prod |
| Supervisor generator | **Single** `market_watchdog_ws_kalshi` with `--market all` + `LIVE_STATE_CACHE_ENABLED=1` |
| Doc drift | `docs/KALSHI_MARKET_INGEST.md` still documents **dual** watchdog programs; update to match generator before/after deploy |

---

## Staged commit hygiene

**Do not ship to prod without review:**

| Path | Issue |
|------|--------|
| `scripts/sandbox/kalshi_market_feed/*.jsonl` | Large soak/event logs (~800k+ lines in diff stat) |
| `scripts/sandbox/kalshi_market_feed/kalshi_market_ws_master.py` | Dev/sandbox only — OK in repo, optional for prod runtime |

**Suggested:** unstage `.jsonl` files; keep `CHECKPOINT_WS_ROLLOVER_BASELINE.md` and code references if useful.

---

## Environment / runtime (prod today vs after deploy)

| Item | Prod now | After deploy |
|------|----------|----------------|
| Watchdog processes | `market_watchdog_ws_kalshi_15m` + `_hourly` | One `market_watchdog_ws_kalshi` |
| Orderbook path | Legacy sidecar + PG options possible | Redis `live_state` / `trade_monitor:orderbook_levels:v1:*` only |
| `live_symbol_status` tick mirror | PG triggers **on** | Triggers **off** (after 20260517 `up`) |
| `trade_manager` expiry guard | Old (expires at :00 without wall-clock check) | Fixed in staged `trade_manager.py` |

---

## Git state at audit time

- **Branch:** `main` (staged changes, not committed)
- **Base commit:** `51c69da` (matches prod HEAD)
- **Staged files:** 82
- **Nothing pushed** per request

---

## Summary

Your instinct was right: **migration SQL for `20260515` and `20260517` was missing from the git tree** even though local (and prod for 20260515) databases had been migrated. Deploying only the staged application code without committing those files and running **`20260517` on production** would leave prod with **live PG tick triggers** while new code assumes **Redis `live_state` only** — a serious behavioral mismatch.

After staging the restored migration files and running `20260517` on prod during deploy, the schema and code paths align. Treat **supervisor consolidation** and **MASTER_RESTART** as mandatory, not optional.
