# Orderbook foundation (shared Redis levels)

Redis-backed Kalshi orderbook depth. **One book for every consumer** (AES, TM, UT, LT, UI, probes). Strategy arming does not create a separate feed.

## Keys

| Key | Content |
|-----|---------|
| `trade_monitor:orderbook_levels:v1:{market_ticker}` | Raw YES/NO level maps, seq, venue/local stamps, `valid` |
| `trade_monitor:orderbook_ws:v1:{market_ticker}` | Pre-serialized `live_orderbook` JSON (when TM watch active + prebuild enabled) |
| `rec_io:trade_monitor:orderbook_watch:v1` | TM UI watched ticker (wake / prebuild only) |
| `rec_io:upper_tail:orderbook_watch:v1` | Armed Upper Tail tickers (**wake only** — never gates Redis freshness) |

## Publish rule (foundation)

With `MARKET_WATCHDOG_IMMEDIATE_ORDERBOOK_FLUSH=1` (default):

1. Apply snapshot/delta in memory on the single Kalshi OB socket.
2. **Immediately** SET the levels key and publish a pub/sub hint.
3. Embed `yes` / `no` levels on **every** hint so subscribers can skip GET.
4. UI prebuild (heavy JSON) runs **after** the hint so it cannot delay book readers.

There is no “hot for Tail / cold for everyone else” flush policy. Coalesce (`MARKET_WATCHDOG_PUBLISH_COALESCE_MS`, default 50ms) only applies when immediate flush is disabled.

## Wake filters (not freshness)

AES/ATS orderbook wakes use `should_wake_tradeflow_on_orderbook` (crypto 15m + allowlist + TM watch + UT watch). That filter must never decide whether Redis gets the book.

## Latency timestamps

| Field | Meaning |
|-------|---------|
| `venue_ts_ms` | Kalshi `msg.ts_ms` |
| `sending_ts_ms` | Kalshi envelope `sending_ts_ms` (clamped when stale vs recv) |
| `ts_ms` | Event time for consumers: `venue_ts_ms` when present |
| `t_ws_recv_ms` | Local wall ms when WS frame received |
| `t_apply_ms` | Local wall ms when delta applied in memory |
| `redis_written_ms` | Wall ms when levels key was SET |
| Consumer `received_ms` | Wall ms when subscriber got the hint |

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
  "redis_written_ms": 1716234567902,
  "yes": {"0.99": "5"},
  "no": {"0.01": "10"},
  "valid": true
}
```

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
| `MARKET_WATCHDOG_HOT_CRYPTO_15M` | `1` | Include crypto 15m in **tradeflow wake** set |
| `MARKET_WATCHDOG_HOT_ORDERBOOK_TICKERS` | empty | Extra tradeflow-wake tickers |
| `MARKET_WATCHDOG_HOT_REGISTRY_REFRESH_SEC` | `0.05` | Watch/allowlist refresh for wake filters |
| `MARKET_WATCHDOG_PUBLISH_COALESCE_MS` | `50` | Fallback batch interval when immediate flush is off |
| `ORDERBOOK_PREBUILD_WS_PAYLOAD` | `1` | Prebuild WS JSON after hint for watched ticker |
| `TRADEFLOW_ORDERBOOK_TRIGGER_MIN_SEC` | `0.05` | AES/ATS wake coalesce on orderbook hints |

Restart `market_watchdog_ws_kalshi` after changing ingest env vars.
