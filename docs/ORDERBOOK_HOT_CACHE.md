# Orderbook hot cache (HF backend)

Redis-backed orderbook depth for Kalshi contracts. Backend scripts and supervisors read the **levels key** directly; the trade monitor UI uses a separate WS fanout path.

## Keys

| Key | Content |
|-----|---------|
| `trade_monitor:orderbook_levels:v1:{market_ticker}` | Raw YES/NO level maps, `seq`, `ts_ms`, `redis_written_ms`, `valid` |
| `trade_monitor:orderbook_ws:v1:{market_ticker}` | Pre-serialized `live_orderbook` JSON (when watch active + prebuild enabled) |
| `rec_io:trade_monitor:orderbook_watch:v1` | Watched ticker for immediate flush + UI fanout |

## Latency timestamps

| Field | Meaning |
|-------|---------|
| `ts_ms` | Wall ms when `market_watchdog_ws` applied the delta in memory |
| `redis_written_ms` | Wall ms when the levels key was SET in Redis |
| Consumer `received_ms` | Wall ms when your script received the pub/sub hint |

**Apply → hot Redis:** `redis_written_ms - ts_ms`  
**Apply → consumer:** `received_ms - ts_ms`

Hot tickers (watch key + `MARKET_WATCHDOG_HOT_ORDERBOOK_TICKERS`) flush **immediately** after each delta. Cold tickers use `MARKET_WATCHDOG_PUBLISH_COALESCE_MS` (default 50ms).

## Pub/sub hint

Channel: `rec_io:live_state:updated` (env: `LIVE_STATE_UPDATED_CHANNEL`)

```json
{
  "type": "live_state_updated",
  "kind": "orderbook",
  "key": "trade_monitor:orderbook_levels:v1:KXBTC15M-...",
  "market_ticker": "KXBTC15M-...",
  "market_interval": "15m",
  "book_seq": 123456,
  "ts_ms": 1716234567890,
  "redis_written_ms": 1716234567895
}
```

## Python subscriber

```python
from backend.core.orderbook_hot_subscriber import (
    load_orderbook_cache_snapshot,
    start_orderbook_hot_subscriber,
)

def on_update(snap):
    print(snap.market_ticker, snap.seq, snap.apply_to_hot_ms, snap.apply_to_receive_ms)

start_orderbook_hot_subscriber(on_update, ticker_filter=lambda mt: mt.startswith("KXBTC15M-"))
```

## Latency probe

```bash
python3 scripts/dev/ob_latency_probe.py --duration 40
python3 scripts/dev/ob_latency_probe.py --ticker KXBTC15M-26MAY241830-30
```

## Environment (market_watchdog_ws_kalshi)

| Variable | Default | Purpose |
|----------|---------|---------|
| `MARKET_WATCHDOG_HOT_TICKER_FLUSH` | `1` | Immediate flush for hot tickers |
| `MARKET_WATCHDOG_HOT_ORDERBOOK_TICKERS` | empty | Extra always-hot tickers (comma-separated) |
| `MARKET_WATCHDOG_PUBLISH_COALESCE_MS` | `50` | Cold book batch interval only |
| `ORDERBOOK_PREBUILD_WS_PAYLOAD` | `1` | Prebuild WS JSON at flush for watched ticker |
| `TRADEFLOW_ORDERBOOK_TRIGGER_MIN_SEC` | `0.05` | AES/ATS wake coalesce on orderbook hints |

Restart `market_watchdog_ws_kalshi` after changing ingest env vars.
