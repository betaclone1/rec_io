# Kalshi websocket orderbook → market watchdog (v2)

**Goal:** Replace the REST-polling `kalshi_market_watchdog` with a new service that builds and maintains orderbooks from Kalshi’s websocket subscriptions, then writes the same price/volume data into the existing `live_data.market_kalshi_*` tables so `strike_table_generator` and the rest of the system are unchanged.

**Scope:** In: new “market watchdog v2” that subscribes to Kalshi orderbook websocket(s), in-memory (and optional short-term) orderbook state, derivation of yes_ask/no_ask/volume/etc. to match current REST semantics, and writing to `market_kalshi_hourly_{symbol}` / `market_kalshi_15m_{symbol}`. Out: changing how strike_table_generator or downstream consumers read data; changing Kalshi auth or non-orderbook APIs.

**Status:** draft

## Context

- **Current:** `kalshi_market_watchdog` polls GET EVENT REST API every second and upserts into `live_data.market_kalshi_{interval}_{symbol}` (yes_ask, no_ask, volume, etc.). Works but is clumsy and not real-time.
- **Target:** Subscribe to Kalshi orderbook websocket(s), maintain per-market orderbooks (sorted), derive the same fields the REST response provides, and upsert into the same tables. Existing test scripts (`kalshi_market_ticker_websocket.py`, `live_orderbook_snapshot.py`, `test_orderbook_websocket.py`, etc.) show connectivity is viable.
- **Constraint:** Deliver the same values `strike_table_generator` needs; no changes to the rest of the system.

## Steps

1. **Document the current contract** — List exactly which tables and columns the watchdog writes and which `strike_table_generator` (and any other consumers) read. Capture REST response shape and how it maps to DB columns (yes_ask, no_ask, volume, last_price, etc.).
2. **Inventory existing websocket/orderbook code** — Review `backend/api/kalshi-api/` (e.g. `kalshi_market_ticker_websocket.py`, `live_orderbook_snapshot.py`, `test_orderbook_websocket.py`, `raw_orderbook_data.py`) and any tests. Summarize subscription model, message types, and what’s already implemented for orderbook state.
3. **Design orderbook data management** — Define in-memory (and if needed short-term persistence) structure for per-market orderbooks: how to apply deltas, keep books sorted, and compute best bid/ask and volume in the same units/semantics as the REST API. Decide scope per market (e.g. which events/markets we subscribe to) and how we map subscription ticks to “event + market” rows we write.
4. **Implement orderbook pipeline** — Build the new service: connect to Kalshi orderbook websocket(s), maintain orderbooks, derive yes_ask, no_ask, no_bid, yes_bid, last_price, volume, etc. to match current semantics. Include reconnection, backoff, and logging.
5. **Implement DB write path** — Upsert derived data into `live_data.market_kalshi_hourly_{symbol}` and `live_data.market_kalshi_15m_{symbol}` using the same schema and conventions as the current watchdog (so strike_table_generator sees no change).
6. **Validate and cut over** — Run new service alongside old watchdog (or against a copy of tables), compare outputs; then switch supervisor/config to the new script and retire or archive the old REST-polling watchdog.

## Completion criteria

- [ ] Contract between watchdog output and strike_table_generator (tables + columns) is documented.
- [ ] Existing websocket/orderbook scripts are summarized and reuse/refactor points identified.
- [ ] Orderbook data model and derivation rules (REST-equivalent fields) are designed and agreed.
- [ ] New market-watchdog-v2 service runs from orderbook websocket and writes to existing market_kalshi_* tables.
- [ ] Strike_table_generator (and any other readers) work unchanged; no code changes required downstream.
- [ ] Old REST-polling watchdog is retired or clearly deprecated in favor of the new service.

## Blockers / decisions

- Confirm which Kalshi websocket API(s) and subscription(s) to use for orderbook data (e.g. exchange API docs, existing test script behavior).
- Decide whether to persist orderbook snapshots/deltas (e.g. for replay or debugging) or keep state in-memory only for the writer process.
