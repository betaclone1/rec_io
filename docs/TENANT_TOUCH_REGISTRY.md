# Tenant touch registry (active tree)

Inventory of **who** may touch PostgreSQL tenant schemas `users_NNNN` and how. Regenerate hints with:

```bash
PYTHONPATH=$(pwd) python3 scripts/db/scan_tenant_touch.py --json scripts/db/output/tenant_touch_scan.json
```

**Scope:** `backend/`, `scripts/` (excluding `scripts/archive*`), `tests/`. **Out of scope for refactors:** `archive/`, `.pre-pull-backup*`, `scripts/migrations/*.sql` (catalog separately as platform DDL).

**Exemption (CI):** same-line `# tenant-touch-exempt: <reason>` — use rarely; see `scripts/ci/check_global_tenant_touch.py`.

---

## Invariant (summary)

| Layer | May touch `users_*` tables? | Connection / binding |
|-------|----------------------------|----------------------|
| Global daemon (market ingest, strike WS, symbol price, redis_switchboard) | **No DML**; read-only cross-tenant **SELECT** only where documented (e.g. lifecycle subscription planning) | `get_system_postgresql_connection()` / `SystemThreadedConnectionPool` |
| Per-user supervised worker | **Yes** (one schema) | `REC_USER_SCHEMA` / `REC_USER_NO` + `get_postgresql_connection()` |
| HTTP (`main`, `read_api`) | **Yes** (request user only) | `request_tenant_user_no` + `get_postgresql_connection()` |
| Operator script | **Yes** when explicitly scoped | `--user-no` / `REC_USER_NO` + `backend/core/tenant_script_args.py` |
| `init_database()` | **Yes** (default tenant bootstrap only) | Tenant connection + `default_pg_schema_for_init()` |

---

## Supervisor: `env_global` vs `env_u`

From [`scripts/config/generate_unified_supervisor_config.py`](../scripts/config/generate_unified_supervisor_config.py):

| Programs | Environment | Notes |
|----------|-------------|--------|
| `main_app`, `read_api`, `redis_switchboard`, `symbol_price_watchdog_*`, `market_watchdog_ws_*`, `strike_table_generator_ws_*`, `system_monitor`, `cascading_failure_detector` | `env_global` (`REC_SINGLE_USER_MODE=1`, no per-user schema) | Must use **system** DB connection for writes; see global module list in `scripts/ci/check_global_tenant_touch.py` |
| `trade_manager_*`, `trade_executor_*`, `kalshi_account_sync_*`, `monitor_manager_*`, `auto_entry_supervisor_*`, `active_trade_supervisor_*`, **`kalshi_lifecycle_consumer_*`** | `env_u` (`REC_USER_SCHEMA=users_NNNN`) | Tenant-bound |

**Kalshi lifecycle:** `market_watchdog_ws` publishes to `REDIS_CHANNEL_KALSHI_LIFECYCLE_TRADES`; each `kalshi_lifecycle_consumer_<NNNN>` applies outcomes in its tenant only.

---

## Cross-tenant read-only (exception)

[`backend/core/kalshi_lifecycle_pending_tickers.py`](../backend/core/kalshi_lifecycle_pending_tickers.py) — discovers `(users_NNNN, trades_NNNN)` via `information_schema` and runs **SELECT** unions so the global watchdog can plan lifecycle WebSocket subscriptions. **No updates.** Trade row updates remain in [`backend/core/kalshi_lifecycle_trade_outcome.py`](../backend/core/kalshi_lifecycle_trade_outcome.py) via per-tenant consumers.

---

## Representative file tiers (non-exhaustive)

| Path | Tier | Mutates `users_*`? | Binds tenant via |
|------|------|--------------------|------------------|
| `backend/core/config/database.py` | `init_bootstrap` | Y (default schema DDL) | `default_pg_schema_for_init()` |
| `backend/trade_manager.py` | `tenant_worker` | Y | `REC_USER_SCHEMA` |
| `backend/monitor_manager.py` | `tenant_worker` | Y | `REC_USER_SCHEMA` |
| `backend/main.py` + `backend/web/routers/*` | `http_multi_tenant` | Y (where routes implement writes) | request token / `tenant_user_no` |
| `backend/read_api.py` | `http_multi_tenant` | varies | request / params |
| `backend/market_watchdog_ws.py` | `global_daemon` | N (publish + read-only pending tickers helper) | n/a (system pool) |
| `backend/strike_table_generator_ws.py` | `global_daemon` | N | system connection |
| `backend/symbol_price_watchdog.py` | `global_daemon` | N | system connection |
| `backend/redis_switchboard.py` | `global_daemon` | N | system connection |
| `backend/kalshi_lifecycle_trade_consumer.py` | `tenant_worker` | Y | `REC_USER_SCHEMA` |
| `scripts/db/*.py` | `operator_script` | often Y | add `--user-no` over time |
| `tests/unit/test_tenant_sql_isolation.py` | `test` | n/a | n/a |

**P0 follow-ups (batch):** remaining `scripts/diagnostics/*` and `scripts/db/*` that still hardcode `users.trades_0001` should gain `--user-no` (pattern: [`scripts/db/backfill_paper_trade_fees.py`](../scripts/db/backfill_paper_trade_fees.py), [`scripts/inspect_trade_and_monitor.py`](../scripts/inspect_trade_and_monitor.py)).

---

## Migrations / init

See [TENANT_INIT_AND_MIGRATIONS.md](TENANT_INIT_AND_MIGRATIONS.md).

---

## Legacy trees

`archive/`, `.pre-pull-backup*`, and `scripts/archive*` are **not** kept in this registry row-by-row; treat as historical only.
