# Implementation plan: Pin open-trade markets across rotation (monitor_confirmed)

**Goal:** Ensure ATS continues to have a price source for every open trade through its full lifecycle, so real-time monitoring (and thus `monitor_confirmed`) reflects actual tracking. No change to when or how we enter or exit trades.

**Root cause (recap):** On event rotation, `kalshi_market_watchdog` TRUNCATEs `live_data.market_kalshi_{interval}_{symbol}` and repopulates with the new event only. Tickers for open trades from the previous event disappear. ATS’s `get_current_closing_price_for_trade()` then returns None, the monitoring loop skips updates, and at close `high_price == low_price` → `monitor_confirmed = FALSE`.

**Approach:** Before TRUNCATE, identify tickers that belong to open/pending trades and that exist in the current table; save those rows; after writing the new event, re-insert the saved rows so ATS still sees them until those trades close.

---

## 1. Data flow (per watchdog instance)

Each watchdog process owns one `(SYMBOL, INTERVAL)` and one table: `live_data.market_kalshi_{interval}_{symbol}` (e.g. `market_kalshi_hourly_btc`).

**On rotation (when `previous_event_ticker != event_ticker`):**

1. **Compute preserve set**
   - Open-trade tickers for this symbol:  
     `SELECT DISTINCT ticker FROM users.trades_0001 WHERE status IN ('pending', 'open') AND symbol = %s AND ticker IS NOT NULL`
   - Restrict to tickers that exist in the current table (so we only keep rows that belong to this table):  
     `SELECT market_ticker FROM live_data.market_kalshi_{interval}_{symbol} WHERE market_ticker IN (... open tickers ...)`
   - If the preserve set is empty, skip steps 2–4 (current behavior: TRUNCATE + new event only).

2. **Read rows to preserve**
   - `SELECT * FROM live_data.market_kalshi_{interval}_{symbol} WHERE market_ticker IN (preserve_tickers)`
   - Store rows in memory (list of dicts or tuples; include all columns needed for re-insert).

3. **TRUNCATE**
   - Same as today: `TRUNCATE TABLE live_data.market_kalshi_{interval}_{symbol}`.

4. **Write new event**
   - Unchanged: `save_market_data_to_postgresql(event_ticker, filtered_markets, SYMBOL, INTERVAL)`.

5. **Re-insert preserved rows**
   - For each saved row, `INSERT INTO live_data.market_kalshi_{interval}_{symbol} (event_ticker, market_ticker, market, strike, yes_bid, yes_ask, no_bid, no_ask, last_price, yes_bid_dollars, yes_ask_dollars, no_bid_dollars, no_ask_dollars, last_price_dollars, volume, volume_24h, open_interest, liquidity, updated_at) VALUES (...)` using the saved values. Do not set `id` (let SERIAL assign). The unique constraint is `(event_ticker, market_ticker)`; preserved rows keep the *previous* event_ticker, so they do not conflict with new-event rows.

Result: the table contains (new event’s markets) + (preserved rows for open trades from the previous event). ATS continues to find those tickers and can keep updating high/low until the trades close.

---

## 2. Where to implement

**File:** `backend/kalshi_market_watchdog.py`

**Locations:**
- **New helper:** `get_open_trade_tickers_for_table(connection, table_name, symbol)`  
  Returns set of tickers: open/pending trades for `symbol` that exist in `table_name`.  
  - Query 1: `SELECT DISTINCT ticker FROM users.trades_0001 WHERE status IN ('pending', 'open') AND symbol = %s AND ticker IS NOT NULL`.  
  - Query 2: `SELECT market_ticker FROM live_data.{table_name} WHERE market_ticker IN (%s, ...)` (parameterize).  
  - Return intersection (tickers that are both open and in the table).

- **New helper:** `fetch_rows_for_tickers(connection, table_name, tickers)`  
  Returns list of rows (e.g. list of dicts keyed by column name) for `SELECT * FROM live_data.{table_name} WHERE market_ticker IN (...)`.

- **New helper:** `reinsert_preserved_rows(connection, table_name, rows)`  
  For each row, INSERT with explicit column list (all columns except `id` and `created_at` if we want to avoid overwriting; or include them if the table allows). Use the same column set as `save_market_data_to_postgresql` plus `event_ticker` from the row.

- **Main loop (rotation block):**  
  Before `cursor.execute(f"TRUNCATE TABLE {table_name}")`:  
  1. Call `get_open_trade_tickers_for_table(connection, table_name, SYMBOL)`.  
  2. If non-empty, call `fetch_rows_for_tickers(connection, table_name, preserve_tickers)` and hold in a variable.  
  After `save_market_data_to_postgresql(...)` (which uses its own connection):  
  3. If we have preserved rows, open a new connection, call `reinsert_preserved_rows(connection, table_name, preserved_rows)`, commit, close.  
  4. Log: e.g. "Preserved N rows for open trades across rotation."

**DB access:** The watchdog already uses `connect_database()`. Ensure it can read `users.trades_0001` (same DB). If the project uses a single DB for users and live_data, no change. If not, the plan assumes the watchdog’s connection has read access to `users.trades_0001`.

---

## 3. Table schema (reference)

From `create_market_kalshi_table` and `save_market_data_to_postgresql`:

- Columns: `id`, `event_ticker`, `market_ticker`, `market`, `strike`, `yes_bid`, `yes_ask`, `no_bid`, `no_ask`, `last_price`, `yes_bid_dollars`, `yes_ask_dollars`, `no_bid_dollars`, `no_ask_dollars`, `last_price_dollars`, `volume`, `volume_24h`, `open_interest`, `liquidity`, `created_at`, `updated_at`.
- Unique: `(event_ticker, market_ticker)`.
- Re-insert: use all columns except `id` (and optionally `created_at`) so the row is identical for ATS’s reads; new `id` is fine.

---

## 4. Edge cases and safety

- **No open trades:** preserve set is empty; no extra reads/writes; behavior matches current (TRUNCATE + new event only).
- **Open trades but none in this table:** e.g. all open trades are 15m and this process is hourly_btc; preserve set is empty after intersection. No re-insert.
- **Many open tickers:** we only re-insert rows we already had; no Kalshi API calls; bounded by number of open positions.
- **Stale prices on preserved rows:** preserved rows keep the last values written before rotation. ATS will use them so it does not skip; high/low will still move if the preserved bid/ask are used. If desired later, we could add a background refresh of preserved tickers from the API; not in scope for this plan.
- **Restart during rotation:** if the process dies after TRUNCATE but before re-insert, we lose the preserved rows for that run; open trades would see None until the next rotation or until they close. Acceptable; no DB corruption.

---

## 5. Verification

- **Logs:** On each rotation where the preserve set is non-empty, log count of preserved tickers and table name.
- **monitor_confirmed:** Over 1–2 weeks after deploy, compare 7-day `monitor_confirmed = FALSE` counts (by monitor/strategy) to pre-change baseline; expect a drop for BTC Momentum Breakout and any other strategy that frequently had open positions across rotation.
- **No behavior change:** Confirm entry/exit timing and rules are unchanged; only the availability of market rows for ATS changes.

---

## 6. Rollout

1. Implement helpers and main-loop changes in `kalshi_market_watchdog.py`.
2. Run locally (or on a dev instance) through at least one rotation with an open trade and confirm the table contains both new-event and preserved rows and ATS continues to update that trade.
3. Deploy to production; leave instrumentation (e.g. preserve count log) in place for at least one week.
4. Review `monitor_confirmed` report and logs; document outcome in `docs/DIAGNOSIS_MONITOR_CONFIRMED_FALSE.md` or a short follow-up note.

---

## 7. Optional: instrumentation only (no pinning)

If we want to validate the “open trade tickers” set before full implementation, add a **logging-only** pass: on rotation, compute and log the preserve set (and count) without re-inserting. That confirms we’re correctly identifying which tickers would have been preserved and that the intersection with the current table is non-empty when we expect it.
