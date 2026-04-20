# Diagnosis: Increase in monitor_confirmed = FALSE

**Purpose:** Diagnose why more trades are closing with `monitor_confirmed = FALSE` (i.e. active_trade_supervisor not consistently picking up and tracking trades while live). **No patches** — diagnosis only.

**Last run:** 2026-03-09 — DB and logs inspected.

---

## 0. Evidence summary (from DB and logs)

**Today’s failures (2026-03-09):** 6 trades with `monitor_confirmed = FALSE`, all on **monitor 10031 (Momentum Breakout)**. All have **high_price = low_price** (same value, not NULL), and closed at :00/:02 (12:00, 13:00, 14:00). So the trade **was** in ATS `active_trades`, but the monitoring loop **never updated** high/low.

**Log evidence (ATS 10031):**
- `⚠️ Market not found for ticker: KXBTCD-26MAR0915-T68249.99`
- `⚠️ Could not get market price for trade 13983 (KXBTCD-26MAR0915-T68249.99), skipping`

So when the ticker is missing from the Kalshi market snapshot, ATS skips the update and high/low stay at `buy_price` → at expiration `high_price == low_price` → `monitor_confirmed = FALSE`.

**Older failures:** Many rows with `high_price = low_price = NULL` (e.g. monitors 10002, 10009, 10014, 10018) — trade **never** in ATS `active_trades` when trade_manager called `get_high_low_prices_from_active_trades` (notification/add path failed or wrong monitor). Separate failure mode from “market not found”.

**Logging work impact:** No change to ATS monitoring logic or to when we `continue` (skip). Only change in trade_manager’s `get_high_low_prices_from_active_trades` is use of `log()`; if that call ever raised we’d return `(None, None)` and write NULL high/low — but today’s 6 have non-NULL high==low, so that path is not responsible for today’s failures. The uptick is not explained by the logging code paths we added; the underlying cause is event rotation + TRUNCATE (see §3.2).

---

## 1. What monitor_confirmed means

- **Source of truth:** `users.trades_<slot>.monitor_confirmed` (boolean).
- **Set when:** On trade close (and on expiration), in `trade_manager.update_trade_status_with_ret_pct()` (and in the 5‑min expiration job).
- **Rule:** `monitor_confirmed = (high_price != low_price)`. So:
  - **TRUE** when ATS successfully tracked the trade and updated `high_price` / `low_price` (they diverge over the trade’s life).
  - **FALSE** when:
    - `high_price == low_price` (e.g. both still equal to initial `buy_price` because ATS never updated them), or
    - `high_price` / `low_price` are NULL (trade never found in ATS `active_trades` when closing).

So an increase in `monitor_confirmed = FALSE` means either:

- ATS **never had** the trade in its `active_trades` table (notification or add path failed), or  
- ATS **had** the trade but **never updated** `high_price`/`low_price` (monitoring loop not running or not succeeding for that trade).

---

## 2. Pipeline (how high_price / low_price get set)

### 2.1 Trade lifecycle and ATS

1. **Trade created**  
   `trade_manager` inserts into `users.trades_<slot>` with `status = 'pending'` and a `monitor` (e.g. `mon_0001_10026`).

2. **Notification "pending"**  
   `trade_manager` calls `notify_active_trade_supervisor_direct(trade_id, ticket_id, "pending")`:
   - Reads `monitor` from `trades_0001` for that `trade_id`.
   - Resolves ATS port with `get_monitor_port("active_trade_supervisor", monitor_suffix)` (e.g. `0001_10026`).
   - POSTs to `http://localhost:{port}/api/trade_manager_notification` with `status: "pending"`.
   - ATS handler: if `monitor_identifier` matches this ATS instance, calls `add_pending_trade(trade_id, ticket_id)`; else ignores.

3. **Notification "open"**  
   When the trade is confirmed (executor fill or paper trade), `trade_manager` calls `notify_active_trade_supervisor_direct(..., "open")`:
   - Same port resolution and POST.
   - ATS: `confirm_pending_trade(trade_id, ticket_id)`; if that fails (no pending row), `add_new_active_trade(trade_id, ticket_id)`.
   - On add, ATS inserts into **`users.active_trades_{user}_{monitor_id}`** (e.g. `active_trades_0001_10026`) with `high_price = low_price = buy_price`.

4. **Monitoring loop (ATS)**  
   ATS runs a **monitoring thread** that:
   - Selects rows from `users.active_trades_{user}_{monitor}` where `status = 'active'`.
   - For each trade: gets `get_current_symbol_price(symbol)` and `get_current_closing_price_for_trade(ticker, side)`.
   - Computes `position_value = 1 - current_market_price`, then `new_high = max(current_high, position_value)`, `new_low = min(current_low, position_value)`.
   - **UPDATE**s that row’s `high_price`, `low_price`, and other monitoring fields.

   If **either** `get_current_symbol_price` or `get_current_closing_price_for_trade` returns **None**, the loop **skips** that trade for that cycle (no UPDATE). So high/low stay at initial `buy_price` for that trade.

5. **On close**  
   `trade_manager.confirm_close_trade` (or expiration path):
   - Calls **`get_high_low_prices_from_active_trades(trade_id)`**:
     - Reads `monitor` from `trades_0001`, builds table name `users.active_trades_{user}_{monitor_id}`.
     - `SELECT high_price, low_price FROM users.{that_table} WHERE trade_id = %s`.
   - Then calls `update_trade_status_with_ret_pct(..., high_price, low_price)` and sets `monitor_confirmed = (high_price != low_price)`.
   - **Then** notifies ATS `"closed"`; ATS removes the row from `active_trades`.

So high/low are read **before** ATS is told to remove the trade — no race on removal.

---

## 3. Failure modes (why monitor_confirmed = FALSE)

### 3.1 Trade never in ATS active_trades (high/low = NULL or missing row)

- **Notification never received**
  - **Port wrong:** `get_monitor_port("active_trade_supervisor", monitor_suffix)` returns a port that isn’t this monitor’s ATS (e.g. stale or wrong config). POST goes to wrong process; correct ATS never sees it.
  - **ATS down or restart:** ATS was down or restarted around the time of "pending" / "open". Request fails (connection refused / timeout); trade_manager may log "ACTIVE TRADE SUPERVISOR ERROR" or "ERROR SENDING NOTIFICATION".
  - **Timeout:** POST times out (e.g. 5s); ATS might process it late or not at all.
- **ATS rejects or ignores**
  - **Wrong monitor in payload:** If `monitor_identifier` in the request doesn’t match this ATS’s `MONITOR_IDENTIFIER`, ATS returns 200 with "ignored". Logs: "DIRECT NOTIFICATION: Ignoring notification for different monitor".
  - **Add fails:** `add_pending_trade` or `add_new_active_trade` fails (DB error, duplicate, etc.). ATS logs "Failed to add pending trade" / "Failed to add new active trade".

**How to check:**  
- trade_manager logs: "NOTIFIED ACTIVE TRADE SUPERVISOR for monitor X" vs "ACTIVE TRADE SUPERVISOR ERROR" / "ERROR SENDING NOTIFICATION".  
- ATS logs for that monitor: "Successfully added pending trade" / "Successfully added new active trade" vs "Ignoring notification for different monitor" / "Failed to add...".  
- DB: for a given closed trade with `monitor_confirmed = FALSE`, see if it ever existed in `users.active_trades_{user}_{monitor}` (you can’t after close because ATS deletes the row; so check logs and timing).

### 3.2 Trade in ATS but high_price / low_price never updated (high == low)

- **Monitoring thread not running**
  - Thread crashed or never started. ATS logs: "BRUTE FORCE FAILSAFE: Health check - N active trades, monitoring thread alive: **False**".
  - After restart, thread may not start until there are active trades and something triggers `start_monitoring_loop()`.

- **Price lookups return None → update skipped (known root cause)**
  - **`get_current_closing_price_for_trade(ticker, side)`**:
    - ATS reads from `live_data.market_kalshi_{hourly|15m}_{symbol}` (via `get_kalshi_market_snapshot(symbol, market)`).
    - It matches the trade’s **ticker** to a row’s `market_ticker` in that table.
    - **When the Kalshi event/market rotates**, `kalshi_market_watchdog` **TRUNCATE**s that table and repopulates it with the **new** event’s markets only (see `kalshi_market_watchdog.py` ~558: `TRUNCATE TABLE`).
    - So a trade whose ticker belongs to the **previous** event (e.g. previous hour) **no longer has a matching row**. `get_current_closing_price_for_trade` returns **None**, and the monitoring loop **skips** the entire update for that trade, including high/low.
  - **`get_current_symbol_price(symbol)`**:
    - Reads from `live_data.live_price_log_1s_{symbol}`. If that table is empty or stale, returns None → same skip.

  So: **event/market rotation** causes “Market not found for ticker” (or no price) → no high/low updates → at close `high_price == low_price` → `monitor_confirmed = FALSE`. This was previously documented in `archive/2026-03-housekeeping/docs/ROOT_CAUSE_ANALYSIS_MONITOR_CONFIRMED.md` (MOMENTUM BREAKOUT; same mechanism applies to any strategy whose tickers leave the snapshot after rotation).

- **Exceptions in the loop**
  - Any exception in `update_active_trade_monitoring_data()` for a trade (e.g. in probability or time-since-entry logic) can prevent that iteration from doing the UPDATE. Logs: "Error updating monitoring data for trade {trade_id}: ...".

---

## 4. How to verify which failure you have

1. **Recent trades with monitor_confirmed = FALSE**
   - Query:
     ```sql
     SELECT id, monitor, trade_strategy, ticker, high_price, low_price, monitor_confirmed, closed_at
     FROM users.trades_<slot>
     WHERE status = 'closed' AND monitor_confirmed = FALSE
     ORDER BY closed_at DESC
     LIMIT 50;
     ```
   - If `high_price` and `low_price` are **NULL**: trade almost certainly **never** made it into ATS `active_trades` (notification/add failure).
   - If `high_price = low_price` (e.g. both equal to buy_price): trade was in ATS but **monitoring never updated** high/low (thread dead or price lookups returning None / exceptions).

2. **ATS logs (per monitor)**
   - "Ignoring notification for different monitor" → wrong port or wrong monitor in payload.
   - "Failed to add new active trade" / "Failed to add pending trade" → add path failed.
   - "Could not get market price for trade X (TICKER), skipping" or "Market not found for ticker: TICKER" → **event rotation / truncation** path; that trade will never get high/low updated.
   - "Could not get current SYMBOL price" → symbol price missing; same skip.
   - "BRUTE FORCE FAILSAFE ... monitoring thread alive: False" → thread not running while there were active trades.
   - "Error updating monitoring data for trade X" → exception in loop.

3. **trade_manager logs**
   - "NOTIFIED ACTIVE TRADE SUPERVISOR for monitor X" vs "ACTIVE TRADE SUPERVISOR ERROR" / "ERROR SENDING NOTIFICATION" for the same trade id (check around the time the trade went to "open").
   - "Trade X not found in active_trades table users.active_trades_..." → trade_manager tried to read high/low at close but row was already missing (shouldn’t happen if order of ops is correct unless ATS removed it earlier).

4. **Correlation with event rotation**
   - If most `monitor_confirmed = FALSE` trades close **shortly after** the next Kalshi event (e.g. next hour) and have tickers from the previous event, the **truncation / “market not found”** path is the likely cause (same as in the archived root cause analysis).

---

## 5. Summary table

| Symptom | Likely cause |
|--------|----------------------|
| high_price, low_price **NULL** on close | Trade never in ATS active_trades (notification failed, wrong port, ATS down, add failed, or ignored for wrong monitor). |
| high_price == low_price (e.g. = buy_price) | Trade in ATS but monitoring never updated: thread dead, or price lookups return None (event rotation / truncation, or missing symbol price), or exception in loop. |
| Increase over time | More trades affected by rotation (e.g. more volume near event boundaries), or more frequent ATS restarts / thread deaths, or port/config issues affecting more monitors. |

---

## 6. References

- **trade_manager:** `get_high_low_prices_from_active_trades()` (lines ~1292–1359), `update_trade_status_with_ret_pct()` (monitor_confirmed logic ~2147–2154), `notify_active_trade_supervisor_direct` / `_with_monitor` (~1745–1839). Order: get high/low → update DB with monitor_confirmed → then notify ATS "closed".
- **active_trade_supervisor:** `update_active_trade_monitoring_data()` (~1363–1523), `get_current_closing_price_for_trade()` (~1255–1304), `get_kalshi_market_snapshot()` (~1183–1250), monitoring thread / `start_monitoring_loop()` (~1668+). Table name: `get_monitor_active_trades_table()` → `users.active_trades_{user}_{monitor}`.
- **kalshi_market_watchdog:** TRUNCATE of `live_data.market_kalshi_{interval}_{symbol}` on event change (~558).
- **Archived root cause:** `archive/2026-03-housekeeping/docs/ROOT_CAUSE_ANALYSIS_MONITOR_CONFIRMED.md` (MOMENTUM BREAKOUT; same “ticker not in snapshot after truncation” mechanism).

No code changes were made; this document is for diagnosis only.

---

## 7. Root cause (confirmed from code + DB + logs)

1. **high_price == low_price (e.g. today’s 6 on 10031)**  
   - **Cause:** `kalshi_market_watchdog` **TRUNCATE**s `live_data.market_kalshi_{interval}_{symbol}` when the event rotates (`backend/kalshi_market_watchdog.py` ~558).  
   - ATS reads that table in `get_kalshi_market_snapshot()` and matches the trade’s `ticker` to `market_ticker`. After truncation, only the **new** event’s tickers exist.  
   - So for any trade whose ticker belongs to the **previous** event, `get_current_closing_price_for_trade()` returns **None** → `update_active_trade_monitoring_data()` does `continue` and **does not** UPDATE that row’s high_price/low_price (`backend/active_trade_supervisor.py` ~1410–1413).  
   - high/low stay at initial `buy_price` → at close/expiration `high_price == low_price` → `monitor_confirmed = FALSE`.  
   - **Evidence:** ATS 10031 log shows “Market not found for ticker” / “Could not get market price … skipping” for tickers from the previous event.

2. **high_price = low_price = NULL**  
   - **Cause:** Trade was never in `users.active_trades_{user}_{monitor}` when trade_manager called `get_high_low_prices_from_active_trades()` (e.g. ATS never got “open”/“pending”, or add failed, or wrong monitor/port).  
   - **Evidence:** trade_manager would log “Trade X not found in active_trades table …” (when that code path runs). “ACTIVE TRADE SUPERVISOR ERROR for monitor …” indicates notification failure.

3. **Did the logging work cause the uptick?**  
   - We did **not** change when ATS skips (no change to the `if current_market_price is None: continue` path).  
   - We did **not** change truncation or snapshot logic.  
   - The only new behavior in the “get high/low” path is `log(...)` on success in `get_high_low_prices_from_active_trades`; if that ever raised we’d return `(None, None)` and get NULL high/low, not high==low. Today’s 6 have high==low, so that path is not responsible.  
   - **Conclusion:** The uptick is not caused by the logging changes. The mechanism is the existing event-rotation/truncation behavior; more Momentum Breakout (or hour-boundary) volume would increase the number of affected trades.

---

## 8. Why is 10031 showing the most monitor_confirmed = FALSE (and what I got wrong)

**Correction:** I previously stated that 10031 was “the only” BTC hourly monitor. That was wrong. There are **nine** BTC hourly monitors: 10019, 10020, 10022, 10023, 10025, 10028, 10029, 10030, 10031 (strategies: Hourly HTC, Momentum Reversal, Reverse HTC, Momentum Breakout). All of them read from `market_kalshi_hourly_btc` when ATS looks up closing price. I should have verified the monitor list before making that claim.

**Actual evidence (since 2026-03-03):**
- **10031 (BTC, hourly, Momentum Breakout):** 7 FALSE, 215 TRUE.
- **10026 (ETH, hourly, Hourly HTC):** 2 FALSE.
- **10034 (BTC, 15m, 15m HTC):** 1 FALSE.
- **10032 (ETH, hourly, Momentum Breakout):** 0 FALSE. **10033 (ETH, hourly, Momentum Contain):** 0 FALSE.

So FALSE in that window is **not** limited to 10031: 10026 and 10034 also had at least one. 10031 had the most (7), all Momentum Breakout.

**What is true:** The mechanism (event rotation → table truncation → ticker missing → ATS skips update → high==low) applies to **any** monitor that reads from a given symbol/market table when that table is truncated. So every BTC hourly monitor (10019, 10020, 10022, 10023, 10025, 10028, 10029, 10030, 10031) is equally exposed when `market_kalshi_hourly_btc` is truncated; same for ETH hourly monitors and `market_kalshi_hourly_eth`, and 15m monitors and their tables. Why 10031 shows up most in this slice of data is likely that **Momentum Breakout** on that monitor has more trades still open at the exact rotation moment (e.g. strategy/timing), not that 10031 is the only one using that table or the only one that can be affected.
