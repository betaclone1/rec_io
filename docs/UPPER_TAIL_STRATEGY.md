# Upper Tail

**v4 CORE context:** Upper Tail is one rail of the main live strategy set — probe W/L → bias meter → sized arm. See `docs/VER4_DEVELOPMENT/CORE_TAIL_BIAS_STRATEGY.md`.

One-sided entry at the expensive end of a 15m book. Same monitor criteria as Lower Tail: a time window (`min_time`–`max_time`) and one target price (`min_ask` = `max_ask`, default $0.99).

Kalshi will not rest these orders from the open. `upper_tail_agent` qualifies during the monitor time window, then sends a single GTC limit at the target on that side (`post_only` off):

- **Crypto** at `live_data_level=full` — always-on orderbook stream consumer (not wake→full tick): armed tickers register for immediate OB Redis flush; each delta is a cheap touch check; rail cross places once (`path=hot`). Housekeeping (monitors, markets, fills) is a separate timer loop. Crypto 15m is assumed **24/7**.
- **Commodity** / lean `market` feed — public trades tape print ≥ target on the timer loop (`path=slow`). Commodity books stay off the orderbook stream for now. Weekend REST polling is gated by hardcoded metals/energy dark hours in `backend/core/market_watchdog/venues/kalshi/schedule.py` (assume recent-month calendar; recheck periodically; new non-crypto symbols need their own close_time back-check before joining a cohort).

The trade is booked only after our own fill (`intent=upper_tail_fill`). Paper monitors book when the trigger qualifies.

Symbols: any 15m underlying whose `live_data_level` is `full` or `market`. AES does not enter these monitors. ATS supervises the open leg the same way as Expiration Scalp: the monitor stop-loss price is the opposite-ask floor, and floor flip sell follows that close when the monitor enables it. A stop price of 0 leaves the leg on until settlement. Lower Tail stays outside ATS.

Process: `upper_tail_agent_*` (port 8052 for user 0001). Strategy seed: migration `20261020_1645_taker_edge_strategy`.

---

## Production crypto hot path (latency) — live as of 2026-11-02 PT

**Audience:** live ops, `@analyst` / backtests that model Upper Tail fill timing, and anyone comparing replay to prod. **Do not invent slower crypto-OB lag** in new backtests unless you are deliberately replaying a pre-fix era.

### What is running on production

**Incident (2026-11-03):** Isolated priority-OB thread + shared `asyncio.Lock` across event loops wedged Kalshi OB ingest and collapsed crypto UT fills (from ~8–16 trades/hour to ~1).

**Safe design (current):** dedicated priority Kalshi OB socket for armed tickers on the **same main event loop** (no OS thread). Main keeps each ticker until `hot_ob_ready_markets` (priority snapshot received) — no silent feed gap. Isolated thread is **hard-disabled**. Stamp clamp retained.

| Piece | Behavior |
|--------|----------|
| **Priority OB WebSocket** | Separate Kalshi `orderbook_delta` connection for **armed Upper Tail crypto** tickers only (plus trade-monitor watch / explicit allowlist) — not the full 15m/hourly universe. |
| **Same-loop isolation** | That socket runs as a task on the **main event loop** (not an OS thread). `hot_ob_lock` separates hot apply from main lifecycle under the same loop. Isolated-thread mode is hard-disabled. |
| **Handoff** | Main keeps serving a ticker until `hot_ob_ready_markets` (priority snapshot received). Priority disconnect falls back to main without invalidating last levels. |
| **Flush** | Armed books flush to Redis on the hot path; `upper_tail_agent` consumes `path=hot` and places once on rail cross. |
| **Stamp hygiene** | Kalshi often omits or freezes `sending_ts_ms` / venue stamps on deltas. Watchdog **clamps** venue/sending to `t_ws_recv_ms` when the stamp is **>250ms older** than recv — so logs no longer show multi-second “stale” ages on fresh frames. |
| **Commodities** | Still **`path=slow`** (tape / timer). Not on this priority OB lane. |

Code homes: `backend/core/market_watchdog/venues/kalshi/ws_ingest.py`, `backend/core/orderbook_hot_publish_registry.py`, `backend/upper_tail_agent.py`. Probe: `scripts/diagnostics/kalshi_ob_ingest_latency_probe.py`.

### Problem we fixed (do not re-attribute to Kalshi)

Live A/B on prod: an idle probe saw Kalshi frames in **~7–10ms**. The same `(ticker, sending_ts_ms)` events on the old full-universe watchdog were often **~250ms p50 extra**, with fat tails to **seconds**. That was **our** shared-socket / event-loop queueing — not an inherent venue floor we cannot beat.

### Measured efficiency (post-fix, production)

| Stage | Typical (crypto hot path) |
|--------|---------------------------|
| Watchdog extra vs idle probe | **~0ms p50**; p99/max on the order of **~40ms** in healthy windows (not hundreds–thousands) |
| Agent-equivalent `source_age` on live hot Redis updates | **~0ms** p50/p99/max after clamp (venue/ts vs `t_ws_recv`) |
| Book in Redis after a BTC update | Often **~10–60ms** wall age while the book is printing |
| Detect → send (when a fire happens) | **~2–6ms** |
| Kalshi place RTT / detect→ack | **~20–30ms** (mostly venue RTT) |

**Operator judgment (2026-11-02):** for crypto Upper Tail **ingest → decide**, prod is as tight as we can make it without changing Kalshi. Remaining material latency on a fire is largely **exchange RTT**, not internal book queueing. Full stamped GTC under this exact build still accumulates as natural rail-crosses (or an explicit 1ct test) land; continuous ingest proof does not wait on that.

### Backtest implications

- **Forward-looking / “match current prod”** Upper Tail crypto models: assume **near-immediate** book awareness on rail touch (ms-scale internal lag), then **~20–30ms** order RTT — **not** multi-second OB staleness.
- **Historical** fills or replays from **before** this deploy may still show large `source_age_ms` / late entries; treat those as **pre-fix pipeline**, not the live baseline.
- Commodity Upper Tail remains **tape/`path=slow`** — do not copy crypto hot-path assumptions onto GOLD/SILVER/WTI.
- Diagnostic join key for A/B ingest probes: **`(market_ticker, sending_ts_ms)`** (not `seq` — seq is per-connection).
