# Unified AES tick contract

This document defines semantics for the **unified** auto entry supervisor process (`auto_entry_supervisor.py unified`): one OS process per tenant evaluates many active monitors in that tenant’s `monitor_list_*` without running one script per monitor. (Legacy argv modes and older `unified_hourly` / `unified_15m` labels may still appear in docs/history; current supervisor generation uses a single unified pool.)

**Latest-only lanes (current):** Unified AES/ATS evaluate per `(symbol, market)` **mailbox** — a newer ladder publish **replaces** the pending snap and cancels in-flight **evaluation** (already-submitted TM/TE trades are never cancelled). Monitors on the same ladder run in parallel; fire/submit is refused if `generation_id`/epoch is superseded. See `backend/core/tradeflow_latest_only_lane.py`.

**BTC 15m Expiration Scalp cutout:** Dedicated processes `auto_entry_supervisor.py btc15m_exp_scalp` and `active_trade_supervisor.py btc15m_exp_scalp` (per tenant) own monitors with `symbol=BTC`, `market=15m`, `strategy=Expiration Scalp`. Those monitors are **excluded** from the general unified AES/ATS pool to prevent double-fire. Membership helpers: `backend/core/aes_btc15m_exp_scalp_cutout.py`.

## Logical tick

- **Tick**: Ladder-scoped latest-only eval driven by Redis `rec_io:live_state:updated` (coalesced; see `TRADEFLOW_LIVE_STATE_TRIGGER_MIN_SEC`, default **0.2s**; orderbook **0.05s**), with failsafe poll `AES_FAILSAFE_POLL_SEC` / `ATS_FAILSAFE_POLL_SEC` (default **1s** for pool modes) when quiet.
- **Failsafe**: AES/ATS monitoring loops call `failsafe_refresh_all` on a **cadence** of `AES_FAILSAFE_POLL_SEC` / `ATS_FAILSAFE_POLL_SEC` (default **1s** for pool modes), whether the live_state wait timed out or woke early. Quiet-only failsafe starved non-waking ladders while other symbols flooded wakes. Do **not** call failsafe on every wake (that doubles work); do **not** skip cadence while busy.
- **Strike table snapshot**: For a given `(exchange, symbol, market)` ladder (e.g. Kalshi BTC hourly / 15m), the latest ladder read from Redis **`live_state`** strike_ladder (AES hot path uses `tradeflow_live_reads.strike_ladder` — not a live PostgreSQL substitute). Header fields (`ttc`, `event_ticker`, …) plus the `strikes` array.
- **TTC for window gates (critical):** `ttc_seconds_from_ladder` must **not** treat frozen ladder `ttc` as wall-clock truth. Prefer `settlement_end_ms` / Kalshi ticker settlement end → seconds remaining **now**. Otherwise age snapshot `ttc` by `last_updated` (or lane `captured_mono` age). Delayed BTC ladder publishes previously left Exp Scalp monitors `INACTIVE` 15–30s into a 45s window; that is a defect, not acceptable jitter.
- **Snapshot identity**: `(exchange, symbol, market)` plus a **decision** fingerprint (default): `event_ticker` + TTC bucketed by `TRADEFLOW_LANE_TTC_BUCKET_SEC` (default **1s**) + yes/no asks rounded to **1¢** for the first N strikes (`TRADEFLOW_LANE_DECISION_STRIKES`). Publisher `generation_id` is used only when `TRADEFLOW_LANE_USE_PUBLISHER_GEN=1`. Same decision gen refreshes the mailbox payload without cancelling in-flight eval, and `TRADEFLOW_LANE_REEVAL_SEC` (default **1s**) still schedules a re-eval so quiet fingerprints cannot skip entry windows. Mailbox holds at most one latest snap per ladder; intermediates that never start (or are cancelled) are discarded — never FIFO of old gens.

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
