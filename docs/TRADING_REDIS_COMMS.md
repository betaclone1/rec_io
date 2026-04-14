# Trading Redis communications

Internal service plane for trade execution, ATS, AES, monitor_manager, and UI fanout. **Does not** extend `redis_switchboard` (see `docs/REALTIME_BACKBONE.md`).

## Enable

Set `USE_TRADING_REDIS_COMMS=1` (or `true`/`yes`/`on`). When unset or false, call sites keep **HTTP fallback** to prior localhost URLs.

## Environment

| Variable | Default | Role |
|----------|---------|------|
| `USE_TRADING_REDIS_COMMS` | off | Prefer Redis streams/pubsub |
| `TRADING_REDIS_STREAM_EXECUTOR` | `trading:executor:trigger` | trade_manager → trade_executor (`trigger_trade`) |
| `TRADING_REDIS_STREAM_TM_STATUS` | `trading:tm:executor_status` | trade_executor → trade_manager (`update_trade_status`) |
| `TRADING_REDIS_STREAM_TM_COMMANDS` | `trading:tm:commands` | AES / ATS → trade_manager (`add_trade` body) |
| `TRADING_REDIS_STREAM_MM_MONITOR_SETTINGS` | `trading:mm:monitor_settings` | main_app → **monitor_manager**: unified auto entry/auto stop saves (`set_auto_entry_settings` body); result key `trading:mm:monitor_settings:ack:{correlation_id}` |
| `TRADING_REDIS_STREAM_MAXLEN` | `8000` | Approximate `XADD` maxlen |
| `REDIS_CHANNEL_ATS_TM_NOTIFICATIONS` | `rec_io:ats_tm_notifications` | trade_manager → ATS (non-`open` statuses) |
| `REDIS_CHANNEL_TRADING_PREFERENCES` | `rec_io:preferences` | UI-shaped events; main forwards to `/ws/preferences` |
| `REDIS_CHANNEL_MONITOR_MANAGER` | `rec_io:mm:trade_events` | trade_manager ↔ monitor_manager; bankroll hook from kalshi sync |
| `REDIS_CHANNEL_TM_POSITIONS_UPDATED` | `rec_io:tm:positions_updated` | kalshi_account_sync_ws → trade_manager (same JSON as `POST /api/positions_updated`) |
| `REDIS_CHANNEL_DB_CHANGES` | `rec_io:db_changes` | Same contract as main db_change forwarder |
| `REDIS_CHANNEL_KALSHI_LIFECYCLE_TRADES` | `rec_io:kalshi_lifecycle_trades` | `market_watchdog_ws` publishes Kalshi `market_lifecycle_v2` outcomes; each `kalshi_lifecycle_consumer_<NNNN>` applies to `users_NNNN.trades_NNNN` only |

Redis connection: `REDIS_URL` or `REDIS_HOST` / `REDIS_PORT` / `REDIS_PASSWORD` (same as ATS enrollment).

## Streams

- **Consumer groups:** `executor` (executor), `tm_status` (trade_manager), `tm_commands` (trade_manager), `mm_monitor_settings` (monitor_manager for auto trade menu saves).
- **Fields:** `type`, `correlation_id`, `source`, `ts`, `payload_json` (JSON string).
- **Idempotency:** handlers use Redis `SET NX` keys `trading:dedupe:*` with short TTL where duplicates are harmful.

## Pub/sub

- **ATS:** `open` remains `rec_io:ats_enroll_request` + ACK keys (`ats_enrollment_redis`). Other statuses use `rec_io:ats_tm_notifications` with `type: ats_tm_notification`.
- **Preferences:** JSON sent as published message body; main app subscribes and pushes to WebSocket clients (same shapes as legacy HTTP broadcast handlers where applicable).
- **DB changes:** `publish_db_change_json` must use `data` shaped like `broadcast_db_change`: `{"timestamp": ..., "change_data": {...}}`.
- **Portfolio → trade_manager:** `publish_positions_updated_notification` carries the same body as HTTP (`{"database": "positions"}` or `"orders"`). `trade_manager` starts a Redis subscriber in FastAPI lifespan when `USE_TRADING_REDIS_COMMS` is on. See `docs/PORTFOLIO_ACCOUNT_SYNC.md`.
- **Kalshi lifecycle → tenant trades:** JSON `{"type":"kalshi_lifecycle_trades","market_ticker":...,"result":...,"event_type":"determined"|"settled","source":"market_watchdog_ws"}`. Consumed by `backend/kalshi_lifecycle_trade_consumer.py` (one supervised process per user with `REC_USER_SCHEMA`).

## Module

Implementation: `backend/core/trading_redis_comms.py`.

## Cutover notes

- `trade_manager` consumes `TRADING_REDIS_STREAM_TM_COMMANDS` and applies commands by **HTTP POST to its own `/trades`** (same process). This removes cross-service HTTP from AES/ATS while keeping a single code path for trade creation until a deeper refactor.
- After enabling Redis in production, confirm consumers start with each process (trade_executor imports start the consumer thread; trade_manager starts consumers in FastAPI lifespan).

## Audit

Cross-reference checklist rows in `docs/REDIS_LEGACY_COMMS_AUDIT.md` (A2–A6, A3 bankroll + trade_manager positions_updated) when validating deployments.

## Multi-tenant workers vs browser HTTP

- **Supervised writers** (`trade_manager_NNNN`, `kalshi_account_sync_NNNN`, `kalshi_lifecycle_consumer_NNNN`, etc.) get `REC_USER_SCHEMA` / `REC_USER_NO` from supervisor config. They use **process** tenant context for `get_postgresql_connection()`, not browser session tokens.
- **Redis stream names** in the table above are **global** (not suffixed per user). Isolation is by **which process consumes** and by **payload** routing: each user’s trade_manager instance is a separate process with its own consumer identity; do not assume a stream is implicitly scoped to one tenant without checking the handler.
- **Browser-facing HTTP** tenant selection is **`read_api` + `backend/web/`** (Bearer / `auth_tokens.json` per `user_NNNN`). Workers do not read `auth_tokens.json`.
