# Deployment Playbook – REC.IO v2

**Scope:** Repeatable steps to deploy/operate REC.IO v2 with minimal downtime. Applies to local/staging/prod. Uses `supervisord`, env-based config, local PostgreSQL (per v2 snapshot), and is Fly/Docker ready.

---

## 1) Environments & Sources of Truth
- **Ports:** `02_Config/MASTER_PORT_MANIFEST.json`
- **Global config:** `02_Config/config.json`
- **Env vars:** `02_Config/env_files/{production|staging|local}.env`
- **DB schema:** `03_Database_Schemas/postgresql_schema.sql`
- **Supervisor config(s):** `04_Infrastructure/supervisor/*.conf`
- **Deployment configs:** `04_Infrastructure/deployment_configs/` (e.g., `fly.toml`, docker files)

> No hardcoded ports/paths. Services must read from the manifest/config/env at boot.

---

## 2) Prereqs (one-time per host)
1. **OS packages:** `python3.11`, `python3-venv`, `pip`, `supervisor`, `postgresql-client`
2. **Python:** `python -m venv venv && source venv/bin/activate && pip install -r requirements.txt`
3. **PostgreSQL:** running and reachable; create DB/user per `.env`
4. **Folders:** `${DATA_ROOT}`, `${LOG_ROOT}`, `${CACHE_ROOT}` exist and writable
5. **Credentials:** place Kalshi & Coinbase creds under `${CREDENTIALS_ROOT}` with correct perms
6. **Ports:** confirm none are occupied (`lsof -i :PORT`)

---

## 3) First-Time Bootstrap (new machine / fresh clone)
```bash
# 1) Select environment
export APP_ENV=production  # or staging/local
export PORT_MANIFEST=/abs/path/v2_final_snapshot_20250127/02_Config/MASTER_PORT_MANIFEST.json
export GLOBAL_CONFIG=/abs/path/v2_final_snapshot_20250127/02_Config/config.json
set -a && source v2_final_snapshot_20250127/02_Config/env_files/${APP_ENV}.env && set +a

# 2) Python deps
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# 3) Database init (schema only)
psql "host=$POSTGRES_HOST port=$POSTGRES_PORT dbname=$POSTGRES_DB user=$POSTGRES_USER password=$POSTGRES_PASSWORD"   -f v2_final_snapshot_20250127/03_Database_Schemas/postgresql_schema.sql

# 4) Supervisor config
sudo mkdir -p /etc/supervisor/conf.d
sudo cp -r v2_final_snapshot_20250127/04_Infrastructure/supervisor/*.conf /etc/supervisor/conf.d/
sudo supervisorctl reread && sudo supervisorctl update
```

---

## 4) Start/Stop/Restart (standard ops)
```bash
# Start all
sudo supervisorctl start all

# Stop all
sudo supervisorctl stop all

# Restart individual service (example: trade_executor)
sudo supervisorctl restart trade_executor
```

**Startup order (if manual):**
1) PostgreSQL → 2) `trade_manager`, `trade_executor`, `main_app` → 3) watchdogs (`btc_price_watchdog`, `kalshi_api_watchdog`, `db_poller`, `kalshi_account_sync`, `unified_production_coordinator`, `active_trade_supervisor`)

---

## 5) Health Checks & Smoke Tests
- **Service health:** `curl http://localhost:<PORT>/health` should return 200
- **DB connectivity:** check supervisor logs for `connected to PostgreSQL`
- **Web UI:** load `main_app` on port 3000, verify dashboard renders
- **Market data:** confirm `kalshi_api_watchdog` is writing snapshots / DB rows
- **BTC feed:** confirm `btc_price_watchdog` updating `btc_price_history.db`
- **Trades:** create a small test trade (paper/sandbox if available) and see it flow: `auto_entry_supervisor → trade_manager → trade_executor → confirmation → DB write`

---

## 6) Logs & Monitoring
- **Supervisor:** `/var/log/supervisor/supervisord.log`
- **Services:** `${LOG_ROOT}/{service}/{service}.log`
- **Kalshi watchdog snapshots:** `${DATA_ROOT}/snapshots/*.json`
- **SQLite (legacy):** `${DATA_ROOT}/sqlite/btc_price_history.db`

> Rotate logs via supervisor/logrotate; ensure write perms.

---

## 7) Zero/Low-Downtime Updates
1. **Prepare new release:** branch/tag → run tests → build artifacts if using Docker.
2. **Drain critical actions:** temporarily pause new auto-entries (`auto_entry_supervisor`) if needed.
3. **Rolling restarts:** restart non-critical watchdogs first, then `trade_manager`, then `trade_executor`, finally `main_app`.
4. **Verify health:** run Section 5 smoke tests.
5. **Resume** auto-entry.

> For containerized deploys (v3+), use blue/green or rolling strategies; for Fly, deploy a new machine and cut over after health checks pass.

---

## 8) Rollback Procedure
- **Config-only change:** restore previous `env`/manifest/config and `supervisorctl restart all`
- **Code regression:** `git checkout <last_good_tag>` → reinstall deps if changed → `supervisorctl restart all`
- **DB change:** restore last backup (`03_Database_Schemas/backups/*.sql`) and restart dependent services

**Smoke after rollback:** Repeat Section 5.

---

## 9) Common Failure Modes & Fixes
- **Port already in use:** `lsof -i :PORT` → kill rogue proc → confirm manifest alignment
- **Postgres auth errors:** re-check `.env` vars; `psql` manual connect test
- **Kalshi API 401/403:** verify creds path & token validity; rotate keys if needed
- **Stale paths:** ensure services read `GLOBAL_CONFIG` and `PORT_MANIFEST` on boot (no hardcoded fallbacks)
- **File perms:** fix `${DATA_ROOT}` and `${LOG_ROOT}` ownership (`chown -R svcuser:svcgroup`)

---

## 10) Release Checklist
- [ ] Changelog updated
- [ ] Config/manifest diffs reviewed
- [ ] `.env` validated for target env
- [ ] DB migrations applied (if any)
- [ ] Supervisor reload: `reread` + `update`
- [ ] Health checks all green
- [ ] Smoke test trade passes
