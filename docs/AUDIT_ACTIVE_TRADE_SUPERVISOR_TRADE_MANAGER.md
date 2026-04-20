# Audit: active_trade_supervisor and trade_manager (monitor_confirmed / fixed-point)

**Purpose:** Full audit of how active_trade_supervisor (ATS) and trade_manager interact, why OPEN trades were not being tracked (monitor_confirmed = FALSE), and the impact of the Fixed Point Migration.

**Date:** 2026-03-12

---

## 1. Summary

- **Root cause (fixed):** In `trade_manager.confirm_open_trade()`, after the fixed-point migration the code still referenced `taker_fill_cost_cents`, which was removed from `users.orders_0001`. When `_parse_dollars(taker_fill_cost_dollars)` returned `None`, the fallback used the undefined variable → **NameError** → confirm_open_trade crashed. The trade never got `status = 'open'` and ATS never received the `"open"` notification, so the trade stayed `pending` in ATS and was never moved to `active`. Only rows with `status = 'active'` are monitored (high/low updated); pending rows are not. Result: trades never tracked → high_price/low_price never set → at close `monitor_confirmed = FALSE`.
- **Fix applied:** Removed the `taker_fill_cost_cents` fallback and added a safe fallback: when `total_cost_usd` is None, read existing `buy_price` from `users.trades_<slot>` so we do not overwrite with 0 and do not crash.

---

## 2. Pipeline: trade creation → ATS tracking → monitor_confirmed

### 2.1 Lifecycle (live trade)

1. **Insert (pending)**  
   - trade_manager inserts into `users.trades_<slot>` with `status = 'pending'`, `monitor` (e.g. `mon_0001_10026`).  
   - Calls `notify_active_trade_supervisor_direct(trade_id, ticket_id, "pending")` which:
     - Reads `monitor` from `trades_0001`, strips `mon_` → `0001_10026`.
     - Resolves port: `get_monitor_port("active_trade_supervisor", "0001_10026")`.
     - POSTs to `http://localhost:{port}/api/trade_manager_notification` with `status: "pending"`.
   - ATS (that monitor’s process): if `monitor_identifier` matches, calls `add_pending_trade()` → INSERT into `users.active_trades_{user}_{monitor}` with `status = 'pending'`.

2. **Open (confirmed)**  
   - Executor stores `order_id_open` via `/api/update_trade_status` (accepted).  
   - trade_manager runs `confirm_open_trade(id, ticket_id)` (from FAILSAFE thread after storing order_id, or from `/api/positions_updated`).  
   - `confirm_open_trade`:
     - Polls `users.orders_0001` for that `order_id_open`: expects `status = 'executed'`, `remaining_count_fp` → 0, uses `taker_fill_cost_dollars` (and fees) for buy_price/fees.
     - **Previously:** When `_parse_dollars(taker_fill_cost_dollars)` was None, it used `taker_fill_cost_cents` → NameError → loop crashed; trade stayed pending, no "open" notification.
     - **Now:** If no total_cost_usd, keeps existing buy_price from `trades_0001`; then UPDATEs trade (position, buy_price, fees, diff, symbol_open), then `update_trade_status(id, 'open')`, which notifies ATS with `"open"`.
   - ATS on `"open"`: `confirm_pending_trade(trade_id, ticket_id)` (UPDATE active_trades SET status='active', high_price=low_price=buy_price); if no pending row, `add_new_active_trade()` (INSERT with status 'active').

3. **Monitoring**  
   - ATS monitoring loop selects from `users.active_trades_{user}_{monitor}` **WHERE status = 'active'** only.  
   - For each row: `get_current_closing_price_for_trade(ticker, side)` (from Kalshi snapshot), `get_current_symbol_price(symbol)`; updates high_price/low_price.  
   - If the trade never becomes `active` (e.g. "open" never received), it is never monitored → high/low stay at initial or NULL.

4. **Close**  
   - trade_manager calls `get_high_low_prices_from_active_trades(trade_id)` (reads monitor from trades_0001, then SELECT from `users.active_trades_{user}_{monitor}`), then `update_trade_status_with_ret_pct(..., high_price, low_price)` and sets `monitor_confirmed = (high_price != low_price)`.  
   - Then notifies ATS `"closed"`; ATS removes the row.

### 2.2 Paper trade path

- trade_manager inserts with pending, then immediately UPDATEs to `status = 'open'` and in a background thread calls `notify_active_trade_supervisor_direct(..., "pending")` and `notify_active_trade_supervisor_direct(..., "open")`.  
- No orders table; no `confirm_open_trade`. So paper trades were not affected by the taker_fill_cost_cents bug.

---

## 3. active_trade_supervisor (ATS) – key points

- **Per-monitor process:** One ATS process per monitor (e.g. `active_trade_supervisor_0001_10026`), port from `get_monitor_port("active_trade_supervisor", "0001_10026")` (formula: `start_port + (monitor_id - 10000) * 2 + 1`).
- **Table:** `users.active_trades_{user}_{monitor}` (e.g. `active_trades_0001_10026`). Created on startup; columns include trade_id, ticket_id, status ('pending' | 'active' | …), high_price, low_price, etc.
- **Endpoint:** `POST /api/trade_manager_notification` with `trade_id`, `ticket_id`, `status`, `monitor_identifier`. If `monitor_identifier != MONITOR_IDENTIFIER`, ATS returns 200 with "ignored".
- **Pending → active:** Only "open" notification triggers transition: `confirm_pending_trade` (UPDATE pending → active) or `add_new_active_trade` (INSERT active). If "open" is never sent or goes to wrong port, the row stays pending and is not monitored.
- **Monitoring loop:** Only rows with `status = 'active'` are selected and updated (high/low). Pending rows are not updated.
- **Data source for high/low:** `get_current_closing_price_for_trade()` uses `get_kalshi_market_snapshot()` → `live_data.market_kalshi_{hourly|15m}_{symbol}`. If the ticker is missing (e.g. after event rotation / TRUNCATE), it returns None and the loop skips that trade for that cycle → high/low not updated → monitor_confirmed can still be FALSE even when the trade is active (see docs/DIAGNOSIS_MONITOR_CONFIRMED_FALSE.md).

---

## 4. trade_manager – notification and confirm_open_trade

- **Port resolution:** `notify_active_trade_supervisor_direct` reads `monitor` from `users.trades_<slot>` for the trade_id, strips `mon_` prefix, then `get_monitor_port("active_trade_supervisor", monitor_suffix)`. So the same monitor that owns the trade gets the notification.
- **When "open" is sent:**
  - From `update_trade_status(..., 'open')` (called by `confirm_open_trade` after it updates the trade to open).
  - From paper-trade path (background thread).
- **confirm_open_trade** is invoked by:
  - FAILSAFE after storing `order_id_open` in `/api/update_trade_status` (accepted).
  - `/api/positions_updated` (db_name `"positions"`) for all pending trades.

If confirm_open_trade raises (e.g. NameError on taker_fill_cost_cents), the trade is never set to open and ATS never gets "open".

---

## 5. Fixed-point migration impact

- **orders_0001:** Legacy columns dropped in `20260312_2045_orders_drop_legacy_int_columns.up.sql`: e.g. `taker_fill_cost`, `maker_fill_cost`, `initial_count`, `remaining_count`, `fill_count`, etc. Only `*_fp` and `*_dollars` remain.
- **confirm_open_trade** was updated to use `remaining_count_fp`, `fill_count_fp`, `initial_count_fp`, `taker_fill_cost_dollars`, etc., but left a fallback referencing `taker_fill_cost_cents` when `_parse_dollars(taker_fill_cost_dollars)` was None. That variable no longer exists → NameError.
- **trades_0001:** No fixed-point column renames in schema; ATS and trade_manager still use `position`, `contract`, `buy_price`, etc. No change needed there for this bug.

---

## 6. Duplicate entries in active_trades (same monitor)

- If the **correct** ATS gets "pending" and then "open":
  - "pending" → one INSERT (status 'pending').
  - "open" → `confirm_pending_trade` UPDATEs that row to 'active'. No second row.
- If **"open" is sent to the correct ATS but "pending" was never received** (e.g. timeout, ATS restart): `confirm_pending_trade` finds no pending row (rowcount 0), so ATS calls `add_new_active_trade` → second INSERT (status 'active'). So one table can end up with two rows for the same trade_id (one leftover pending if it ever arrived, one active). Mitigation: ensure "pending" and "open" both reach the same ATS; optionally ATS could merge/dedupe by trade_id when adding active.
- If **confirm_open_trade never completes** (e.g. crash): trade stays pending in DB; ATS has only the pending row and never gets "open", so no second row from "open". Duplicates in that scenario would require another path (e.g. duplicate "open" or wrong port logic) and are secondary to the main bug.

---

## 7. Recommendations

1. **Deploy the fix** (remove taker_fill_cost_cents fallback and use existing buy_price when total_cost_usd is None) and restart trade_manager (and ATS if desired).
2. **Monitor:** After deploy, run `check_monitor_confirmed_failures.py` over the next days; expect fewer monitor_confirmed = FALSE for trades that open after the fix.
3. **Optional hardening:** In ATS, on "open" when `add_new_active_trade` is used, consider deleting any existing row with the same trade_id and status 'pending' to avoid duplicate rows.
4. **Event rotation:** monitor_confirmed = FALSE can still occur when the trade is active but the ticker disappears from the Kalshi snapshot (rotation/TRUNCATE). See docs/DIAGNOSIS_MONITOR_CONFIRMED_FALSE.md and docs/MONITOR_CONFIRMED_PIN_OPEN_TRADES_PLAN.md for pinning open-trade markets.

---

## 8. Key code references

| Component | Location |
|-----------|----------|
| notify_active_trade_supervisor_direct | trade_manager.py ~1827 |
| notify_active_trade_supervisor_direct_with_monitor | trade_manager.py ~1784 |
| confirm_open_trade (orders + update status + notify ATS) | trade_manager.py ~859 |
| get_high_low_prices_from_active_trades | trade_manager.py ~1331 |
| update_trade_status_with_ret_pct (monitor_confirmed) | trade_manager.py ~2122 |
| handle_trade_manager_notification (pending / open) | active_trade_supervisor.py ~518 |
| add_pending_trade / confirm_pending_trade / add_new_active_trade | active_trade_supervisor.py ~759, ~852, ~658 |
| update_active_trade_monitoring_data (only status='active') | active_trade_supervisor.py ~1368 |
| get_monitor_port | backend/core/port_config.py ~221 |
| Orders legacy columns dropped | scripts/migrations/20260312_2045_orders_drop_legacy_int_columns.up.sql |
