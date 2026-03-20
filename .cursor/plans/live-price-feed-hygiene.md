# Live price feed hygiene (BTC/ETH)

**Goal:** Reduce watchdog CPU and simplify code paths for the critical live price pipeline by making Postgres the canonical place that keeps `live_data.live_symbol_status` synchronized from the 1s log tables.

**Scope**
- In-scope: BTC/ETH 1s live price logs (`live_data.live_price_log_1s_btc`, `live_data.live_price_log_1s_eth`) and the derived snapshot table (`live_data.live_symbol_status`).
- Out-of-scope: SPX/NDX (kept as-is).

## Current status
- Local implementation and trigger sync verification done.
- Production rollout pending.

## What changed (local)
1. **DB migrations**
   - `20260318_1300_live_symbol_status_sync_from_live_price_logs`
     - Adds Postgres trigger functions and triggers to upsert `live_data.live_symbol_status` from `live_price_log_1s_btc` / `live_price_log_1s_eth`.
   - `20260318_1310_live_symbol_status_unique_on_symbol_non_partial`
     - Ensures `live_data.live_symbol_status(symbol)` has a full-table unique index so the trigger upsert can reliably use `ON CONFLICT (symbol)`.
   - `20260318_1405_live_symbol_status_db_notify_trigger`
     - Adds DB NOTIFY trigger on `live_data.live_symbol_status` so the Redis websocket emits `db_change` events for the standalone live UI.

2. **Code**
   - `backend/symbol_price_watchdog.py`: BTC/ETH no longer perform the Python-side dual write into `live_data.live_symbol_status`.
   - `backend/core/config/database.py` and `docs/MASTER_DB_SCHEMA_REFERENCE.md`: updated to include the new uniqueness guarantee for `live_symbol_status(symbol)` on fresh DB init.
   - `backend/core/stream_registry.py`: added stream mapping for `live_data.live_symbol_status` → `live_symbol_status`.
   - `backend/main.py`: added `GET /api/live_symbol_status_snapshot` for the test UI.
   - `frontend/tabs/live_symbol_status_test.html`: standalone UI subscribes to `/ws/db_changes` and refreshes on `live_symbol_status` signals.

## Local verification
- Insert/upsert into `live_data.live_price_log_1s_btc` updates `live_data.live_symbol_status` for `symbol='BTC'`.
- Insert/upsert into `live_data.live_price_log_1s_eth` updates `live_data.live_symbol_status` for `symbol='ETH'`.
- Websocket emits `db_change` events when `live_symbol_status` rows update.
- Opening `/tabs/live_symbol_status_test.html` shows real-time updates for the requested fields.

## Production checklist (when you are ready)
1. Apply DB migrations in order (project root):
   - `PYTHONPATH=$(pwd) venv/bin/python scripts/db/run_migration.py up 20260318_1300_live_symbol_status_sync_from_live_price_logs`
   - `PYTHONPATH=$(pwd) venv/bin/python scripts/db/run_migration.py up 20260318_1310_live_symbol_status_unique_on_symbol_non_partial`
   - `PYTHONPATH=$(pwd) venv/bin/python scripts/db/run_migration.py up 20260318_1405_live_symbol_status_db_notify_trigger`
2. Restart `redis_switchboard` so it loads the updated stream registry mapping.
3. Restart `main_app` so the snapshot endpoint is available.
4. Restart the watchdog services so they only write the 1s log tables:
   - `supervisorctl restart symbol_price_watchdog_btc`
   - `supervisorctl restart symbol_price_watchdog_eth`
5. Verify:
   - `live_data.live_symbol_status` changes within the same tick after a change to `live_data.live_price_log_1s_btc` / `_eth`.
   - Open `/tabs/live_symbol_status_test.html` and confirm values refresh on `live_symbol_status` db_change events.

## Completion criteria
- Proved continuous 1s synchronization for BTC and ETH with no exceptions and no duplicate rows in `live_symbol_status`.
- Proved `redis_switchboard` emits `db_change` for `live_symbol_status` and the standalone UI reflects updates in real time.

