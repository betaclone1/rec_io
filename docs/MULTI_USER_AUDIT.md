# Multi-user migration audit (phase 0)

Inventory of tenant-scoped vs global references. Generated for the siloed-schema initiative; re-run ripgrep when adding features.

## Environment and ports

| Symbol | Location | Classification |
|--------|----------|----------------|
| `REC_POOL_USER_NUMBER` | [`backend/core/port_config.py`](backend/core/port_config.py) | Tenant default for supervisord names; must align with `REC_USER_NO` per process |
| `default_pool_user_number()` | `port_config.py` | **Dev/single-user fallback** only when `REC_SINGLE_USER_MODE=1` |
| `pool_user_for_unified_aes_ats()` | `port_config.py` | **Must not** pick arbitrary first user in multi-user; superseded by per-user supervisor blocks |
| `user_scoped_service_name()` | `port_config.py` | Uses pool user number for manifest keys |

## PostgreSQL schema `users` → `users_<user_no>`

| Area | Approx. hits (Apr 2026) | Notes |
|------|-------------------------|--------|
| [`backend/core/config/database.py`](backend/core/config/database.py) | ~140 `users.` | Bootstrap DDL; must use [`tenant_context`](backend/core/tenant_context.py) |
| [`backend/trade_manager.py`](backend/trade_manager.py) | ~138 | All queries tenant-qualified |
| [`backend/active_trade_supervisor.py`](backend/active_trade_supervisor.py) | ~96 | Worker: `REC_USER_SCHEMA` required in multi-user |
| [`backend/main.py`](backend/main.py) | ~97 | API: session → tenant |
| [`backend/kalshi_account_sync_ws.py`](backend/kalshi_account_sync_ws.py) | ~41 | Credentials path + DB |
| [`backend/auto_entry_supervisor.py`](backend/auto_entry_supervisor.py) | ~35 | AES pool |
| Other `backend/*.py` + `scripts/*.py` | Hundreds | Incremental refactor; prefer `TenantContext.ut()` |

**Global schemas (unchanged):** `system`, `live_data`, `historical_data`, `testing`, `backtest`, `archive`.

## Auth and filesystem

| Pattern | Location | Action |
|---------|----------|--------|
| `user_0001` paths | `main.py` (`AUTH_TOKENS_FILE`, `DEVICE_TOKENS_FILE`) | Parameterize by `user_no` from session |
| `system.master_users` (by `user_no` / session slot) | `main.py`, auth | Canonical user row; `kalshi_user_id` and credentials live here, not per-tenant `user_info_*` tables |
| `fetch_session_master_user_credentials` | [`backend/web/session_user_credentials.py`](backend/web/session_user_credentials.py) | Reads `system.master_users` for the session slot |

## Supervisor

| File | Issue |
|------|--------|
| [`scripts/config/generate_unified_supervisor_config.py`](scripts/config/generate_unified_supervisor_config.py) | Queries `users.monitor_list_0001` only; must loop active tenants and set `REC_USER_SCHEMA` / `REC_USER_NO` per program block |

## NOTIFY / realtime

| Artifact | Notes |
|----------|--------|
| [`scripts/migrations/20260401_1600_trades_0001_rec_io_db_notify.up.sql`](../scripts/migrations/20260401_1600_trades_0001_rec_io_db_notify.up.sql) | Trigger on `users.trades_0001`; after schema rename becomes `users_0001.trades_0001` |
| [`backend/redis_switchboard.py`](backend/redis_switchboard.py) | Single `LISTEN` channel; payload should include `pg_schema` or `user_no` for WS fanout filtering |
| [`backend/core/stream_registry.py`](backend/core/stream_registry.py) | Document per-tenant stream naming where applicable |

## Frontend / mobile

| Files | Notes |
|-------|--------|
| `frontend/tabs/dashboard.html`, `dashboard_mobile.html` | Hardcoded `0001` in API calls in places; must send session cookie/token only; server resolves tenant |
| `trade_history*.html`, `trade_monitor*.html` | Same |

## Migrations (historical)

Existing `.up.sql` files reference `users.`; **already applied** on prod keep history. **New** migrations should use tenant-aware patterns or target `users_0001` explicitly when patching the primary install.

## Classification shorthand

- **T**: Must use `TenantContext` / `REC_USER_SCHEMA`
- **G**: Global (`system`, `live_data`, …)
- **D**: Dev-only default allowed when `REC_SINGLE_USER_MODE=1`

## Paper-only tenants (implemented)

- **Supervisor**: `generate_unified_supervisor_config.py` checks `backend/data/users/user_<NNNN>/credentials/kalshi-credentials/prod/kalshi.pem` and `.env`. If missing, sets `REC_PAPER_ONLY_USER=1` and **`autostart=false`** for `trade_executor_<NNNN>` and `kalshi_account_sync_<NNNN>`.
- **Runtime**: `trade_executor.py` skips live Redis consumer loops when `REC_PAPER_ONLY_USER=1`. `kalshi_account_sync_ws.py` exits `main()` immediately in that mode.
- **UX**: Monitors still default to paper; live paths require prod Kalshi credentials on disk for that user.
