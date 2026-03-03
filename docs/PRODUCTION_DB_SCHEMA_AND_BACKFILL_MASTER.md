# Production DB: Schema Updates and Backfill — Master Instructions

This document is the single source of truth for:
1. **What we are doing** — new metrics and columns
2. **How we update DB schemas** — where schema changes live and how they are applied
3. **How we backfill data** — logic and scripts
4. **Production runbook** — exact steps for a remote agent to update the production DB the same way

---

## 1. What We Are Doing

### 1.1 Historical price tables (already in place)

- **Tables:** `historical_data.btc_price_history`, `historical_data.eth_price_history` (and optionally ndx/spx).
- **New columns added:** `movement`, `movement_percentile`.
- **Existing columns:** `momentum`, `momentum_percentile`, `volatility`, `volatility_percentile`, OHLCV, etc.
- **How they get populated:** Analytics pipeline (update price logs → generate profiles → assign percentiles). Movement is computed from (H-L)/O and rolling windows; movement_percentile is assigned from `analytics.{symbol}_movement_profile`.
- **Timezone:** All historical price timestamps are **EST** (stored as `timestamp without time zone`).

### 1.2 Trades table (users.trades_0001)

- **New columns added:** `volatility`, `movement`, `movement_percentile`.
- **Existing columns:** `momentum`, `momentum_percentile`, `volatility_percentile`, plus all other trade fields.
- **Intent:** For each trade we store market context at entry: volatility and movement (and their percentiles).
- **New trades (implemented):** `insert_trade()` in `backend/trade_manager.py` reads the **latest row** from `live_data.live_price_log_1s_{symbol}` and writes `volatility`, `volatility_percentile`, `movement`, `movement_percentile` (same pattern as momentum) into the new trade row. So every new trade (manual or auto) gets these at insert time from the live feed.
- **Existing trades:** Backfill from historical price logs via `scripts/backfill_trades_volatility_movement.py` (top-of-minute lookup).

### 1.3 Backfill logic

- **Source:** `historical_data.btc_price_history` and `historical_data.eth_price_history`.
- **Target:** `users.trades_0001` columns `volatility`, `volatility_percentile`, `movement`, `movement_percentile`.
- **Rule:** For each trade, use `symbol` (BTC or ETH), `date`, and `time` (EST). Build the **top-of-minute** timestamp (e.g. 14:32:45 → 14:32:00). Look up that minute in the corresponding historical table and copy the four values into the trade row. Trades with no matching historical row (e.g. outside data range) are skipped.

### 1.4 Live price log tables (1s) — movement columns

- **Tables:** `live_data.live_price_log_1s_btc`, `live_price_log_1s_eth`, `live_price_log_1s_spx`, `live_price_log_1s_ndx`.
- **New columns (all four tables):** `move_1m`, `move_2m`, `move_3m`, `move_4m`, `move_15m`, `move_30m`, `movement`, `movement_percentile`.
- **How they get populated:** The **symbol price watchdog** (`backend/symbol_price_watchdog.py`) writes these on every tick. For each window (1m, 2m, … 30m), high/low/open are derived from ticks in that window in the same table; raw move = (high − low) / open × 100. The weighted composite `movement` uses the same weights as momentum (0.3, 0.25, 0.2, 0.15, 0.05, 0.05). `movement_percentile` is looked up from `analytics.{symbol}_movement_profile` (or latest dated profile table). No backfill script: new data is filled as the watchdog runs after schema/ code deploy.
- **Reference:** Schema and column descriptions in `docs/MASTER_DB_SCHEMA_REFERENCE.md`; change log in `DATABASE_CHANGES_LOG.md`. Test script: `python -m backend.test_watchdog_movement` (from repo root, with project deps). Movement profile tables use column **movement_value** (not momentum_value) for the percentile lookup value.

### 1.5 Strike tables (real-time) — volatility and movement columns

- **Tables:** `live_data.strike_table_hourly_btc`, `strike_table_hourly_eth`, `strike_table_hourly_spx`, `strike_table_hourly_ndx`.
- **New columns (all four tables):** `volatility`, `volatility_percentile`, `movement`, `movement_percentile`.
- **How they get populated:** The **strike table generator** (`backend/strike_table_generator.py`) reads the latest row from `live_data.live_price_log_1s_{symbol}` (same row used for price and momentum) and writes these four values into each strike table row it generates. No backfill: new snapshots get the values when the generator runs after schema/code deploy.
- **Reference:** Schema in `docs/MASTER_DB_SCHEMA_REFERENCE.md`; change log in `DATABASE_CHANGES_LOG.md`. Schema migration: `init_database()` in `backend/core/config/database.py` adds the columns if missing.

### 1.6 Movement profile tables (analytics) — column rename

- **Tables:** `analytics.{symbol}_movement_profile` and `analytics.{symbol}_movement_profile_YYYYMMDD` (e.g. btc, eth).
- **Change:** Column **`momentum_value`** renamed to **`movement_value`** in all movement profile tables. The column holds movement values; the name now matches. Momentum profile tables are unchanged (they keep `momentum_value`).
- **How:** Migration in `init_database()` renames the column. Code: `backend/util/analytics/symbol_profiler.py` (create/insert/assign movement profile) and `backend/symbol_price_watchdog.py` (load_movement_profile) use **`movement_value`**.

---

## 2. How We Update DB Schemas

### 2.1 Where schema changes live

- **File:** `backend/core/config/database.py`
- **Function:** `init_database()`
- **Two mechanisms:**
  1. **CREATE TABLE IF NOT EXISTS** — Defines the full table for **new** databases. New columns are added to this block so fresh installs get them.
  2. **DO $$ ... END $$;** (migration block) — For **existing** databases. Uses `information_schema.columns` to check for each column; if missing, runs `ALTER TABLE ... ADD COLUMN ...`. This is how existing production DBs get new columns without recreating tables.

### 2.2 When schema updates are applied

- **Option A — Via application:** If the application calls `init_database()` on startup or during some init flow, the migration block runs when the app starts and adds any missing columns. (Current main.py startup does not call `init_database()`; it may be called elsewhere or only in tests.)
- **Option B — Explicit run:** Run a one-off script that calls `init_database()` so the migration block runs once.
- **Option C — Manual ALTER:** Run the same `ALTER TABLE` statements directly against the DB (e.g. from psql or a small script). Use this when you need to add columns immediately without deploying code that runs `init_database()`.

### 2.3 Trades table: the three new columns (reference)

For `users.trades_0001`, the migration in `database.py` adds these if they do not exist:

```sql
ALTER TABLE users.trades_0001 ADD COLUMN volatility NUMERIC(10,4);
ALTER TABLE users.trades_0001 ADD COLUMN movement NUMERIC(10,4);
ALTER TABLE users.trades_0001 ADD COLUMN movement_percentile NUMERIC(5,1);
```

The same types are in the CREATE TABLE block for new installs.

---

## 3. How We Backfill Data

### 3.1 Script

- **Path:** `scripts/backfill_trades_volatility_movement.py`
- **Run from repo root:**
  ```bash
  python3 scripts/backfill_trades_volatility_movement.py
  ```
- **Requires:** Project environment (so `backend.core.config.database.get_postgresql_connection` works). No extra CLI args.

### 3.2 What the script does

1. Selects from `users.trades_0001` all rows where:
   - `symbol` is BTC or ETH (case-insensitive),
   - and at least one of `volatility`, `volatility_percentile`, `movement`, `movement_percentile` is NULL.
2. For each such row:
   - Builds EST top-of-minute from `date` and `time` (handles both DB date/time types and text).
   - Maps symbol to table: BTC → `historical_data.btc_price_history`, ETH → `historical_data.eth_price_history`.
   - Selects from that table the row with `timestamp = <that minute>`.
   - Updates the trade row with the four values from the historical row (only filling NULLs via COALESCE).
3. Commits once at the end. Reports: updated count, skipped (no timestamp), skipped (no historical row), errors.

### 3.3 When to run backfill

- After the three columns exist on production.
- After historical price tables have been populated with volatility/movement (analytics pipeline has been run for the date range of your trades).
- Can be run again later; it only fills NULLs, so re-running is safe and will pick up new trades or previously missing historical data.

---

## 4. Production Runbook (Remote Agent)

Use this as the single set of instructions to bring production in line with the above: same schema and same backfill.

### 4.1 Prerequisites

- Access to the production server and the application repo (codebase at the same version that includes the schema and backfill changes).
- PostgreSQL connection for the production DB (env or config used by the app: `get_postgresql_connection()`).
- Python environment that can run the app’s backend (so `backend.core.config.database` and the script’s imports work).

### 4.2 Step 1: Ensure schema (add columns if missing)

**Option 1 — Run init_database (recommended)**  
From the **project root** on the server:

```bash
cd /path/to/repo
python3 -c "
from backend.core.config.database import init_database
ok, msg = init_database()
print('OK:', ok, msg)
"
```

This runs all migrations in `database.py`, including: new columns on `users.trades_0001`; movement columns on live 1s price log tables; volatility and movement columns on strike tables (btc, eth, spx, ndx). If columns already exist, the migration block does nothing.

**Option 2 — Add columns manually**  
If you cannot run Python or prefer SQL only, connect to the production DB and run:

```sql
-- Only run each if the column does not exist (check information_schema or run one-by-one and ignore “already exists” errors).
ALTER TABLE users.trades_0001 ADD COLUMN IF NOT EXISTS volatility NUMERIC(10,4);
ALTER TABLE users.trades_0001 ADD COLUMN IF NOT EXISTS movement NUMERIC(10,4);
ALTER TABLE users.trades_0001 ADD COLUMN IF NOT EXISTS movement_percentile NUMERIC(5,1);
```

(If your Postgres version does not support `ADD COLUMN IF NOT EXISTS`, check for the column in `information_schema.columns` first, then run the corresponding `ALTER TABLE ... ADD COLUMN ...` only when missing.)

### 4.3 Step 2: Confirm historical data

- Ensure the analytics pipeline has been run for production so that `historical_data.btc_price_history` and `historical_data.eth_price_history` have `volatility`, `volatility_percentile`, `movement`, and `movement_percentile` populated for the date range that covers your trades.
- If not, run the usual analytics steps (e.g. update price logs, generate profiles, assign percentiles) before backfilling trades.

### 4.4 Step 3: Run the backfill

From the **project root**:

```bash
cd /path/to/repo
python3 scripts/backfill_trades_volatility_movement.py
```

- Expect output like: `Updated: N, skipped (no timestamp): 0, skipped (no historical row): M, errors: 0`.
- Some trades may be skipped (no historical row at that minute); that is expected if data is missing for that minute or symbol.

### 4.5 Step 4: Verify (optional)

- Spot-check a few trades that should have been updated:
  ```sql
  SELECT id, symbol, date, time, volatility, volatility_percentile, movement, movement_percentile
  FROM users.trades_0001
  WHERE symbol IN ('BTC', 'ETH')
  ORDER BY id DESC
  LIMIT 20;
  ```
- Confirm that the new columns are non-NULL where you expect and that values look consistent with the historical tables for the same minute.

---

## 5. Summary Table

| What | Where | How |
|------|--------|-----|
| Schema (new columns on trades) | `backend/core/config/database.py` (`init_database`) | Run `init_database()` or run the ALTERs in §4.2 |
| Historical tables (movement columns) | Already added via analytics pipeline / migration | No extra step if pipeline has been run |
| Live 1s tables (movement columns) | `backend/core/config/database.py`; written by watchdog | Schema via `init_database()`; values filled on each tick by `symbol_price_watchdog.py` (no backfill) |
| Strike tables (volatility/movement columns) | `backend/core/config/database.py`; written by generator | Schema via `init_database()`; values filled when `strike_table_generator.py` runs (reads from live 1s price log) |
| Backfill trades from historical | `scripts/backfill_trades_volatility_movement.py` | Run script from repo root (§4.4) |
| New trades vol/movement at insert | `backend/trade_manager.py` `insert_trade()` | Reads latest `live_price_log_1s_{symbol}` row; no backfill for new trades |
| Movement profile column | `analytics.*_movement_profile*` | Column is **movement_value** (renamed from momentum_value); migration in `init_database()`; profiler + watchdog use it |
| Doc / schema reference | `docs/MASTER_DB_SCHEMA_REFERENCE.md` | Updated for new columns |
| Live movement test | `backend/test_watchdog_movement.py` | Run `python -m backend.test_watchdog_movement` from repo root |

---

## 6. Real-time fill for new trades (implemented)

`insert_trade()` in `backend/trade_manager.py` fills volatility and movement at insert:

- Reads the **latest row** from `live_data.live_price_log_1s_{symbol}` (same query used for price and momentum).
- Writes into the new trade row: `symbol_open`, `momentum`, `momentum_percentile`, `momentum_5s_avg`, **`volatility`**, **`volatility_percentile`**, **`movement`**, **`movement_percentile`**.
- No payload fields required; all from live feed. Applies to both manual and auto entry.
- Existing trades with NULLs: use backfill script (§3, §4.4).
