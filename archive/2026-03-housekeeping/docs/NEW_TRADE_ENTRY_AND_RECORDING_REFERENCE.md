# New Trade Entry and Recording — Reference

This document describes **all ways a new (open) trade can be entered**, what data is passed to `trade_manager`, and how it is written to the **trades historical log** (`users.trades_0001`). It does not cover closing trades.

---

## 1. Single recording point

- **Every new trade is recorded in exactly one place:** `backend/trade_manager.py` → `insert_trade(trade)`.
- **Every new-trade path** ends at the trade_manager HTTP endpoint `POST /trades` with `intent` ≠ `"close"` (or no intent). The handler is `add_trade()`; it calls `insert_trade(data)` for open/paper flows.
- **Table:** `users.trades_0001` (PostgreSQL, `users` schema).

---

## 2. Ways a new trade can be entered

### 2.1 Manual entry (strike table)

- **UI:** User clicks a YES/NO cell in the strike table (e.g. `frontend/tabs/trade_monitor.html` with strike table).
- **Flow:**
  1. **Frontend:** `frontend/js/strike-table.js` — on click, calls `prepareTradeData(spanEl)` (from `frontend/js/trade-execution-controller.js`), then `POST /api/trigger_open_trade` with the returned object.
  2. **Main app:** `backend/main.py` → `trigger_open_trade()` receives the JSON, builds a **trade_data** dict (adds `ticket_id`, `date`, `time`, converts side yes/no → Y/N, loads `bankroll_allotment_total` from `users.monitor_list_0001` by monitor id), then **POSTs** that dict to **trade_manager** at `http://<host>:<trade_manager_port>/trades`.
  3. **Trade manager:** `backend/trade_manager.py` → `add_trade()` receives the body. For open (no `intent: "close"`): if `paper_trade` → insert with status `pending`, then immediately set status `open` and skip executor; else → send to trade_executor, then `insert_trade(data)` with status `pending`. Returns `{"id": trade_id}`.

- **Payload to trade_manager (from main.trigger_open_trade):**  
  `ticket_id`, `status`, `date`, `time`, `symbol`, `market`, `trade_strategy`, `contract`, `strike`, `side` (Y/N), `ticker`, `buy_price`, `position`, `symbol_open`, `symbol_close`, `momentum`, `prob`, `diff`, `win_loss`, `entry_method` (e.g. `"manual"`), `monitor`, `bankroll_allotment_total`, `paper_trade`.

- **Data source (manual, strike table):**
  - **prepareTradeData:** `symbol` from button/data or `getCurrentSymbol()`; `strike`/`side`/`ticker`/`diff` from DOM/data attributes; `buy_price` from `data-ask-price`; `position` from `/api/monitor/<id>` (`total_position`); `symbol_open` from `getCurrentSymbolTickerPrice()`; `momentum` from `/api/momentum?symbol=...`; `prob` from strike table Prob column; `trade_strategy` and `paper_trade` from `/api/monitor/<id>`; `contract` from `getTruncatedMarketTitle()`; `monitor` from `window.currentMonitorName`; `entry_method`: `"manual"`.

### 2.2 Manual entry (watchlist)

- **UI:** User clicks a YES/NO cell in the watchlist table.
- **Flow:**
  1. **Frontend:** `frontend/js/watchlist-table.js` — on click, calls `prepareTradeData(spanEl)`, then `POST /api/trigger_open_trade` with the same shape as strike table (but does **not** send `monitor` or `entry_method` in the snippet; if the page sets `currentMonitorName`/`currentMonitorId`, `prepareTradeData` still returns `monitor` and the caller could add it — currently the watchlist JSON only sends a subset; if monitor is missing, main’s `trigger_open_trade` returns 400 “Monitor must be specified”).
  2. Same as 2.1 from main app onward: main builds trade_data (including monitor from request) and POSTs to trade_manager → `add_trade()` → `insert_trade(data)`.

- So **manual entry** is effectively: **strike table or watchlist** → **prepareTradeData** → **POST /api/trigger_open_trade** → main → **POST trade_manager /trades** → **add_trade()** → **insert_trade(data)**.

### 2.3 Auto entry

- **Trigger:** Auto-entry supervisor decides to open a trade (e.g. bracket / rules).
- **Flow:**
  1. **Backend:** `backend/auto_entry_supervisor.py` → `trigger_auto_entry_trade(strike_data)`. Builds **trade_payload** (ticket_id, date, time, symbol, market, trade_strategy, contract, strike, side, ticker, prob, diff, buy_price, position, monitor, bankroll_allotment_total, entry_method `"auto_entry"`, loss_prevention, multiplier, paper_trade). **POSTs** directly to **trade_manager** at `http://localhost:<trade_manager_port>/trades` (no main app in the path).
  2. **Trade manager:** Same `add_trade()`: paper vs live branch, then `insert_trade(data)` with status `pending`.

- **Payload to trade_manager (from auto_entry_supervisor):**  
  Same logical fields as manual; `entry_method`: `"auto_entry"`; `strike_data` provides strike, side, ticker, probability, diff, buy_price; position from `get_position_size()`; bankroll from `get_bankroll_allotment()`; contract from strike table `market_title`; trade_strategy from DB; paper_trade from `users.monitor_list_<user>`, etc.

---

## 3. What gets sent to trade_manager (open payload)

Common fields used by **add_trade** / **insert_trade**:

- **Required for insert_trade:** `date`, `time`, `strike`, `side`, `buy_price`, `position`, and **symbol** (no fallback; must be in payload).
- **From payload if present:** `status`, `market`, `trade_strategy`, `contract`, `prob`, `diff`, `ticker`, `ticket_id`, `market_id`, `entry_method`, `close_method`, `monitor`, `bankroll_allotment_total`, `volatility_percentile`, `paper_trade`, `loss_prevention`, `multiplier`.
- **Monitor is required** for the insert path (main’s trigger_open_trade and add_trade both rely on it; insert_trade uses it for DB and for fetching cooldown_timer / loss_prevention / multiplier from monitor_list).

---

## 4. How insert_trade writes to users.trades_0001

- **insert_trade(trade)** is the only function that INSERTs a new row into `users.trades_0001`.
- It:
  - Reads **symbol** from `trade` (required).
  - Overwrites **symbol_open** from live data: `SELECT price FROM live_data.live_price_log_1s_{symbol} ORDER BY timestamp DESC LIMIT 1`.
  - Computes **momentum** and **momentum_percentile** and **momentum_5s_avg** from `get_momentum_data_from_postgresql(symbol)` and `calculate_momentum_percentile(symbol, momentum_score)` (watchdog-style logic inside trade_manager).
  - Derives **contract_name** from `truncate_contract_name(contract_original, symbol)`, **hour_idx** from contract, **weekly_cycle** from date + hour_idx.
  - Resolves **loss_prevention**, **multiplier** from trade payload or, if missing, from monitor state in DB (`_fetch_monitor_state`, monitor_list).
  - Gets **price_spread** from strike table via `_get_price_spread_from_strike_table(symbol, ticker, side)`.
  - **INSERT columns (and source):**
    - status, date, time, symbol, market, trade_strategy, contract, strike, side, prob, diff, buy_price, position, sell_price, closed_at, fees, pnl, symbol_open, symbol_close → from trade or None; **symbol_open** from live price log as above.
    - momentum, volatility_percentile, win_loss, ticker, ticket_id, market_id → momentum from DB/compute; **volatility_percentile** from `trade.get('volatility_percentile')`; rest from trade or None.
    - momentum_percentile, momentum_5s_avg, entry_method, close_method, monitor, bankroll, hour_idx, weekly_cycle, loss_prevention, multiplier, price_spread, paper_trade, cooldown_timer → from trade or from DB/compute as above.

- **Note:** The table has columns **volatility**, **movement**, **movement_percentile** (for backfill / future use). **insert_trade** does **not** set them; it only sets **volatility_percentile** from the payload. So new rows have volatility/movement/movement_percentile NULL unless backfilled or later logic is added.

---

## 5. Summary table

| Entry type   | Trigger                    | Frontend/script              | HTTP path                     | Who builds payload        | Who inserts DB        |
|-------------|----------------------------|------------------------------|-------------------------------|----------------------------|------------------------|
| Manual (ST) | Strike table YES/NO click  | strike-table.js              | POST /api/trigger_open_trade  | main.trigger_open_trade    | trade_manager.insert_trade |
| Manual (WL) | Watchlist YES/NO click     | watchlist-table.js           | POST /api/trigger_open_trade  | main.trigger_open_trade    | trade_manager.insert_trade |
| Auto        | Auto-entry supervisor      | —                            | POST /trades (trade_manager)  | auto_entry_supervisor      | trade_manager.insert_trade |

- **Close** is not “new trade entry”: frontend sends `POST /trades` with `intent: "close"` and trade `id`; main forwards to trade_manager; add_trade handles close path (update status, executor or paper close). No `insert_trade` for closes.

---

## 6. Files to look at

- **Recording:** `backend/trade_manager.py` — `insert_trade()`, `add_trade()` (POST /trades).
- **Manual entry:** `backend/main.py` — `trigger_open_trade()` (POST /api/trigger_open_trade); `frontend/js/strike-table.js`, `frontend/js/watchlist-table.js`, `frontend/js/trade-execution-controller.js` (prepareTradeData, closeTrade).
- **Auto entry:** `backend/auto_entry_supervisor.py` — `trigger_auto_entry_trade()`.
- **Schema:** `backend/core/config/database.py` (users.trades_0001); `docs/MASTER_DB_SCHEMA_REFERENCE.md`.
