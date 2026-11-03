# Orderbook hot cache (HF backend)

Redis-backed orderbook depth for Kalshi contracts. Backend scripts and supervisors read the **levels key** directly; the trade monitor UI uses a separate WS fanout path.

## Keys

| Key | Content |
|-----|---------|
| `trade_monitor:orderbook_levels:v1:{market_ticker}` | Raw YES/NO level maps, seq, venue/local stamps, `valid` |
| `trade_monitor:orderbook_ws:v1:{market_ticker}` | Pre-serialized `live_orderbook` JSON (when watch active + prebuild enabled) |
| `rec_io:trade_monitor:orderbook_watch:v1` | Watched ticker for immediate flush + UI fanout |
| `rec_io:upper_tail:orderbook_watch:v1` | Armed Upper Tail crypto tickers (unioned into hot set) |

## Latency timestamps

| Field | Meaning |
|-------|---------|
| `venue_ts_ms` | Kalshi `msg.ts_ms` — Unix ms of the latest book change included in the delta/snapshot |
| `sending_ts_ms` | Kalshi envelope `sending_ts_ms` — when the venue sent the WS frame |
| `ts_ms` | Event time for consumers: `venue_ts_ms` when present, else local apply ms |
| `t_ws_recv_ms` | Local wall ms when `market_watchdog_ws` received the WS frame |
| `t_apply_ms` | Local wall ms when the delta was applied in memory |
| `redis_written_ms` | Wall ms when the levels key was SET in Redis |
| Consumer `received_ms` | Wall ms when your script received the pub/sub hint |

**Venue hold (exchange):** `sending_ts_ms - venue_ts_ms`  
**Wire + apply:** `t_apply_ms - sending_ts_ms` (approx)  
**Apply → hot Redis:** `redis_written_ms - t_apply_ms`  
**Venue → consumer:** `received_ms - venue_ts_ms` (or `ts_ms`)

Hot tickers flush **immediately** after each delta (levels also embedded in the pub/sub hint so subscribers can skip Redis GET). Cold tickers use `MARKET_WATCHDOG_PUBLISH_COALESCE_MS` (default 50ms).

Always-hot by default: all `KX{BTC,ETH,SOL,XRP,DOGE}15M-*` books (`MARKET_WATCHDOG_HOT_CRYPTO_15M=1`).

Subscribe uses explicit `update_interval_ms: 0` (Kalshi real-time; 100/1000 would conflate public deltas).

## Pub/sub hint

Channel: `rec_io:live_state:updated` (env: `LIVE_STATE_UPDATED_CHANNEL`)

```json
{
  "type": "live_state_updated",
  "kind": "orderbook",
  "key": "",
  "market_ticker": "KXBTC15M-...",
  "market_interval": "15m",
  "book_seq": 123456,
  "ts_ms": 1716234567890,
  "venue_ts_ms": 1716234567890,
  "sending_ts_ms": 1716234567895,
  "t_ws_recv_ms": 1716234567900,
  "t_apply_ms": 1716234567901,
  "redis_written_ms": 1716234567902,
  "yes": {"0.99": "5"},
  "no": {"0.01": "10"},
  "valid": true
}
```

`yes` / `no` are present on hot flushes only.

## Python subscriber

```python
from backend.core.orderbook_hot_subscriber import (
    load_orderbook_cache_snapshot,
    start_orderbook_hot_subscriber,
)

def on_update(snap):
    print(
        snap.market_ticker,
        snap.seq,
        snap.venue_ts_ms,
        snap.apply_to_hot_ms,
        snap.apply_to_receive_ms,
        snap.from_hint,
    )

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
| `MARKET_WATCHDOG_HOT_CRYPTO_15M` | `1` | Always-hot crypto 15m books |
| `MARKET_WATCHDOG_HOT_ORDERBOOK_TICKERS` | empty | Extra always-hot tickers (comma-separated) |
| `MARKET_WATCHDOG_HOT_REGISTRY_REFRESH_SEC` | `0.05` | How often watch/UT allowlists are reloaded |
| `MARKET_WATCHDOG_PUBLISH_COALESCE_MS` | `50` | Cold book batch interval only |
| `ORDERBOOK_PREBUILD_WS_PAYLOAD` | `1` | Prebuild WS JSON at flush for watched ticker |
| `TRADEFLOW_ORDERBOOK_TRIGGER_MIN_SEC` | `0.05` | AES/ATS wake coalesce on orderbook hints |

Restart `market_watchdog_ws_kalshi` after changing ingest env vars.
