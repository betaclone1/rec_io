# REC.IO v3 baseline audit

```yaml
doc_id: AUDIT_V3_BASELINE
initiative: VER4_DEVELOPMENT
audit_date: 2026-10-21
auditor: master agent (chat), repo read + read-only SSH
prod_observed_at_utc: 2026-10-21T23:43:59Z
repo_root_local: /Users/ericwais1/rec_io_local/3_0
prod_git_commit: 869e3baf
prod_git_subject: "Release v3.12.17 — Commodity category, Taker Edge, commodity symbol close"
changelog_head: docs/changelog/MASTER_CHANGELOG.md ## 2026-10-20 — Release v3.12.17
local_tree: dirty relative to that release (live_data_level and other uncommitted work). Prod does not have live_data_level.
secrets_policy: names and paths only. No token or password values.
not_this_doc: v4 target architecture, migration plan, or deploy steps.
```

Authority when docs disagree: running code and the production host beat older narrative. `docs/MASTER_DB_SCHEMA_REFERENCE.md` is broad but stale in places (see `drift`).

---

## 1. Product

REC.IO is a single-host automated trading system for Kalshi prediction markets. It ingests venue markets and index prices, builds strike ladders, and lets per-tenant **monitors** open and manage positions through Kalshi. Operators use a web UI. Bookkeeping posts Kalshi-vs-QuickBooks journals. Historical cycle packages are sealed locally and copied to Google Drive.

Primary user: one live trading tenant (`0001`, `master_admin`, Kalshi enabled). Other `system.master_users` rows exist and are not live-trading.

Surfaces:

- Desktop and mobile web UI under `frontend/`. Served by `main_app`. Tabs load on first view.
- HTTP read/aggregate API: `read_api` (port 3050).
- Realtime: PostgreSQL `NOTIFY` → `redis_switchboard` → Redis `rec_io:db_changes` and `/ws/db_changes` (port 3010). UI refetches `read_api`. Switchboard does not own domain HTTP.
- Ops: supervisor, cron, DigitalOcean snapshot, Drive upload.

Canonical product map: `docs/SYSTEM_BIBLE.md`. Component map: `docs/ARCHITECTURE.md`. Realtime: `docs/REALTIME_BACKBONE.md`, `docs/REDIS_ARCHITECTURE.md`.

Timezone: trading wall clock is `America/New_York` via `backend/core/time_eastern.py`. Postgres app connections set `timezone=America/New_York`. Host OS on production is **UTC**. Cron must not assume `CRON_TZ`.

---

## 2. Production DigitalOcean host (observed)

Source: `docs/PRODUCTION_HOST.md` plus read-only SSH on 2026-10-21. No droplet resize, snapshot, or process change was made.

```yaml
droplet_id: "562337636"
droplet_name: rec-io-server-new-york-1
public_ipv4: 165.22.13.146
retired_droplet_id: "513735057"   # 137.184.224.94 — do not snapshot
project_root: /opt/rec_io_server
ssh_user_default: root
os: Ubuntu 22.04.4 LTS
vcpus: 8
ram: 15Gi
mem_available_at_audit: ~12Gi
loadavg_1_5_15: [7.28, 9.31, 9.44]
root_disk: 310G
root_used: 48G (16%)
historical_data_disk: 26G   # /opt/rec_io_server/backend/data/historical_data
logs_disk: 1.8G              # /opt/rec_io_server/logs
postgres: "PostgreSQL 14.18 (Ubuntu)"
postgres_db: rec_io_db
postgres_db_size: 4675 MB
redis: "6.0.16"
redis_used_memory: 60.85M
redis_peak: 69.15M
redis_maxmemory: unlimited (0)
redis_dbsize: 206
nginx: 1.18.0 (Ubuntu)
app_role: rec_io_user
rec_environment: production
rec_single_user_mode: "1"
rec_default_user_schema: users_0001
rec_mtb_home_exchange_index: "2"
rec_enable_hourly_live: "0"
```

May 2026 perf audit (`docs/perf-audits/PROD_CPU_RAM_POST_KALSHI_INGEST_REFACTOR_2026-05-22.md`) described an **80G** disk and ~14Gi available on 8 vCPU. Disk is now **310G**. That audit’s process list (dual market watchdogs, `symbol_price_watchdog_*`) is **not** the current topology. Do not use those RSS numbers as the v4 baseline.

### 2.1 What shares the droplet

One machine runs SSH, nginx, PostgreSQL, Redis, and every Python supervisor program. There is no separate app tier, no managed database, and no object store in the live path. Google Drive is the off-box archive.

### 2.2 Listen map (ss, audit time)

| Bind | Port | Role |
|------|------|------|
| `0.0.0.0` / `[::]` | 22 (SSH, implied) | Admin |
| `0.0.0.0` | 80, 443 | nginx |
| `0.0.0.0` | 3000 | `main_app` |
| `0.0.0.0` | 3050 | `read_api` |
| `0.0.0.0` | 3010 | `redis_switchboard` WebSocket |
| `0.0.0.0` / `[::]` | 5432 | PostgreSQL |
| `127.0.0.1` / `[::1]` | 6379 | Redis |
| `0.0.0.0` | 8001, 8012, 8041 | tenant trade_executor, monitor_manager, exp-scalp ATS (0001) |
| `127.0.0.1` | 8033, 8039, 8050, 8052 | unified AES, exp-scalp AES, maker_edge, taker_edge |

Postgres is reachable on the public interface. Redis is loopback only. Several app ports are public in addition to nginx. Nginx site `proxy_pass` lines were not captured (grep of `sites-enabled` / `conf.d` returned empty).

### 2.3 Secrets on the host (paths only)

Supervisor program `environment=` lines in `/opt/rec_io_server/backend/supervisord.conf` inline DB passwords and Intuit OAuth admin/state secrets. Those values are **not** copied here. Treat that file as credential material.

| Secret | Path |
|--------|------|
| App env | `/opt/rec_io_server/.env` (`DB_*`, `REC_DB_*`, `DIGITALOCEAN_API_TOKEN`) |
| Kalshi prod key | `backend/data/users/user_NNNN/credentials/kalshi-credentials/prod/kalshi.pem` plus sibling `.env` (`KALSHI_API_KEY_ID`) and `kalshi-auth.txt` (`email:` line). Reader: `backend/core/kalshi_auth_files.py` |
| QuickBooks | `backend/data/users/user_NNNN/credentials/quickbooks/.env` (`INTUIT_CLIENT_ID`, `INTUIT_CLIENT_SECRET`, `INTUIT_REFRESH_TOKEN`, `QBO_REALM_ID`, `QBO_ENVIRONMENT`) |
| Drive (prod identity `eric@rec-io.com`) | `backend/data/secrets/gdrive_oauth_client.json`, `backend/data/secrets/gdrive_oauth_token.json` |
| Drive (laptop / agent scripts) | `.cursor/gcp-oauth.keys.json`, `.cursor/gdrive-server-credentials.json` — not the prod path |

### 2.4 Cron (root crontab, observed)

Both wrappers exit unless US Eastern wall clock matches. Host TZ is UTC, so they are scheduled every hour and self-gate. See `docs/PRODUCTION_HOST.md`.

| Schedule | Command | Effect |
|----------|---------|--------|
| `30 * * * *` | `REC_USER_NO=0001 /opt/rec_io_server/scripts/cron/bookkeeper_kalshi_reconcile.sh` | Fires only at 00:30 America/New_York. Kalshi portfolio vs QBO journal. Log: `logs/bookkeeper_kalshi_reconcile.log` |
| `0 * * * *` | `/opt/rec_io_server/scripts/cron/do_auto_backup_snapshot.sh` | Fires only at 01:00 America/New_York. DO snapshot of droplet 562337636, keep 5 `auto_backup_*`. Then `pg_dump` → Drive `DATA/DB_BACKUPS`, keep 14, delete local dump. Log: `logs/do_auto_backup_snapshot.log` |

Snapshot implementation: `scripts/do/auto_backup_snapshot.py`, `scripts/do/snapshot_prod.sh`. Dump: `scripts/backup/create_compressed_db_backup.sh`. Upload: `scripts/gdrive/upload-db-backup.js`.

Bookkeeper and backup are **not** supervisor programs.

### 2.5 Deploy path (repo, not re-verified live this audit)

Current production code matches changelog **v3.12.17** (`869e3baf`). Routine update path in-repo is git on the server plus supervisor regen, not the old full-image `scripts/deploy_digital_ocean.sh` (that guide still describes a greenfield install and is easy to misread).

Operator skills (do not run unless instructed): `.cursor/skills/prepare-update`, `apply-update`, `apply-update-from-local`, `simple-pull`, `push-commits-and-update-production`, `system-restart-production`.

Generator: `scripts/config/generate_unified_supervisor_config.py` → `backend/supervisord.conf`. Full local restart helper: `scripts/MASTER_RESTART.sh`.

Migrations: `scripts/migrations/*.up.sql` + `python3 scripts/db/run_migration.py`. `init_database()` in `backend/core/config/database.py` is greenfield bootstrap. The “run init_database to migrate” section inside `docs/MASTER_DB_SCHEMA_REFERENCE.md` conflicts with `AGENTS.md`. Agents must use the migration runner.

### 2.6 Supervisor programs (production status, 2026-10-21)

All of these reported `RUNNING`. Uptime on the market/price/strike set was **~19h 55m**.

Global:

| Program | Script | Notes |
|---------|--------|-------|
| `main_app` | `backend/main.py` | Wiring only: FastAPI, lifespan, routers. Port 3000 |
| `read_api` | `backend/read_api.py` | Reads. Port 3050. No Redis subscribe |
| `redis_switchboard` | `backend/redis_switchboard.py` | LISTEN → Redis → `/ws/db_changes`. Port 3010 |
| `cfbenchmarks_price_watchdog` | `backend/cfbenchmarks_price_watchdog.py` | Kalshi `cfbenchmarks_value` index WS → live_state. Port 8008 |
| `pyth_price_watchdog` | `backend/pyth_price_watchdog.py` | Commodity underlyings. Port 8009 in generator |
| `market_watchdog_ws_kalshi` | `backend/market_watchdog_ws.py --exchange kalshi --market 15m` | Hourly parked because `REC_ENABLE_HOURLY_LIVE=0`, so argv is `15m` not `all` |
| `strike_table_generator_ws_15m` | `strike_table_generator_ws.py --exchange kalshi --market 15m --symbols BTC ETH SOL` | autostart true. Port 8036 |
| `strike_table_generator_ws_hourly` | `... --market hourly --symbols BTC ETH SOL` | **autostart=false** in conf, but process **RUNNING** pid 4083238 for ~19h55m. Stale relative to the park flag. Not stopped during this audit |
| `strike_snapshot_publisher` | `backend/strike_snapshot_publisher.py` | |
| `cycle_packager` | `backend/cycle_packager.py` | Seals cycle packages |
| `position_risk_engine` | `backend/position_risk_engine.py` | PRE. ATS remains the closer |
| `system_monitor` | `backend/system_monitor.py` | |
| `cascading_failure_detector` | `backend/cascading_failure_detector.py` | Process/DB health. Not a trade exit |

Per tenant **0001** only (no `*_0002` programs on the host):

| Program | Script argv |
|---------|-------------|
| `trade_manager_0001` | `trade_manager.py` |
| `trade_executor_0001` | `trade_executor.py` |
| `kalshi_account_sync_0001` | `kalshi_account_sync_ws.py` |
| `kalshi_lifecycle_consumer_0001` | `kalshi_lifecycle_trade_consumer.py` |
| `monitor_manager_0001` | `monitor_manager.py` |
| `auto_entry_supervisor_0001` | `auto_entry_supervisor.py unified` |
| `active_trade_supervisor_0001` | `active_trade_supervisor.py unified` |
| `auto_entry_supervisor_0001_btc15m_exp_scalp` | `auto_entry_supervisor.py btc15m_exp_scalp` |
| `active_trade_supervisor_0001_btc15m_exp_scalp` | `active_trade_supervisor.py btc15m_exp_scalp` |
| `maker_edge_agent_0001` | `maker_edge_agent.py` |
| `taker_edge_agent_0001` | `taker_edge_agent.py` |

Generator still emits `*_0002` (and further slots) when that user is a trading user with monitors. Prod supervisor list did not include them.

Stream overlay observed in supervisor env (not a secret):

```yaml
MARKET_WATCHDOG_SYMBOLS: BTC,ETH,SOL,GOLD,SILVER,WTI
STRIKE_SNAPSHOT_SYMBOLS: BTC,ETH,SOL,GOLD,SILVER,WTI
STRIKE_SNAPSHOT_MARKETS: 15m
strike_generator_cli_symbols: BTC ETH SOL
PYTH_UNDERLYING_TICKERS_default: Metal.Index.1OZGOLD/USD,Metal.Index.SILVER/USD,Commodities.Index.PYTHOIL/USD
CFBENCHMARKS_PUBLISH_MODE: live_state
PYTH_PUBLISH_MODE: live_state
USE_TRADING_REDIS_COMMS: "1"
LIVE path flags present: STRIKE_PIPELINE_HEALTH_STRICT_MODE=1, STRIKE_PIPELINE_FRESHNESS_STRICT=1, ATS_HTTP_FALLBACK_ENABLED=0, REC_STRIKE_TABLE_ARCHIVE=0
```

Port manifest (can lag the generator): `backend/core/config/MASTER_PORT_MANIFEST.json`. Safe range documented as 8000–9000. Per-monitor dynamic ports still described there; production tradeflow is **one AES + one ATS per tenant**, plus the BTC 15m Expiration Scalp cutout pair, not one OS process per monitor.

### 2.7 Tenants (observed, no PII)

`system.master_users`:

| user_no | status | account_type | exchange_credentials.kalshi |
|---------|--------|--------------|-----------------------------|
| 0001 | active | master_admin | true |
| 0002 | inactive | user_basic | false |
| 0003 | inactive | master_admin | false |
| 0004 | pending_email_verification | user_basic | false |

Postgres schemas present: `analytics`, `archive`, `backtest`, `core`, `historical_data`, `live_data`, `public`, `rec`, `system`, `testing`, `users`, `users_0001`, `users_0002`, `users_0003`, `work_progress`.

No `users_0004` schema. Legacy schema `users` still exists beside `users_0001`. Application SQL often says `users.trades_NNNN`; `TenantConnection` (`backend/core/tenant_context.py`) rewrites that to `users_<slot>` and sets `rec.tenant_pg_schema`. RLS policy `rec_tenant_gate` with `FORCE ROW LEVEL SECURITY`; role `rec_io_user` is `NOBYPASSRLS`. Empty GUC is allowed to see all tenant rows (operator tools). Superuser bypasses RLS.

Global daemons must use `get_system_postgresql_connection()`, not a tenant-wrapped connection. Registry: `docs/TENANT_TOUCH_REGISTRY.md`.

`REC_SINGLE_USER_MODE=1` on prod. Long-term backlog still calls out hardcoded `0001`: `docs/LONG_TERM_INITIATIVES.md`.

---

## 3. Data plane

### 3.1 Hot path (current code)

Documented in `docs/KALSHI_MARKET_INGEST.md` and `docs/ARCHITECTURE.md`.

```
Kalshi WS + rollover REST
  → market_watchdog_ws.py
  → Redis live_state (not PG orderbook tables)
       rec_io:live_state:v1:market:kalshi:{15m|hourly}:{SYM}
       trade_monitor:orderbook_levels:v1:{ticker}
       fanout rec_io:live_state:updated
       settled registry rec_io:market_watchdog:settled:v1 (15m)

CF Benchmarks index WS → cfbenchmarks_price_watchdog → live_state (+ ring PG)
Pyth commodity index → pyth_price_watchdog → live_state

strike_table_generator_ws → strike ladders (live_state; LIVE_STATE_CACHE_ENABLED=1)
strike_snapshot_publisher → snapshot read path

monitor_list (Postgres) → auto_entry_supervisor
  → Redis trading:tm:commands or HTTP POST /trades
  → trade_manager → trade_executor → Kalshi REST orders

fills: kalshi_account_sync_ws → TM confirm_open
open positions: active_trade_supervisor (Redis hash live_state:tenant:{slot}:active_trades)
venue result: market lifecycle WS → Redis → kalshi_lifecycle_consumer → trades.market_result
  → TM finalize → win_loss_confirmed from venue only
```

Removed and must not be revived as fallbacks: `backend/market_watchdog.py`, `kalshi_live_orderbook_sidecar`, PG `live_data.market_kalshi_*` writers, strike-gen PG market snapshot fallback. Schema reference still documents `live_data.market_kalshi_hourly`, `market_kalshi_15m`, `market_kalshi_ws_15m`. Those sections are historical relative to the ingest doc.

### 3.2 Redis roles

- Switchboard channel: `rec_io:db_changes` (PG NOTIFY channel `rec_io_db_changes`, function `public.rec_io_db_notify()`).
- Trading comms: `USE_TRADING_REDIS_COMMS=1`. Examples: `trading:tm:commands`, `trading:executor:trigger`, `trading:mm:monitor_settings`, `rec_io:ats_enroll_request`, `rec_io:tm:positions_updated`.
- Live state keys above. Sandbox prefix `sandbox:kalshi:*` is not written in production.
- Redis is not the system of record for trades. Postgres is.

### 3.3 Schemas (catalog, not every column)

| Schema | Holds |
|--------|--------|
| `users_NNNN` | Tenant trades, monitors, strategies, orders, fills, positions, settlements, subaccounts, account history, paper twins |
| `users` | Legacy qualifier / leftover objects. Do not assume it is the only tenant store |
| `live_data` | `symbols_list`, strike tables, price rings, `live_symbol_status`, pipeline health |
| `system` | `master_users`, `strategy_list_default`, `schema_migrations`, `health_status`, `event_log`, `version_control` |
| `historical_data` | `btc_price_history`, `eth_price_history`, `ndx_price_history`, `spx_price_history`, `btc15m_cycle_candles` |
| `analytics` | Fingerprint / momentum / probability lookup tables (BTC, ETH, NDX, SPX). Dated snapshots (e.g. `20250917`, `20251016`) |
| `archive` | `trades_archive_live_*`, `trades_archive_paper_*` |
| `backtest` | `kalshi_historical_trades_api`, `grid_sweep_trades` |
| `core` | `system_state` |
| `work_progress` | TTC progress scratch |
| `testing` | Old orderbook experiments |
| `public` | Legacy `trades`, `fills`, `positions`, `active_trades` |
| `rec` | RLS helpers `ensure_tenant_rls_for_schema`, `refresh_all_tenant_rls` |

Full column text: `docs/MASTER_DB_SCHEMA_REFERENCE.md` (generated header date 2026-03-03; many later migrations were edited in). Drift check: `scripts/db/check_db_schema_drift.py`.

### 3.4 `live_data.symbols_list` (prod vs local repo)

Prod columns at audit: `id`, `symbol`, `analytics_updated`, `date_added`, `category`.

Prod rows:

| symbol | category |
|--------|----------|
| BTC, ETH, SOL, XRP, DOGE | crypto |
| GOLD, SILVER, WTI | commodity |

Local uncommitted migration `scripts/migrations/20261021_1322_symbols_list_live_data_level` adds `live_data_level` (`full` \| `market` \| `price_only` \| `none`). **Not on production.** Schema reference in the dirty tree already documents it. Seed intent in that doc: BTC and ETH `full`; GOLD, SILVER, WTI `market`; SOL, XRP, DOGE `none`. Prod strike CLI is still `--symbols BTC ETH SOL`, which does not match that seed and does not include GOLD/SILVER/WTI on the strike generator command line. Market watchdog env **does** list GOLD, SILVER, WTI.

---

## 4. Kalshi API

Official sharding doc linked from `docs/KALSHI_EXCHANGE_SHARDING.md`.

### 4.1 Endpoints in code

| Use | URL |
|-----|-----|
| Prod REST | `https://external-api.kalshi.com/trade-api/v2` |
| Prod WS | `wss://external-api-ws.kalshi.com/trade-api/ws/v2` |
| Demo REST (tests only) | `https://demo-api.kalshi.co/trade-api/v2` |
| V1 account history | `https://api.elections.kalshi.com` in `backend/kalshi_account_sync_ws.py` (`KALSHI_V1_BASE_URL`) |

Auth: API key id + RSA PEM. Request signing in `backend/bookkeeper/kalshi_portfolio_balance.py` (`_sign_request`) and the executor/account-sync stack. Credential layout in §2.3. `system.master_users.exchange_credentials.kalshi` must not be false or the user is paper-only even if key files exist (`kalshi_auth_ok` in the supervisor generator). `kalshi_user_id` on `master_users` is the venue UUID.

### 4.2 Exchange shards

Collateral is per `(exchange_index, subaccount)`, not a flat cash number.

| exchange_index | Kalshi category | REC.IO |
|----------------|-----------------|--------|
| 0 | Catch-all | Pre-cutover crypto home. CASH/primary often here |
| 1 | Exotics | Unused for product |
| 2 | Crypto | **Home of crypto markets after 2026-08-24.** MTB operational address `(2, 1)` |
| 3 | Sports | Unused |

Subaccount numbers (REC names):

| n | Name |
|---|------|
| 0 | Primary / CASH on that shard |
| 1 | Master Trading Bankroll (MTB). Orders default here |
| 2 | Cash Transfer in portfolio sync docs; bookkeeper map also has named roles in `KALSHI_SUBACCOUNT_NAME_TO_NUMBER` (`backend/bookkeeper/kalshi_subaccount_transfer.py`) |
| 3+ | Ancillary / `undefined_N` |

Within shard: `POST /portfolio/subaccounts/transfer` with `exchange_index`.
Across shards: one `POST /portfolio/intra_exchange_instance_transfer` (IAT). Async. Poll until destination address credits. Helper: `transfer_kalshi_address`.

Orders: `POST /portfolio/events/orders` (Create Order V2). `trade_executor` sends `subaccount` default **1** and `exchange_index` default **-1** (auto-route by ticker). Auto-route does **not** move cash. Crypto debit comes from `(2, 1)`. Env `REC_MTB_HOME_EXCHANGE_INDEX=2` (observed on prod) selects rake home shard.

Balances: `GET /portfolio/subaccounts/balances` matrix → `users_*.subaccounts_*` columns `exchange_0_balance` … `exchange_3_balance` plus `balance` = sum. Migration `20260813_1448_subaccount_exchange_balances`. Poller: `backend/bookkeeper/kalshi_portfolio_balance.py` and account sync.

Money: Kalshi amounts often **centicents** ($1 = 10000). Internal subaccount balances stored in **cents**. Module: `backend/core/kalshi_money.py`. Fixed-point contract counts (`*_fp`, `*_dollars` text) landed in orders/fills/positions/settlements during the Kalshi FP migration.

### 4.3 Market data WS

Implementation: `backend/core/market_watchdog/venues/kalshi/ws_ingest.py`. Entry: `backend/market_watchdog_ws.py`.

Channels used on the hot path (ingest doc): ticker, orderbook delta, `market_lifecycle_v2` for `market_result` on the outgoing contract. Account sync owns user-order/fill WS separately (`kalshi_account_sync_ws.py`).

15m rollover (must match sandbox checkpoint `scripts/sandbox/kalshi_market_feed/CHECKPOINT_WS_ROLLOVER_BASELINE.md`):

1. No REST at `:00/:15/:30/:45`. `_subscription_sync` ~1s with the wall-clock live ticker.
2. Outgoing contract: ticker WS only (not orderbook) plus lifecycle for `market_result`.
3. Orderbook: add new markets before delete old; channel `seq` + batched `get_snapshot`; coalesced Redis flush ~50ms.
4. Log lines: `rollover_15m`, then `WS_ROLLOVER_OK`.

Series examples: `KXBTC15M`, `KXETH15M`, `KXGOLD15M`, `KXSILVER15M`, `KXWTI15M`. Ticker shape `KXBTC15M-26AUG131630-30`. Sharding did not change ticker strings.

### 4.4 Account sync and lifecycle

- `kalshi_account_sync_ws.py`: orders, fills, positions, portfolio into tenant tables; wakes trade manager.
- `kalshi_lifecycle_trade_consumer.py`: applies venue `market_result` onto `trades_*`.
- 5-minute `/events` backfill is the documented waiter when lifecycle misses. Do not invent `market_result` from spot.
- Historical backfill CLI: `backend/api/kalshi-api/kalshi_historical_ingest.py`.
- Portfolio narrative: `docs/PORTFOLIO_ACCOUNT_SYNC.md`.

### 4.5 Settlement rule (non-negotiable)

`win_loss_confirmed` is computed only from venue `market_result` + trade `side` (`compute_win_loss_confirmed_from_venue` in `backend/core/kalshi_lifecycle_trade_outcome.py`). `symbol_close` / `symbol_expiration` are analytics, not the outcome. Schema-reference sentences that still say otherwise are wrong. Rule file: `.cursor/rules/00-no-fallbacks.mdc`.

---

## 5. Auto-parameter pipeline

“Auto parameters” are columns on the tenant monitor (and the strategy template those columns are copied from). They are not a separate config service.

```yaml
system_of_record:
  monitors: users_<NNNN>.monitor_list_<NNNN>
  strategy_templates: users_<NNNN>.strategy_list_<NNNN>
  global_seed: system.strategy_list_default
  runtime_push: monitor_manager Redis stream trading:mm:monitor_settings
  settings_module: backend/core/auto_entry_settings_store.py
  entry_process: backend/auto_entry_supervisor.py
  exit_process: backend/active_trade_supervisor.py
  order_gateway: backend/trade_manager.py → backend/trade_executor.py
  exceptions_outside_aes:
    - maker_edge_agent.py  # strategy "Maker Edge"
    - taker_edge_agent.py  # strategy "Taker Edge"
```

### 5.1 Two different switches

| Column | Meaning |
|--------|---------|
| `monitor_list.status` | `active` / `inactive`. Whether AES/ATS iterations run for that monitor |
| `monitor_list.auto_trade` | Boolean master gate for automatic entry **and** ATS auto-stop |
| `monitor_list.auto_trade_status` | Display / orchestration (`inactive` / `active`). Not the script lifecycle |

Paper vs live:

| Column | Meaning |
|--------|---------|
| `paper_trade` | Paper path in trade_manager (no live Kalshi order) |
| `test_filter` | Forces paper; fills do not touch paper account balance |
| `reverse` | Dispatch opposite side of the signal; auto-stop disabled; label `Reverse {strategy}` |

Weekend mutation (`monitor_manager`, Sat 00:00:30 ET / revert Mon 00:00:20 ET): `weekend_adjustment` ∈ `none`, `paper_only`, `reduce_position_50`, `reduce_position_25`, `probability_adjustment_10`, `probability_adjustment_25`. Originals stored in `weekend_adjustment_snapshot` jsonb.

### 5.2 Identity and size

| Column | Role |
|--------|------|
| `id` | Slot-prefixed integer. Slot S uses `S*10000+1 .. S*10000+9999` (0001 → 10001–19999). Name `mon_<slot>_<id>` |
| `name`, `symbol`, `market` | `market` is `15m` or `hourly` (column default `hourly`) |
| `strategy` | Router key. Exact strings below |
| `subaccount` | Kalshi subaccount number. Default 1 = MTB. Bankroll uses that subaccount’s `bankroll_current`. Migration `20261017_1200_monitor_list_subaccount` |
| `position_size`, `position_type` (`percent` default), `multiplier`, `total_position` | Size |
| `bankroll_allotment`, `bankroll_allotment_pct`, `bankroll_allotment_total` | Allotment |
| `performance_based_allocation`, `current_performance_modifier`, `current_max_pct_exposure` | Performance sizing |
| `monitor_dupe_pairing` | `integer[]` of peer monitor ids. TM caps new open size on same ticker+side by summed peer exposure |

Subaccount drawdown halt is on `subaccounts_*`, not the monitor: `drawdown_trading_halt`, `drawdown_reset_threshold_pct` (default 50), `trading_halt_active`, `drawdown_halt_monitor_snapshot`. Category `crypto` \| `commodity` on the subaccount (`20261020_1200_subaccount_category_base_value_factor`).

### 5.3 Entry gates (shared shape)

These live on both `monitor_list_*` and `strategy_list_*` unless noted.

| Column | Default | Use |
|--------|---------|-----|
| `min_probability` | 95.00 | Win-probability floor (numeric, not int) |
| `max_probability` | 100.00 | Ceiling |
| `min_differential` | 0.25 | Edge vs price. Hourly HTC / Rising Devil: min uses a −0.5 cushion |
| `max_differential` | NULL | Blocks “too good” edge when set |
| `min_time` | 120 | TTC window lower bound (seconds). Expiration Scalp seed uses a short window (0–60 in strategy seed notes) |
| `max_time` | 900 | TTC window upper bound |
| `min_ttc_seconds` | 60 | Additional TTC floor |
| `min_volume` | 1000 | |
| `min_ask` | 0.0000 | Ask window floor. High Water Scalp: the single entry price target |
| `max_ask` | 0.9800 | Ask window ceiling. HWS copies `min_ask` into both |
| `min_ask_range` | NULL | Rising Devil: min active-side ask range; NULL disables |
| `min_buffer_pct` | 0 | Expiration Scalp: minimum strike `buffer_pct`. 0 disables |
| `min_movement` / `max_movement` | 0 / 100 | Expiration Scalp movement window vs ladder `movement_percentile` |
| `adverse_delta_15s_pct` | 0 | Expiration Scalp veto on 15s delta against the side. 0 disables |
| `allow_re_entry` | false | |
| `min_cooldown_timer` / `max_cooldown_timer` | 300 / 3300 | Seconds. Strategy will not activate outside this cooldown band |
| `cooldown_timer`, `cooldown_start_time` | runtime | |
| `prob_adj` | 5.00 | Hourly HTC spike cooldown raises min probability by this, rather than a hard pause |
| `spike_alert_enabled` | true | |
| `spike_alert_momentum_threshold` | 36 | |
| `spike_alert_cooldown_threshold` | 30 | |
| `spike_alert_cooldown_minutes` | 15 | |
| `entry_verification_period_enabled` / `_seconds` | false / empty | Dwell before entry (Expiration Scalp, High Water Scalp) |
| `min_fill_price` | NULL | Minimum estimated taker fill (dollars) before executor sends. NULL or 0 disables. TM precheck |
| `min_slippage` | 0 | Projected entry slippage floor (est fill − trigger). 0 disables. Enabled range −0.2000..0.0000. TM rejects worse |
| `max_price_spread` | 0.0300 | |
| `time_in_force` | `fill_or_kill` | `fill_or_kill` \| `immediate_or_cancel` \| `good_till_canceled` |
| `order_type` | `market` | Policy `limit` or `market`. Kalshi request may still be a priced limit |

### 5.4 Exit / auto-stop parameters

ATS evaluates only pool rows in status `active`. Same `auto_trade` flag as entry. Module notes: `docs/TRADE_LIFECYCLE_AND_AUTO_STOP_CURRENT.md` (snapshot 2026-09-07; still the best as-built narrative; code wins if it conflicts).

| Column | Default | Use |
|--------|---------|-----|
| `stop_loss_price` | 0 | Ask-gate stop. **0 disables**. Fires when opposite-side ask exceeds `1 − stop_loss_price`. Trigger `stop_loss_floor` |
| `stop_verification_period_enabled` / `_seconds` | false / 1 | Dwell before auto-stop (0–60). 0 = immediate |
| `momentum_spike_enabled` | true | |
| `momentum_spike_threshold` | 36 | Trigger `momentum_spike` |
| `momentum_scalp_entry_threshold` | NULL | Momentum Scalp entry |
| `momentum_scalp_trailing_stop_amount` | 0.10 | |
| `momentum_scalp_profit_target` | 0.99 | |
| `max_profit` | 0.9900 | Scalp max profit |
| `limit_close_price` | 0 | High Water Scalp owned-side GTC target (e.g. 0.99). 0 disables. Opposite rest is `1 − price` |
| `limit_close_offset` | 0 | High Water Test 1: GTC = fill + offset |
| `stop_loss_offset` | 0 | High Water Test 1: floor = fill − offset |
| `position_risk_mode` | `legacy` | `legacy` \| `shadow` \| `paper`. HWS Scalp stop authority uses PRE LVWAP regardless |
| `position_risk_policy` | `hws_lvw_v1` | Allowlisted PRE policy |
| `position_risk_book_only_enabled` | false | Marginal L2-only decisions when public tape is UNKNOWN |
| `flip_sell_prob` | false | After probability auto-stop, open inverted side |
| `flip_sell_floor` | false | After floor stop. **Expiration Reversal CHECK forces this true** |
| `flip_sell_prob_mult` / `flip_sell_floor_mult` | NULL until set | Size token, e.g. `1x` |

`close_method` values written by ATS (`_close_method_for_auto_trigger`): `auto_stop_loss_floor`, `auto_probability`, `auto_momentum_spike`, `auto_scalp_max_profit`, `auto_scalp_trailing_stop`, `auto_scalp_profit_target`, `auto_reversal_*`, `auto_close_retry`, `limit_close`, else `auto_{key}`. Manual UI: `manual`. Contract end: `expired`.

Close order is **buy the opposite leg**. Do not invert `side` again in the close payload.

### 5.5 Loss prevention

| Column | Default | Use |
|--------|---------|-----|
| `loss_prevention_toggle` | true | Master enable |
| `loss_prevention_method` | `win_streak` | or `time` |
| `loss_prevention_state` | `none` | Token (renamed from `loss_prevention`) |
| `win_streak`, `win_streak_threshold` | 0 / 22 | Streak method |
| `loss_prevention_duration` | 4 | Time method, hours |
| `simulated_trade_loss_prevention` | false | Time method includes simulated trades |
| `symbol_wide_loss_prevention` | false | Follow `live_data.live_symbol_status` for the symbol when that state is not `off` |
| `loss_prevention_cooldown_loss_count` | 0 | |
| `live_loss_prevention_cooldown_start_time` | | Live-trade anchor |
| `simulated_loss_prevention_cooldown_start_time` | | |
| `original_loss_prevention_cooldown_start_time` | | |

Expiration-family LP toggle defaults off in the product bible (Expiration Scalp / Reversal, High Water Scalp / Test 1). Flip sells after a loss keep full size and do not count as a separate LP loss.

Regime (separate from LP): `regime_monitor_enabled` (default false), `regime_window` (`30d`, `7d`, `1d`, `12h`) switches LIVE/PAPER.

### 5.6 Strategy name registry

Prod `system.strategy_list_default.name` on 2026-10-21:

`15m HTC`, `Expiration Reversal`, `Expiration Scalp`, `High Water Scalp`, `High Water Test 1`, `Hourly HTC`, `Maker Edge`, `Momentum Breakout`, `Momentum Contain`, `Rising Devil`, `Taker Edge`.

AES code routes at least: `Momentum Scalp`, `Momentum Reversal`, `Reverse HTC`, `Momentum Breakout`, `Momentum Contain`, `Rising Devil`, and defaults unknown names to **Hourly HTC** (`auto_entry_supervisor.py` around the strategy dispatch and `_strategy` fallback). `Momentum Scalp`, `Momentum Reversal`, and `Reverse HTC` are in code and **not** in the prod default strategy table. `15m HTC` is in the table; confirm router before treating it as a live dispatch key.

| Strategy | Who places / exits |
|----------|--------------------|
| Hourly HTC | Unified AES / ATS. Default fallback name |
| Expiration Scalp | Dedicated cutout processes `*_btc15m_exp_scalp` for BTC 15m. Unified AES excludes those rows |
| Expiration Reversal | AES/ATS. DB check: `flip_sell_floor` must be true. Seeded by `20261010_1100_expiration_reversal_strategy` |
| High Water Scalp | AES/ATS + PRE LVWAP stop. Doc: migrations `20260828_1635_high_water_scalp` |
| High Water Test 1 | AES/ATS. IOC inside ask band; `limit_close_offset`, `stop_loss_offset` |
| Rising Devil | AES. Differential gates plus `min_ask_range` |
| Momentum Scalp / Reversal / Breakout / Contain, Reverse HTC | AES branches |
| Maker Edge | `maker_edge_agent`. **Not** AES/ATS. Dual resting bids. Doc: `docs/MAKER_EDGE_STRATEGY.md`. Seed `20261017_1500_maker_edge_strategy`. Monitors: 15m, `min_ask=max_ask` default 0.01, `min_time`–`max_time`. Symbols in the doc: BTC, ETH, GOLD, SILVER, WTI |
| Taker Edge | `taker_edge_agent`. **Not** AES/ATS. One GTC after a public print at/above target. Doc: `docs/TAKER_EDGE_STRATEGY.md`. Seed `20261020_1645_taker_edge_strategy`. Default target 0.99. Hold to settlement |

Maker/Taker membership filters: `backend/core/maker_edge_kalshi.py`, `backend/core/taker_edge.py` (`STRATEGY_NAME`, exclude from unified AES/ATS).

### 5.7 Open / confirm / settle sequence

```
AES is_auto_trade_enabled + strategy gates
  → trigger_auto_entry_trade
  → TM add_trade (POST /trades or Redis)
       enrich TIF, min_fill, min_slippage, offsets from monitor
       dupe-monitor cap
       insert status=pending
       paper: promote to open, notify ATS
       live: executor; store order_id_open
  → account sync fill → confirm_open_trade → status=open
  → ATS enroll Redis rec_io:ats_enroll_request + ACK ats:enroll:result:{correlation_id}

UI manual: POST /api/trigger_open_trade → trade_actions → TM
ATS flip-sell: trigger_flip_sell_open_after_auto_stop → TM open inverted side

Hold to contract end: TM APScheduler status=expired (~15 min job)
  → lifecycle or /events sets market_result
  → finalize_expired → closed + win_loss_confirmed

Failed close: row stays open (no durable close_failed). ATS retry trigger close_attempt_failed.
```

`entry_method`: `auto_entry` (AES), `manual`, `flip_sell`, `simulated_15m`.

Trade statuses: `pending → open → closing → closed`, or `open → expired → closed`. Also `partial`, `ERROR` (swept by expiry job).

Tables: `users_<slot>.trades_<slot>` (live/paper log), `trades_simulated_<slot>` (no venue confirm columns). Operational ATS pool: Redis `live_state:tenant:{slot}:active_trades` when `LIVE_STATE_ACTIVE_TRADES_ENABLED` (default 1). Optional PG `active_trades_15m_*` / `active_trades_hourly_*`.

Executor WS health gate can refuse orders. `ATS_HTTP_FALLBACK_ENABLED=0` on prod.

### 5.8 Price → strike → probability

Crypto spot: Kalshi CF Benchmarks index (`cfbenchmarks_price_watchdog`), not the old per-symbol Coinbase `symbol_price_watchdog_*` processes. Those files still exist (`backend/symbol_price_watchdog.py`, `backend/symbol_price_watchdog_finance.py`) and are **not** in `global_core_service_specs()`.

Commodities: `pyth_price_watchdog`.

Strike ladder: `strike_table_generator_ws.py` for symbols on its CLI. Probabilities / differentials / `buffer_pct` / movement percentile are ladder fields AES reads. Analytics lookup tables in schema `analytics` (`probability_lookup_*`, fingerprints) are the historical model store; live entry uses the strike pipeline, and `STRIKE_PIPELINE_HEALTH_STRICT_MODE=1` on prod.

Hourly live streams are **code-parked** unless `REC_ENABLE_HOURLY_LIVE=1`. Prod flag is `0`. The hourly strike process was still running (see §2.6).

---

## 6. Google Drive archives

Canonical read path is **Node scripts**, not the GDrive MCP. `docs/GDRIVE_ACCESS.md`.

Two credential domains:

1. Production uploads: `eric@rec-io.com` JSON under `backend/data/secrets/` (`GDRIVE_OAUTH_PATH`, `GDRIVE_CREDENTIALS_PATH`).
2. Laptop/agent search and Docs: `.cursor/` OAuth files. Scripts: `scripts/gdrive/search-drive.js`, `read-file.js`, `daily-briefing-drive-check.js`, `create-doc.js`, `create-account-history-sheet.js`.

### 6.1 Folders

| Drive path | Folder id | Writer | Retention |
|------------|-----------|--------|-----------|
| `DATA/DB_BACKUPS` | `1yvZm4itVZGmDXlIu7qBeIFKbCTiITO3o` (`GDRIVE_DB_BACKUPS_FOLDER_ID`) | `scripts/gdrive/upload-db-backup.js` from nightly cron | Keep 14 `rec_io_db_backup_*`. Local dump removed after upload unless `DB_BACKUP_KEEP_LOCAL=1` |
| `DATA/HISTORICAL_DATA/BACKTESTING_DATA` | `1Jlhz57hSXMYe8Yr_GtIJsaXY0GAW6L1v` (`GDRIVE_BACKTESTING_DATA_FOLDER_ID`) | `backend/core/cycle_gdrive_upload.py` → `scripts/gdrive/upload-backtesting-data.js` | Full sealed cycle packages. Enable `CYCLE_GDRIVE_UPLOAD` (default when creds resolve). Disable `CYCLE_GDRIVE_UPLOAD=0`. Legacy alias `BTC15M_CYCLE_GDRIVE_UPLOAD` |

Download: `scripts/gdrive/download-backtesting-data.js`, `scripts/gdrive/download_week_packages.mjs`, `backend/core/cycle_gdrive_download.py`.

DO snapshots are **not** Drive objects. They are DigitalOcean droplet snapshots named `auto_backup_YYYY-MM-DD_HHMM`, prune to 5. Deploy-named snapshots are not pruned.

### 6.2 Cycle package product (local disk is the working copy)

Doc: `docs/HISTORICAL_CYCLE_DATA_PRODUCT.md`, `docs/CYCLE_RECONSTRUCTION_PIPELINE.md`.

- Local root: `backend/data/historical_data/backtesting_data/` (sealed `.tar.xz` per cycle).
- Prod historical tree size at audit: **26G** (whole `historical_data`, not only packages).
- Schema version 4 members called out in the product doc: `public_trades.csv`, `volume_path.csv`, `quality.json`, rich `market_meta`, `proprietary_members`. External SKU strips `strike_table.csv` and `metrics_ring.csv` via `scripts/backtest/export_cycle_package_variant.py`.
- Size ballpark in that doc: ~4–6 MB xz per busy BTC cycle; ~80–110 GB/year/symbol typical.
- Packager process: `cycle_packager` (supervisor, autostart when `features.cycle_backtesting_capture` is not false).
- Hot PG capture can be disabled (`CYCLE_HOT_PG=0`). Prod strike archive flag `REC_STRIKE_TABLE_ARCHIVE=0`.
- Postgres `historical_data.*_price_history` is a different store (Eastern-naive `timestamp` first column). It is not the cycle package.
- Commercial resale is explicitly gated on Kalshi/CFB terms. Not started.

Public trade day files and month archives are a second historical product (`scripts/backtest/`, `docs/BACKTESTING.md`). Rule: do not keep duplicate pull caches after a successful package (`.cursor/rules/09-no-duplicate-historical-artifacts.mdc`).

Account-history sheets: `scripts/gdrive/export_account_history.py` / `create-account-history-sheet.js` (Sheets API). Separate from the backup and backtest folders.

---

## 7. QuickBooks

Package: `backend/bookkeeper/`. CLI: `python -m backend.bookkeeper.bookkeeper`. OAuth HTTP: `backend/bookkeeper/intuit_oauth_routes.py`. REST: `backend/bookkeeper/quickbooks/quickbooks_online_rest.py`.

```yaml
oauth_authorize: https://appcenter.intuit.com/connect/oauth2
token_url: https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer
api_production: https://quickbooks.api.intuit.com   # via api_base_url()
api_sandbox: https://sandbox-quickbooks.api.intuit.com
config_env: backend/data/users/user_NNNN/credentials/quickbooks/.env
example: backend/bookkeeper/quickbooks/dotenv.example
default_environment_if_unset: sandbox
prod_cron_user: "0001"
```

`QboConfig` fields: client id, client secret, refresh token, realm id, environment. Refresh persists a new refresh token back into that `.env` (`_persist_refresh_token`).

### 7.1 What QBO is used for

Chart of accounts read; account lookup by exact name; transfers between named accounts; TransactionList report; uncleared bank/credit-card lines (TransactionList `cleared=Uncleared` — **not** the Banking-tab “for review” feed; that is not on this v3 Accounting API).

Kalshi reconcile (`--reconcile-kalshi`):

| Piece | Value |
|-------|--------|
| Left side | Kalshi `GET` portfolio total (cash + positions), cents, via `fetch_total_portfolio_cents` |
| Right side | QBO account **Kalshi Trading Account** (`--kalshi-account`) |
| Residual P/L account | **Trading Income** |
| Interest credits | **Interest Income** (`kalshi_reconcile_credits`) |
| Incentive credits | **Kalshi Incentives Income** |
| Skip if abs(gap) < | `$0.01` (`--min-diff`) |
| Idempotency | Skip if a reconcile JournalEntry already exists for the target date unless `--force` |
| Nightly | `--reconcile-prior-day` so the just-closed ET day gets the entry. Cron wrapper |
| Dry run | `--reconcile-dry-run` |

External cash (ACH) must not be dumped into Trading Income. `backend/bookkeeper/kalshi_reconcile_externals.py` lists QBO Transfers/Deposits against Kalshi Trading Account and strips unmatched bank movement from the wallet gap before the income plug (`adjusted_reconcile_gap`).

Journal is two-sided between the asset account and the income (or interest/incentive) account. This is **not** a full general ledger sync of every fill.

### 7.2 Bookkeeper that is Kalshi-only (not QBO)

| Module | Role |
|--------|------|
| `kalshi_portfolio_balance.py` | Signed REST balance and subaccount matrix |
| `kalshi_subaccount_transfer.py` | Within-shard transfer and IAT |
| `kalshi_reconcile_credits.py` | Classify Kalshi interest vs incentive credits for the QBO split |
| Account sync processes | Live portfolio tables |

Subaccount rake (MTB target PnL → transfer toward CASH on the home shard) is account-sync / Kalshi, controlled by `subaccounts.automatic_transfers`, `target_pnl__pct`, `transfer_amt`, `base_value`. Home shard env `REC_MTB_HOME_EXCHANGE_INDEX`.

### 7.3 Gaps

- QBO is one tenant’s books (`0001` cron), not a per-monitor ledger.
- No customer/invoice/sales-receipt workflow found in the bookkeeper CLI surface.
- Sandbox is the code default if `QBO_ENVIRONMENT` is missing. Production cron depends on the user `.env` being set to production. This audit did not open that file.
- Intuit client secrets also appear as process env names `REC_INTUIT_OAUTH_STATE_SECRET` and `REC_INTUIT_OAUTH_ADMIN_SECRET` inside supervisor config (values omitted).

---

## 8. Frontend and HTTP edges

- UI: `frontend/` (HTML/JS/CSS). Desktop and mobile. Help center map: `docs/HELP_CENTER_CONTENT_MAP.md`.
- `backend/main.py` is wiring. Routers: `backend/web/routers/` via `register_main_app_routers()`.
- Reads that are aggregates belong on `read_api`, not new `main_app` routes.
- Trade open proxy and some writes still sit on main / `backend/web/trade_actions.py`.
- Auth: `docs/AUTHENTICATION_GUIDE.md`. Registration email SMTP notes: `docs/REC_ALERTS_SMTP_SECRETS.md`.

---

## 9. Drift, debt, and traps for v4

Ordered by how easily an agent will cargo-cult the wrong generation.

1. **Two generations of market ingest in the docs.** `KALSHI_MARKET_INGEST.md` (Redis live_state, one watchdog, no PG orderbook) is current. `ARCHITECTURE.md` still says `market_watchdog_ws_kalshi_15m` and `market_kalshi_*` tables. Schema reference still lists those tables. Port manifest still lists both split and unified program names.
2. **Hourly is parked in env and autostart, but the hourly strike process was RUNNING** on prod at audit time (~20h). Flag `REC_ENABLE_HOURLY_LIVE=0`, conf `autostart=false`.
3. **Strike CLI symbols ≠ watchdog symbols ≠ local `live_data_level` seed.** Prod strike generators: `BTC ETH SOL`. Watchdog env: `BTC,ETH,SOL,GOLD,SILVER,WTI`. `live_data_level` is local-only and not migrated on prod.
4. **Single droplet, public Postgres :5432, public app ports, secrets inside `supervisord.conf`.** Redis is the only data port bound to loopback.
5. **CPU headroom is thin.** Load ~7–9 on 8 vCPU with ~12Gi RAM free. The box is CPU-bound, not RAM-bound. May 2026 audit already said this; the disk grew, the core count did not.
6. **Tenant model is half-migrated.** Schemas `users`, `users_0001`, `users_0002`, `users_0003`. Only 0001 is an active Kalshi trader and the only supervised tenant. `REC_SINGLE_USER_MODE=1`. Hardcoded `0001` remains a named backlog item.
7. **Strategy table ≠ AES router.** Three momentum/reverse names exist in code and not in `strategy_list_default`. Unknown strategy strings fall through to Hourly HTC.
8. **Maker Edge and Taker Edge are a second execution path** (own processes, own Kalshi REST in `maker_edge_kalshi.py` / taker agent) beside `trade_executor`.
9. **`win_loss_confirmed` wording in the schema reference is unsafe.** Code + no-fallback rule win.
10. **Schema how-to that tells operators to call `init_database()` for alters is unsafe.** Migrations only.
11. **`docs/DIGITAL_OCEAN_DEPLOYMENT_GUIDE.md` describes a greenfield `deploy_digital_ocean.sh`**, not the current git-pull update path.
12. **GDrive MCP is unsupported for daily work.** Scripts only.
13. **Historical warehouse is local disk + Drive folders**, not Spaces/S3. Product doc already says object storage would be required to sell the data. ToS unresolved.
14. **QBO integration is a nightly residual journal**, not an accounting system of record for trades.
15. **Analytics schema is a pile of dated fingerprint tables** (BTC/ETH/NDX/SPX × percentiles). NDX/SPX are not in the live symbol list.
16. **Public and testing schemas** still hold legacy trade and orderbook experiments.
17. **No-fallback rule** is load-bearing. v4 must not reintroduce spot-as-settlement, stale-cache fills, or dual writers.

---

## 10. Source index

| Topic | Path |
|-------|------|
| Host, cron, backup | `docs/PRODUCTION_HOST.md` |
| Components | `docs/ARCHITECTURE.md` |
| Product | `docs/SYSTEM_BIBLE.md` |
| Ingest | `docs/KALSHI_MARKET_INGEST.md`, `backend/core/market_watchdog/venues/kalshi/ws_ingest.py` |
| Shards | `docs/KALSHI_EXCHANGE_SHARDING.md` |
| Portfolio | `docs/PORTFOLIO_ACCOUNT_SYNC.md` |
| Trade lifecycle | `docs/TRADE_LIFECYCLE_AND_AUTO_STOP_CURRENT.md` |
| Maker / Taker | `docs/MAKER_EDGE_STRATEGY.md`, `docs/TAKER_EDGE_STRATEGY.md` |
| Monitors | `docs/MONITORS_LIST_INFRASTRUCTURE.md` |
| Schema | `docs/MASTER_DB_SCHEMA_REFERENCE.md` |
| Realtime | `docs/REALTIME_BACKBONE.md`, `docs/REDIS_ARCHITECTURE.md` |
| Tenants | `docs/TENANT_TOUCH_REGISTRY.md`, `backend/core/tenant_context.py` |
| Supervisor | `scripts/config/generate_unified_supervisor_config.py` |
| Ports | `backend/core/config/MASTER_PORT_MANIFEST.json` |
| Drive | `docs/GDRIVE_ACCESS.md`, `scripts/gdrive/README.md`, `backend/core/cycle_gdrive_upload.py` |
| Cycle product | `docs/HISTORICAL_CYCLE_DATA_PRODUCT.md` |
| QBO | `backend/bookkeeper/bookkeeper.py`, `backend/bookkeeper/quickbooks/quickbooks_online_rest.py` |
| Releases | `docs/changelog/MASTER_CHANGELOG.md` |
| Backlog already named | `docs/LONG_TERM_INITIATIVES.md` |
| CPU snapshot (stale topology) | `docs/perf-audits/PROD_CPU_RAM_POST_KALSHI_INGEST_REFACTOR_2026-05-22.md` |

---

## 11. Audit limits

- Read-only SSH. No `supervisorctl` restart, no SQL writes, no credential file reads.
- Nginx upstream map not captured.
- QBO `.env` not opened, so production-vs-sandbox realm was not confirmed from disk. Cron user is `0001`.
- Local git dirty tree was not fully diffed. The one schema delta called out is `live_data_level` absent on prod.
- Droplet size/region slug was not pulled from the DigitalOcean API. RAM, disk, and hostname were read from the guest.
- This file is a baseline, not a v4 proposal.
