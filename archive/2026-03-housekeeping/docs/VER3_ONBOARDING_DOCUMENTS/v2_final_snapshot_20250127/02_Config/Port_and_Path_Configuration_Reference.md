# Port & Path Configuration Reference – REC.IO v2

## Purpose
Single source of truth for service **ports**, **paths**, and **environment variables** used in REC.IO v2. BMAD agents should treat this as canonical for v2; v3 will inherit and extend it.

---

## Source of Truth Files
- **`/v2_final_snapshot_20250127/02_Config/MASTER_PORT_MANIFEST.json`** – Assigned ports for every service.
- **`/v2_final_snapshot_20250127/02_Config/config.json`** – Global config (paths, toggles).
- **Environment** – `.env` files per environment (production/staging/local).

> All services must read from these files (no hardcoded ports/paths).

---

## Core Port Assignments (from v2 snapshot)

| Service                         | Port |
|---------------------------------|------|
| main_app                        | 3000 |
| trade_manager                   | 4000 |
| trade_executor                  | 8001 |
| btc_price_watchdog              | 8002 |
| symbol_price_watchdog_btc       | 8006 |
| kalshi_account_sync             | 8004 |
| kalshi_api_watchdog             | 8005 |
| symbol_price_watchdog_eth       | 8008 |
| active_trade_supervisor         | 8007 |
| auto_entry_supervisor           | 8009 |
| unified_production_coordinator  | 8010 |
| cascading_failure_detector      | 8011 |
| system_monitor                  | 8012 |

> If any port changes, update **MASTER_PORT_MANIFEST.json** and redeploy. Do **not** patch code constants.

---

## Path Conventions (v2)
All paths are resolved from **config.json** and/or environment variables.

**Base directories**
- `DATA_ROOT` → e.g., `~/rec_io_20/data/`
- `LOG_ROOT` → e.g., `~/rec_io_20/logs/`
- `CACHE_ROOT` → e.g., `~/rec_io_20/cache/`
- `CREDENTIALS_ROOT` → e.g., `~/rec_io_20/credentials/`

**Key files & folders**
- Price history (SQLite legacy): `${DATA_ROOT}/sqlite/btc_price_history.db`
- JSON snapshots (Kalshi watchdog): `${DATA_ROOT}/snapshots/*.json`
- Supervisor logs: `${LOG_ROOT}/supervisor/*.log`
- Service logs: `${LOG_ROOT}/{service}/{service}.log`
- Postgres backups: `${DATA_ROOT}/backups/postgres/*.sql`

---

## Environment Variables (minimum set)
These should be present in `.env` files and exported at process start (supervisord).

```
APP_ENV=production|staging|local
PORT_MANIFEST=/path/to/v2_final_snapshot_20250127/02_Config/MASTER_PORT_MANIFEST.json
GLOBAL_CONFIG=/path/to/v2_final_snapshot_20250127/02_Config/config.json
DATA_ROOT=/abs/path/to/data
LOG_ROOT=/abs/path/to/logs
CACHE_ROOT=/abs/path/to/cache

# Kalshi
KALSHI_API_BASE=https://api.elections.kalshi.com/trade-api/
KALSHI_API_KEY=...
KALSHI_API_SECRET=...

# PostgreSQL
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_DB=rec_io
POSTGRES_USER=rec_trading_user
POSTGRES_PASSWORD=...

# Coinbase (BTC price)
COINBASE_API_KEY=...
```

---

## Change Control (v2)
1. Edit **MASTER_PORT_MANIFEST.json** or **config.json** (PR required).
2. Update `.env` if new variables are introduced.
3. Restart via **supervisord** (services read ports/paths at boot).
4. Verify with health checks (`/health`) and the validation checklist below.

---

## Validation Checklist
- [ ] `PORT_MANIFEST` path resolves and JSON parses without error.
- [ ] Each running service binds to the port listed above.
- [ ] `GLOBAL_CONFIG` is readable at boot; no fallback to defaults.
- [ ] No hardcoded ports/paths found in recent diffs.
- [ ] Logs write under `${LOG_ROOT}/{service}/` without permission errors.
- [ ] `btc_price_watchdog` can read/write SQLite file path.
- [ ] `kalshi_api_watchdog` can write JSON snapshots.
- [ ] PostgreSQL connection uses env vars (no inline DSNs).

---

## Notes & Edge Cases
- Legacy components that still use **SQLite/JSON** must source their file paths from `config.json` to avoid drift.
- Any temporary port overrides for local debugging must **not** be committed.
- When moving to v3, prefer **Redis** for coordination and centralize path discovery in a config service.
