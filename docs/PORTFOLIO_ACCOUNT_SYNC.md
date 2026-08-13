# Portfolio / account sync pipeline

This document describes [`backend/kalshi_account_sync_ws.py`](../backend/kalshi_account_sync_ws.py): Kalshi REST usage, WebSocket subscriptions, internal notifications, and environment knobs. Official Kalshi WebSocket contract: [WebSocket connection](https://docs.kalshi.com/websockets/websocket-connection).

## High-level flow

```mermaid
flowchart LR
  subgraph kalshi [Kalshi]
    WS[WSS v2]
    REST[REST portfolio APIs]
  end
  subgraph sync [kalshi_account_sync_ws]
    HOT[live_state hot hash]
    SPOOL[PG spool fills/orders]
    Q[Quick periodic]
    F[Full reconcile]
  end
  WS -->|market_position| HOT
  WS -->|fill user_orders| HOT
  WS -->|fill user_orders| SPOOL
  Q --> REST
  F --> REST
  F --> SPOOL
```

Portfolio **hot state** is **WebSocket-driven** for live upserts. **Startup baseline** seeds Redis from REST: current positions snapshot plus the prior **`LIVE_STATE_KALSHI_PORTFOLIO_RETENTION_HOURS`** (default 1h) of fills and orders via paginated `min_ts` polls. Ongoing: positions use WS upserts with periodic REST **prune only** (no REST upsert on the timer); fills/orders stay WS + spool.

## Hot path (live_state)

| Entity | Redis key | PG | WS action |
|--------|-----------|-----|-----------|
| Positions | `rec_io:live_state:v1:tenant:{slot}:kalshi:positions` | **None** (ephemeral) | REST baseline on startup; WS upserts live; REST timer prune only |
| Orders | `...:kalshi:orders` | Spooled upsert (history) | REST baseline (1h) on startup; WS upserts + spool live |
| Fills | `...:kalshi:fills` | Spooled upsert (history) | REST baseline (1h) on startup; WS upserts + spool live |

Pub/sub: `rec_io:live_state:updated` with kinds `kalshi_positions`, `kalshi_orders`, `kalshi_fills`.

Monitor: `/live-path-cache-monitor?source=kalshi_positions&user_no=0001` (also `kalshi_orders`, `kalshi_fills`).

Account manager **Open Positions** reads hot state via `GET /api/db/positions` (not PG). **Recent fills** use `GET /api/db/fills` from the hot fills hash (rolling window), not PG.

**Live tradeflow:** `trade_manager` `confirm_open_trade` / `confirm_close_trade` read order status, counts, and fee/cost fields from the **orders hot hash** only (`tradeflow_live_reads.kalshi_order` → `live_state_kalshi_portfolio.get_order`). PostgreSQL `orders_*` is historical spool only. Trade rows (`trades_*`) remain in PG.

Env: `LIVE_STATE_KALSHI_PORTFOLIO_RETENTION_HOURS` (default 1, fills/orders hot window), `PORTFOLIO_PG_SPOOL_FLUSH_MS` (default 250), `PORTFOLIO_PG_SPOOL_MAX_BATCH` (default 50), `ACCOUNT_SYNC_POSITIONS_PRUNE_SEC` (default 300), `ACCOUNT_SYNC_HOT_EXECUTOR_WORKERS` (default 4), `ACCOUNT_SYNC_REST_EXECUTOR_WORKERS` (default 1).

## REST inventory

| Function | HTTP | When it runs |
|----------|------|--------------|
| `sync_balance` | `GET /portfolio/subaccounts/balances` | Step 1: upsert live `users.subaccounts_*` cash per Kalshi subaccount (matrix → `exchange_*_balance`, `balance` = sum) |
| `sync_balance` | `GET /portfolio/balance?subaccount=N` | Step 2: position marks; sab history gets matrix cash + these marks → `subaccount_balance_*_<n>` |
| `sync_balance` (aggregate) | — | Step 3: sum latest sab snapshots → hero `account_balance_*`; bankroll from subaccount 1 |
| `sync_balance(full=True)` | same as above | **Startup baseline only** — disables 120s hero throttle so every subaccount + hero row is refreshed after `MASTER_RESTART` |
| `sync_portfolio_hot_state_baseline` | positions + fills + orders REST | **Startup only** — positions snapshot; fills/orders paginated with `min_ts` = retention window |
| `sync_positions_prune_hot_state` | `GET .../portfolio/positions?limit=200` | Every `ACCOUNT_SYNC_POSITIONS_PRUNE_SEC` (default 300s); **prune only** (no hot upsert) |
| `sync_fills` | `GET .../portfolio/fills?limit=50` | Full reconcile; initial baseline (**PG only**, not hot hash) |
| `sync_orders` | `GET .../portfolio/orders?limit=50` | Full reconcile; initial baseline (**PG only**, not hot hash) |
| `sync_settlements` | `GET .../portfolio/settlements?limit=50` | Quick periodic; full reconcile; initial baseline |
| `sync_account_history` | v1 paged deposits + withdrawals | Inside `sync_balance` when Kalshi user id is available |
| Manual internal transfer | `POST /portfolio/subaccounts/transfer` | Account manager `initiate-transfer` (live); then `sync_balance` repoll |

**Live subaccounts:** #0 = **CASH** (deposits/withdrawals), #1 = **Master Trading Bankroll** (hero bankroll), #2+ = ancillary (`undefined_2`, …). No deposit/withdrawal routing. Orders default to **subaccount 1** via `trade_executor`.

**Exchange sharding:** Kalshi balances are a **`(exchange_index, subaccount)`** matrix. After crypto cutover, trading MTB is **`(2, 1)`**; cross-shard moves use IAT through primaries only. Schema: `exchange_0..3_balance` on `subaccounts_*` / `subaccount_balance_*_*` (migration **`20260813_1448_subaccount_exchange_balances`**); `balance` = sum. Full model: [KALSHI_EXCHANGE_SHARDING.md](KALSHI_EXCHANGE_SHARDING.md).

**Automatic MTB rake (live):** When MTB `realized_pnl_pct` ≥ `target_pnl__pct` and `automatic_transfers` is on, `poll_live_account_balances` calls `POST /portfolio/subaccounts/transfer` **#1 → #0** for `transfer_amt × base_value` cents, updates MTB `base_value` in DB, then **repolls all subaccounts** (no throttle). Paper mode simulates the same destination (**CASH**) in `subaccounts_update` without Kalshi.

**Settlement balance glitch guard (live):** Kalshi `GET /portfolio/balance?subaccount=1` can race around settlement in two ways:

1. **Overstatement:** settlement cash in `balance` while `portfolio_value` still includes the settled mark (cash up, PV flat/up).
2. **Understatement:** buys already debited and marks cleared before settlement credits land (large one-tick portfolio drop; e.g. ~50% false drawdown).

[`poll_live_account_balances`](../backend/balance_snapshot.py) detects both on **MTB (subaccount 1)**. On match it **skips the DB write**, logs `balance_settlement_glitch_skipped` (WARNING), sleeps per `REC_BALANCE_GLITCH_REPOLL_DELAYS_SEC` (default `2,3,5`), and repolls until clean (`balance_settlement_glitch_cleared` INFO). If retries exhaust: **overstatement** keeps the last good row; **understatement** writes the confirmed low reading (API consistently low). Disabled when `REC_BALANCE_GLITCH_GUARD=0`, on automatic MTB rake repoll, or when `sync_balance` saw new external deposit events that cycle (`deposit_cycle`).

**Drawdown halt confirmation:** Emergency halt (`bankroll_stepped_down`) requires `REC_DRAWDOWN_HALT_CONFIRM_TICKS` consecutive crash-sized readings (default `2`): the previous written portfolio must already be at/below the drawdown threshold before the crossing fires. First observation keeps sticky `bankroll_current` and does not halt.

| Env | Default | Purpose |
|-----|---------|---------|
| `REC_BALANCE_GLITCH_GUARD` | `1` | `0` / `false` disables settlement glitch skip+repoll |
| `REC_BALANCE_GLITCH_MIN_CASH_DELTA_CENTS` | `1000` | Minimum cash increase ($10) before overstatement heuristic runs |
| `REC_BALANCE_GLITCH_REPOLL_DELAYS_SEC` | `2,3,5` | Comma-separated sleeps between repoll attempts after a skipped write |
| `REC_BALANCE_UNDERSTATEMENT_MIN_DROP_RATIO` | `0.25` | Min fraction of prior portfolio dropped in one tick to treat as understatement |
| `REC_BALANCE_UNDERSTATEMENT_MIN_DROP_CENTS` | `10000` | Min absolute portfolio drop ($100) for understatement heuristic |
| `REC_DRAWDOWN_HALT_CONFIRM_TICKS` | `2` | Consecutive below-threshold portfolio observations before emergency halt (`1` = immediate) |

**Note:** `limit=50` on fills/orders/settlements means long-tail completeness depends on **full reconciliation** (`ACCOUNT_SYNC_FULL_RECONCILE_SEC`, default 900s) and periodic quick syncs.

## WebSocket

- **URL:** `wss://external-api-ws.kalshi.com/trade-api/ws/v2` (same host as docs; credentials via `KALSHI-ACCESS-*` headers on handshake).
- **Channels (single subscribe):** `market_positions`, `fill`, `user_orders` (see Kalshi subscribe command).
- **Behavior:** `market_position` → live_state positions hash (`position_cost_dollars`, `position_fp`, etc.); balance debounced. `fill` / `user_orders` → live_state hash + PG spool; balance debounced. PoC logging for first N fill/order messages.

## Timers

| Timer | Env | Default | Purpose |
|-------|-----|---------|---------|
| Debounce | `ACCOUNT_SYNC_DEBOUNCE_MS` | 400 | Coalesce rapid WS events before REST (fills/orders PG, balance) |
| Quick | `ACCOUNT_SYNC_QUICK_PERIODIC_SEC` | 300 | `sync_settlements` + `sync_balance` |
| Positions prune | `ACCOUNT_SYNC_POSITIONS_PRUNE_SEC` | 300 | REST positions poll → drop stale hot hash keys |
| Full | `ACCOUNT_SYNC_FULL_RECONCILE_SEC` | 900 | Fills/orders/settlements/balance REST (not hot hash) |

## Internal comms (after portfolio-plane Redis work)

| Target | Mechanism |
|--------|-----------|
| `main` db_change fanout | `publish_db_change_json` when `USE_TRADING_REDIS_COMMS`, else `POST /api/notify_db_change` |
| `monitor_manager` bankroll | `PUBLISH` `rec_io:mm:trade_events` (or `REDIS_CHANNEL_MONITOR_MANAGER`), else HTTP |
| `trade_manager` `positions_updated` | `PUBLISH` `rec_io:tm:positions_updated` (or `REDIS_CHANNEL_TM_POSITIONS_UPDATED`), else `POST /api/positions_updated` |

See also [TRADING_REDIS_COMMS.md](TRADING_REDIS_COMMS.md) and [REDIS_LEGACY_COMMS_AUDIT.md](REDIS_LEGACY_COMMS_AUDIT.md) section A3 / portfolio.
