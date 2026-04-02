# Unified AES tick contract

This document defines semantics for the **unified** auto entry supervisor processes (`unified_hourly`, `unified_15m`): one OS process evaluates many monitors in `users.monitor_list_0001` without running one script per monitor.

## Logical tick

- **Tick**: One pass of the AES monitoring loop (by default ~1s cadence; see `HEARTBEAT_INTERVAL_SEC` vs the 1s sleep in `start_monitoring_loop`).
- **Strike table snapshot**: For a given `(exchange, symbol, market)` ladder (e.g. Kalshi BTC hourly), the latest ladder row set read from `live_data.strike_table_*` — header fields (`ttc`, `event_ticker`, …) plus the `strikes` array for that timestamp.
- **Snapshot identity**: Implicitly identified by `(exchange, symbol, market)` at read time; the DB `timestamp` on the header row is the generator’s version. Per tick, monitors that share the same symbol and normalized market reuse **one** fetched snapshot to avoid N identical queries.

## Submitted vs confirmed

- **Submitted (AES perspective)**: For unified mode with trading Redis enabled: successful `XADD` to the trade_manager command stream with a durable `ticket_id` in the payload and `correlation_id` equal to that `ticket_id`. This means “accepted for processing by trade_manager’s consumer,” not “order placed” or “position open.”
- **Submitted (HTTP fallback)**: HTTP `POST /trades` returned `201` — same practical meaning as today; used when Redis comms are unavailable (logged as degraded path).
- **Confirmed**: Trade row in `users.trades_0001` reaches `open` (or paper-trade equivalent) and downstream executor/confirmation logic runs — **outside** AES’s tick loop. AES must **not** block the next tick waiting for this.

## Monitor-scoped duplicate prevention

- **10s strike cooldown** (`TRADE_COOLDOWN`, `last_trade_times`): Keys include `monitor_id` in unified pool (`_strike_cooldown_key`). The same strike/side on monitor A does not suppress monitor B.
- **`is_strike_already_traded` / open positions**: Scoped to the monitor (and its `trades_*` row set) via current monitor context.
- **Trade manager idempotency**: `insert_trade` treats a non-empty `ticket_id` as an idempotency key: if a row with that `ticket_id` already exists in `users.trades_0001`, the existing `id` is returned and a second insert is not performed. AES publishes `add_trade` with stream `correlation_id` equal to `ticket_id`, which aligns with the trade_manager consumer’s Redis dedupe key (`trading:dedupe:tm_cmd:{correlation_id}`) for the same delivery.

## Observability

- Set env **`AES_UNIFIED_PROFILE=1`** to emit one `[AES PROFILE]` line per unified pass: total `unified_pass` time, per-group ladder `prefetch`, extra per-monitor `get_master` fetch time when not served from the shared snapshot (`get_master_extra`), `master_hits` (cache hits), summed `trigger_trade`, and per-monitor wall times.

## HTTP fallback policy (unified pool)

1. Prefer **Redis** `add_trade` command stream with `correlation_id=ticket_id`.
2. If Redis publish fails or trading Redis is disabled: **one** synchronous HTTP `POST` to trade_manager `/trades` (existing timeout), with a clear log line that the unified pool is on the HTTP fallback path.
3. Post-submit **logging and UI notify** on the Redis fast path are **non-blocking** (background thread) so the next monitor/snapshot group is not delayed.

## Unified ATS (auto close) parity

The unified **active_trade_supervisor** pool uses the same ideas for **`trigger_auto_stop_close`**: Redis `add_trade` with `correlation_id=ticket_id`, deferred `trade_logger` + preferences/notify after a successful XADD (unified pool only), and HTTP fallback to **main_app** `POST /trades` (same proxy path as legacy ATS). On HTTP 200, the JSON body is checked for an `error` key so main_app proxy failures are not treated as success. See `backend/active_trade_supervisor.py`.
