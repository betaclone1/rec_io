# Unified AES tick contract

This document defines semantics for the **unified** auto entry supervisor process (`auto_entry_supervisor.py unified`): one OS process per tenant evaluates many active monitors in that tenant’s `monitor_list_*` without running one script per monitor. (Legacy argv modes and older `unified_hourly` / `unified_15m` labels may still appear in docs/history; current supervisor generation uses a single unified pool.)

## Logical tick

- **Tick**: One pass of the AES monitoring loop. Wakes are primarily **event-driven** via Redis `rec_io:live_state:updated` (coalesced; see `TRADEFLOW_LIVE_STATE_TRIGGER_MIN_SEC`, default **0.2s**; orderbook **0.05s**), with failsafe poll `AES_FAILSAFE_POLL_SEC` (default **1s**) when quiet.
- **Strike table snapshot**: For a given `(exchange, symbol, market)` ladder (e.g. Kalshi BTC hourly / 15m), the latest ladder read from Redis **`live_state`** strike_ladder (AES hot path uses `tradeflow_live_reads.strike_ladder` — not a live PostgreSQL substitute). Header fields (`ttc`, `event_ticker`, …) plus the `strikes` array.
- **Snapshot identity**: Implicitly identified by `(exchange, symbol, market)` at read time plus ladder/envelope fields (`event_ticker`, TTC, `generation_id` when present, ask fingerprint). Per tick, monitors that share the same symbol and normalized market reuse **one** fetched snapshot to avoid N identical queries.

## Submitted vs confirmed

- **Submitted (AES perspective)**: For unified mode with trading Redis enabled: successful `XADD` to the trade_manager command stream with a durable `ticket_id` in the payload and `correlation_id` equal to that `ticket_id`. This means “accepted for processing by trade_manager’s consumer,” not “order placed” or “position open.”
- **Submitted (HTTP fallback)**: HTTP `POST /trades` returned `201` — same practical meaning as today; used when Redis comms are unavailable (logged as degraded path).
- **Confirmed**: Trade row in the tenant `trades_*` table reaches `open` (or paper-trade equivalent) and downstream executor/confirmation logic runs — **outside** AES’s tick loop. AES must **not** block the next tick waiting for this.

## Monitor-scoped duplicate prevention

- **Strike cooldown** (`TRADE_COOLDOWN`, default **1** second in code; `last_trade_times`): Keys include `monitor_id` in unified pool (`_strike_cooldown_key`). The same strike/side on monitor A does not suppress monitor B. Cooldown is claimed when `can_trade_strike` returns true (before later filters); failed later gates do not always release the key (known Stage 1 candidate).
- **`is_strike_already_traded` / open positions**: Scoped to the monitor (and its `trades_*` row set) via current monitor context.
- **Trade manager idempotency**: `insert_trade` treats a non-empty `ticket_id` as an idempotency key: if a row with that `ticket_id` already exists for the tenant trades table, the existing `id` is returned and a second insert is not performed. AES publishes `add_trade` with stream `correlation_id` equal to `ticket_id`, which aligns with the trade_manager consumer’s Redis dedupe key (`trading:dedupe:tm_cmd:{correlation_id}`) for the same delivery.

## Observability

- Set env **`AES_UNIFIED_PROFILE=1`** to emit one `[AES PROFILE]` line per unified pass: total `unified_pass` time, per-group ladder `prefetch`, extra per-monitor `get_master` fetch time when not served from the shared snapshot (`get_master_extra`), `master_hits` (cache hits), summed `trigger_trade`, and per-monitor wall times.
- Set env **`TRADEFLOW_DECISION_TRACE=1`** for structured `[TRADEFLOW TRACE]` lines (pass begin/end, ladder identity, per-monitor wall, HTC gate reasons, cooldown skips, fire/block). Add **`TRADEFLOW_DECISION_TRACE_VERBOSE=1`** for per-strike post-cooldown skip reasons (prob/diff/volume/ask). Implementation: `backend/core/tradeflow_decision_trace.py`. Does **not** change gate outcomes.
- Side-by-side helpers: `scripts/diagnostics/check_tradeflow_env_parity.py`, `scripts/diagnostics/check_ats_enrollment_health.py`.

## HTTP fallback policy (unified pool)

1. Prefer **Redis** `add_trade` command stream with `correlation_id=ticket_id`.
2. If Redis publish fails or trading Redis is disabled: **one** synchronous HTTP `POST` to trade_manager `/trades` (existing timeout), with a clear log line that the unified pool is on the HTTP fallback path.
3. Post-submit **logging and UI notify** on the Redis fast path are **non-blocking** (background thread) so the next monitor/snapshot group is not delayed.

## Unified ATS (auto close) parity

The unified **active_trade_supervisor** pool uses the same ideas for **`trigger_auto_stop_close`**: Redis `add_trade` with `correlation_id=ticket_id`, deferred `trade_logger` + preferences/notify after a successful XADD (unified pool only), and HTTP fallback to **main_app** `POST /trades` (same proxy path as legacy ATS). On HTTP 200, the JSON body is checked for an `error` key so main_app proxy failures are not treated as success. See `backend/active_trade_supervisor.py`. With `TRADEFLOW_DECISION_TRACE=1`, ATS also emits enrollment health traces (`ats_enrollment_health`, failed `ats_enroll_ack`).
