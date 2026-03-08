# Diagnosis: Simulated and Paper Trade Duplicates (2026-03-07)

## Observed

- **Simulated:** 63,923 rows in `trades_simulated_0001`; many groups with **76 duplicates** (same date, contract, strike, side). Example: ETH 7:45pm, $1,960, Y → 75 from mon_0001_10026, 1 from mon_0001_10009.
- **Paper:** Duplicate paper trades in `trades_0001` (e.g. 9x same ETH 9am / mon_10026 / $1,990 / N).

## Root causes

### 1. Simulated duplicates

**Cause:** `is_strike_already_simulated_traded()` only looks for rows with `status IN ('open', 'pending')` and `(monitor, ticker, side)`. It does **not** include **contract** or **date**.

When the 15m expiration job **closes** a simulated trade (`status = 'closed'`), the next simulated scan no longer finds an "open" row for that (monitor, ticker, side). So it inserts again for the same 15m window. Scans run every ~90s; after each :00/:15/:30/:45 close we get a new insert. Result: many rows per (date, contract, strike, side) per monitor (e.g. 75 in one day).

**Fix:** Treat "already traded" as: **any** row (open or closed) for this **monitor + date + contract + strike + side**. That limits to one sim trade per 15m window per monitor per strike/side.

### 2. Paper trade duplicates

**Cause:** `is_strike_already_traded()` (used before inserting into `trades_0001`) uses **POSTGRES_HOST, POSTGRES_DB, POSTGRES_USER, POSTGRES_PASSWORD**. Trade_manager uses **DB_*** via `get_postgresql_connection()`. If production sets only `DB_*` (e.g. in supervisord), `POSTGRES_*` may be unset and default to `localhost` / `rec_io_db` — a different host or instance. The duplicate check then runs against the wrong DB and does not see rows trade_manager just wrote, so it allows duplicate paper inserts.

**Fix:** Use the same connection as trade_manager: `get_db_connection()` (i.e. `get_postgresql_connection()` from `backend.core.config.database`) in `is_strike_already_traded()` instead of a separate `psycopg2.connect(**postgres_config)` with POSTGRES_*.

## Summary

| Issue | Cause | Fix |
|-------|--------|-----|
| Simulated tens of thousands of duplicates | Duplicate check only (monitor, ticker, side) + open/pending; closed rows allow re-insert for same contract | Check for any row (open or closed) per monitor + **date + contract** + strike + side |
| Paper trade duplicates on live monitors | `is_strike_already_traded` uses POSTGRES_*; trade_manager uses DB_* → different DB | Use `get_db_connection()` in `is_strike_already_traded()` |

## Fixes applied

1. **auto_entry_supervisor.py**
   - `is_strike_already_simulated_traded`: now requires `date` and `contract` in `strike_data` and checks for **any** row (no status filter) with `(monitor, date, contract, strike, side)`. Caller passes `date_str` and `contract_str` (next 15m boundary) and formatted strike.
   - `is_strike_already_traded`: now uses `get_db_connection()` (same as trade_manager) instead of POSTGRES_*; single query with `(monitor, ticker, side)`.

2. **trade_manager.py**
   - `insert_simulated_trade`: before INSERT, runs a SELECT for existing row with `(monitor, date, contract, strike, side)`; if found, returns that id and skips insert (server-side duplicate guard).

## After deploy

- Run the dedupe script again to clean existing duplicate simulated rows:  
  `PYTHONPATH=$(pwd) venv/bin/python backend/util/dedupe_simulated_trades.py`
- Restart application services so all supervisors and trade_manager load the new logic.
