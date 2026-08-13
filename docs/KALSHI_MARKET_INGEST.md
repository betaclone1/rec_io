# Kalshi market ingest (production)

**Exchange sharding:** Crypto markets live on Kalshi shard **2** after the 2026-08-24 cutover. Ticker strings and wall-clock subscribe/rollover are unchanged; see [KALSHI_EXCHANGE_SHARDING.md](KALSHI_EXCHANGE_SHARDING.md).

Production ingest is a **line-for-line port** of the verified sandbox feed test:

- Source: `scripts/sandbox/kalshi_market_feed/kalshi_market_ws_master.py`
- Baseline: `scripts/sandbox/kalshi_market_feed/CHECKPOINT_WS_ROLLOVER_BASELINE.md`

Implementation: `backend/core/market_watchdog/venues/kalshi/ws_ingest.py`  
Entry: `backend/market_watchdog_ws.py --exchange kalshi --market 15m|hourly`

## What was removed (no fallbacks)

| Removed | Replacement |
|---------|-------------|
| `backend/market_watchdog.py` | Deleted |
| `backend/core/kalshi_live_orderbook_sidecar.py` | Deleted |
| `kalshi_market_watchdog_*` supervisor programs | Gone |
| `MARKET_WATCHDOG_WS_ORDERBOOK_TABLES` (PG orderbook tables) | **Not set** — Redis depth only |
| `live_data.market_kalshi_*` writers | **None** in Python tree |
| Strike gen PG market snapshot fallback | **live_state only** (`LIVE_STATE_CACHE_ENABLED=1`) |
| Strike gen wake on `db_change` for `market_kalshi_*` | **live_state_updated only** |

## Supervisor

| Program | Command |
|---------|---------|
| `market_watchdog_ws_kalshi_15m` | `market_watchdog_ws.py --exchange kalshi --market 15m` |
| `market_watchdog_ws_kalshi_hourly` | `market_watchdog_ws.py --exchange kalshi --market hourly` |

Required env (set in `generate_unified_supervisor_config.py`):

- `LIVE_STATE_CACHE_ENABLED=1`
- `KALSHI_API_KEY_ID`, `KALSHI_PRIVATE_KEY_PATH`
- `REDIS_URL` or `REDIS_HOST` / `REDIS_PORT`

## Redis contracts (only hot path)

| Output | Key / channel |
|--------|----------------|
| Market ladder | `rec_io:live_state:v1:market:kalshi:{15m\|hourly}:{SYM}` |
| Orderbook depth | `trade_monitor:orderbook_levels:v1:{ticker}` |
| Fanout | `rec_io:live_state:updated` (`kind=market` / `kind=orderbook`) |
| Settled registry | `rec_io:market_watchdog:settled:v1` (15m process) |

Sandbox prefix `sandbox:kalshi:*` is **not** written in production.

## Rollover (must match checkpoint)

1. **No REST** at `:00/:15/:30/:45` — only `_subscription_sync` every ~1s with wall-clock live ticker.
2. **Outgoing** — schedule `outgoing` phase ticker on ticker WS only (not OB); `market_lifecycle_v2` for `market_result`.
3. **OB** — add new markets before delete old; channel `seq` + batched `get_snapshot` resync; coalesced Redis flush (~50ms).
4. **Logs** — `rollover_15m`, then `WS_ROLLOVER_OK market_result … (lifecycle_ws)`.

Verify (same as sandbox):

```bash
tail -f logs/market_watchdog_ws_kalshi.err.log | grep -E 'rollover_15m|WS_ROLLOVER_OK|get_snapshot'
```

**Live path cache monitor (local UI):** `http://localhost:3000/live-path-cache-monitor` — pick source
(`market`, `symbol`, `strike_ladder`, `active_trades`, or raw `redis_key`) and confirm WS updates.
Legacy URL `/active-trades-hot-path-test` redirects to the active-trades preset.

## Regenerate supervisor after pull

```bash
python3 scripts/config/generate_unified_supervisor_config.py
supervisorctl -c backend/supervisord.conf restart market_watchdog_ws_kalshi_15m market_watchdog_ws_kalshi_hourly strike_table_generator_ws_15m
```
