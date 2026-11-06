# Orderbook foundation (shared Redis levels)

Redis-backed Kalshi orderbook depth. **One book for every consumer** (AES, TM, UT, LT, UI, probes). Strategy arming does not create a separate feed.

**Owner:** non-lean 15m books are published by `kalshi_orderbook_live` (lab architecture: WS → RAM apply → latest-wins Redis). With `REC_KALSHI_OB_LIVE_OWNER=1` (default), `market_watchdog_ws_kalshi` does **not** subscribe those OB markets — dual ownership destroyed live-view latency (~1s venue→recv).

Blank-slate lab lessons: **lean pub/sub hints**, **pre-subscribe next 15m cycle**, **never block the WS loop on Redis**.

## Keys

| Key | Content |
|-----|---------|
| `trade_monitor:orderbook_levels:v1:{market_ticker}` | Raw YES/NO level maps, seq, venue/local stamps, `valid` (**SoT for depth**) |
| `trade_monitor:orderbook_ws:v1:{market_ticker}` | Pre-serialized `live_orderbook` JSON (when TM watch active + prebuild enabled) |
| `rec_io:trade_monitor:orderbook_watch:v1` | TM UI watched ticker (wake / prebuild only) |
| `rec_io:upper_tail:orderbook_watch:v1` | Armed Upper Tail tickers (**wake only** — never gates Redis freshness) |

## Publish rule (foundation)

With `MARKET_WATCHDOG_IMMEDIATE_ORDERBOOK_FLUSH=1` (default):

1. Apply snapshot/delta in memory on the single Kalshi OB socket.
2. **Immediately** SET the levels key.
3. Publish a **lean** pub/sub hint (ticker + seq + latency stamps — **no** embedded `yes`/`no`).
4. UI prebuild (heavy JSON) runs **after** the hint so it cannot delay book readers.

There is no “hot for Tail / cold for everyone else” flush policy. Coalesce (`MARKET_WATCHDOG_PUBLISH_COALESCE_MS`, default 50ms) only applies when immediate flush is disabled.

## Pre-subscribe (15m rollover)

Non-lean 15m symbols keep **current + next** market tickers on the OB channel. The next cycle is quiet until open; at the boundary the clock advances and the prior ticker drops via normal subscription sync. Tradeflow wake and cycle-hot PG enqueue only follow the **current** clock ticker.

## Wake filters (not freshness)

AES/ATS orderbook wakes use `should_wake_tradeflow_on_orderbook` (live crypto 15m **current** cycle + allowlist + TM watch). That filter must never decide whether Redis gets the book. Pre-subscribed next-cycle books do not wake AES until they become current.

## Latency timestamps

| Field | Meaning |
|-------|---------|
| `venue_ts_ms` | Raw Kalshi `msg.ts_ms` (None if omitted; never rewritten to local recv) |
| `sending_ts_ms` | Raw Kalshi envelope `sending_ts_ms` (None if omitted) |
| `ts_ms` | Event time for consumers: `venue_ts_ms` when present, else `t_apply_ms` |
| `t_ws_recv_ms` | Local wall ms when WS frame received |
| `t_apply_ms` | Local wall ms when delta applied in memory |
| `redis_written_ms` | Wall ms when levels key was SET |
| Consumer `received_ms` | Wall ms when subscriber got the hint |

**Latency:** `t_ws_recv_ms − venue_ts_ms` (and vs `sending_ts_ms`). Cycle-package `deltas.csv` / `_deltas` rows store `ts_ms`, `sending_ts_ms`, `t_ws_recv_ms` beside `received_at` so sealed archives can measure the same gap.

Subscribe uses explicit `update_interval_ms: 0` (Kalshi real-time).

## Pub/sub hint

Channel: `rec_io:live_state:updated` (env: `LIVE_STATE_UPDATED_CHANNEL`)

```json
{
  "type": "live_state_updated",
  "kind": "orderbook",
  "market_ticker": "KXBTC15M-...",
  "book_seq": 123456,
  "ts_ms": 1716234567890,
  "venue_ts_ms": 1716234567890,
  "sending_ts_ms": 1716234567895,
  "t_ws_recv_ms": 1716234567900,
  "t_apply_ms": 1716234567901,
  "redis_written_ms": 1716234567902
}
```

Consumers that need depth: `GET trade_monitor:orderbook_levels:v1:{market_ticker}` (see `orderbook_hot_subscriber.load_orderbook_cache_snapshot`).

## Python subscriber

```python
from backend.core.orderbook_hot_subscriber import (
    start_orderbook_hot_subscriber,
)

def on_update(snap):
    print(snap.market_ticker, snap.seq, snap.from_hint, snap.apply_to_hot_ms)

start_orderbook_hot_subscriber(on_update, ticker_filter=lambda mt: mt.startswith("KXBTC15M-"))
```

## Latency probe

```bash
python3 scripts/dev/ob_latency_probe.py --duration 40
python3 scripts/dev/ob_latency_probe.py --ticker KXBTC15M-26MAY241830-30
```

## Environment (`market_watchdog_ws_kalshi`)

| Variable | Default | Purpose |
|----------|---------|---------|
| `MARKET_WATCHDOG_IMMEDIATE_ORDERBOOK_FLUSH` | `1` | Immediate Redis publish for every dirty OB/ticker |
| `MARKET_WATCHDOG_HOT_TICKER_FLUSH` | (alias) | Same as immediate flush (back-compat) |
| `MARKET_WATCHDOG_HOT_CRYPTO_15M` | `1` | Include **live current** crypto 15m in tradeflow wake set |
| `MARKET_WATCHDOG_HOT_ORDERBOOK_TICKERS` | empty | Extra tradeflow-wake tickers |
| `MARKET_WATCHDOG_HOT_REGISTRY_REFRESH_SEC` | `0.05` | Watch/allowlist refresh for wake filters |
| `MARKET_WATCHDOG_PUBLISH_COALESCE_MS` | `50` | Fallback batch interval when immediate flush is off |
| `ORDERBOOK_PREBUILD_WS_PAYLOAD` | `1` | Prebuild WS JSON after hint for watched ticker |
| `TRADEFLOW_ORDERBOOK_TRIGGER_MIN_SEC` | `0.05` | AES/ATS wake coalesce on orderbook hints |

Restart `market_watchdog_ws_kalshi` after changing ingest env vars.
