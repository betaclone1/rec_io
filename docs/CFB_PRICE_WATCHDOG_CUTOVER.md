# CF Benchmarks price watchdog — cutover plan

**Status:** Local supervisor uses `cfbenchmarks_price_watchdog` (`live_state`) instead of four crypto `symbol_price_watchdog_*` programs. Production cutover is operator-driven.

**Goal:** Replace four `symbol_price_watchdog_{btc,eth,sol,xrp}` processes with one `cfbenchmarks_price_watchdog` that publishes the same hot-path contract as legacy Coinbase watchdogs.

---

## Current vs target

| | Legacy (today) | CFB (target) |
|---|----------------|--------------|
| Feed | Coinbase WS ×4 processes | Kalshi `cfbenchmarks_value` ×1 WS |
| Price | Coinbase spot | CFB index (BRTI, ETHUSD_RTI, SOLUSD_RTI, XRPUSD_RTI) |
| Hot path | `live_state_cache.set_symbol` → `live_state_updated` | **Same** (when `CFBENCHMARKS_PUBLISH_MODE=live_state`) |
| Test / shadow UI | N/A | `rec_io:experiment:cfbenchmarks:*` (optional in `experiment` / `shadow` modes) |
| Supervisor | 4 programs | 1 program (disable the four legacy programs on cutover) |

**Do not run legacy symbol watchdogs and CFB in `live_state` mode for the same symbols at the same time** — both would write `rec_io:live_state:v1:symbol:{SYM}`.

---

## Publish modes (`CFBENCHMARKS_PUBLISH_MODE`)

Controlled in `backend/cfbenchmarks_price_watchdog.py` via `backend/core/cfbenchmarks_publish.py`.

| Mode | Experiment Redis | `live_state` hot path | Use when |
|------|------------------|----------------------|----------|
| `experiment` (default) | Yes | No | Local test UI only (`cfb_test_ui_stack.sh`) |
| `shadow` | Yes | Yes | Pre-cutover validation: compare CFB vs Coinbase in parallel |
| `live_state` | No | Yes | Production cutover (legacy symbol WDs stopped) |

Optional (off by default): `CFBENCHMARKS_PG_TICKS=1` calls legacy `insert_tick()` for `live_data.live_price_log_1s_*`. See **PostgreSQL** below.

---

## Hot path contract (must match legacy)

Downstream consumers read **`live_state_cache.get_symbol_data(BTC|ETH|SOL|XRP)`**, not experiment keys.

1. Redis key: `rec_io:live_state:v1:symbol:{SYMBOL}`
2. Pub/sub: `rec_io:live_state:updated` with `kind=symbol`
3. Payload: full `tick_row` from `build_symbol_tick_row` plus CFB overrides:
   - `one_minute_avg` ← Kalshi `avg_60s_data.value` when present
   - `momentum_*_avg` ← CFB time-window deque (sparse-feed safe)
4. Env: same as legacy (`LIVE_STATE_CACHE_ENABLED=1`, `LIVE_STATE_USE_TICK_BUFFER=1`, DB creds, `REC_POOL_USER_NUMBER`, etc.)

Consumers (unchanged on cutover):

- `redis_switchboard` → `live_symbol_spot` / `/ws/live_market`
- `strike_table_generator_ws` (wake on symbol `live_state_updated`)
- `tradeflow` / monitors / trade manager (via `live_state` and PG history)

---

## Cutover phases (do not skip validation)

### Phase 0 — Today (default)

- `CFBENCHMARKS_PUBLISH_MODE=experiment`
- Legacy symbol watchdogs run in production
- Test UI: `/cfbenchmarks_feed_test` + `scripts/local/cfb_test_ui_stack.sh`

### Phase 1 — Shadow (no production switch)

1. Deploy code with publish modes.
2. Run **both**:
   - Legacy `symbol_price_watchdog_*` (unchanged, `live_state` writer)
   - `cfbenchmarks_price_watchdog` with `CFBENCHMARKS_PUBLISH_MODE=shadow`
3. Compare for several days:
   - `live_state` snapshots (CFB will overwrite if same key — **shadow cannot write same key as legacy**)

**Shadow correction:** In true parallel shadow, either:

- Compare via **experiment UI** (CFB) vs **production UI** (live_state from Coinbase), or
- Use a **forked Redis prefix** for shadow `live_state` (not implemented; compare via logs/metrics export instead), or
- Run shadow on **staging** with only CFB in `live_state` mode and no legacy WDs.

Recommended shadow on **local/staging**: stop legacy WDs, run CFB `live_state` only, validate downstream; keep prod on Coinbase until sign-off.

### Phase 2 — Staging cutover

1. Stop `symbol_price_watchdog_{btc,eth,sol,xrp}`.
2. Start `cfbenchmarks_price_watchdog` with `CFBENCHMARKS_PUBLISH_MODE=live_state`.
3. Verify:
   - Trade monitor spot / mom / 1m avg
   - Strike table generation latency and correctness
   - Auto-entry / tradeflow thresholds
   - Trade expiry `one_minute_avg` (PG history if enabled)
4. Run `scripts/db/check_db_schema_drift.py` only if enabling PG ticks.

### Phase 3 — Production cutover

1. Maintenance window or low-risk period.
2. Stop four legacy symbol watchdog programs.
3. Start `cfbenchmarks_price_watchdog` (`live_state` mode), autorestart on.
4. Confirm `live_state_updated` traffic and strike pipeline health.
5. Rollback: stop CFB WD, restart four legacy programs (keep `experiment` mode off in prod).

---

## Supervisor (local)

`scripts/config/generate_unified_supervisor_config.py` emits **`cfbenchmarks_price_watchdog`** only for crypto (no `symbol_price_watchdog_{btc,eth,sol,xrp}`). Finance indices (SPX/NDX) unchanged.

Regenerate via `MASTER_RESTART` or `python3 scripts/config/generate_unified_supervisor_config.py`.

Env on that program: `CFBENCHMARKS_PUBLISH_MODE=live_state`, `CFBENCHMARKS_RING_PG=1`, plus standard `LIVE_STATE_*` / DB / Redis from global supervisor env.

---

## Behavioral differences to accept or mitigate

| Topic | Legacy Coinbase | CFB |
|-------|-----------------|-----|
| Tick rate | ~1 Hz | ~1/min per index |
| Feed health | Stale **price** 180s → reconnect | Stale **tick drought** per index → reconnect (see below) |
| `one_minute_avg` | 60s tick buffer avg | Kalshi `avg_60s_data` (preferred for cutover) |
| Mom 1m percentile | 60-tick rolling on ~1 Hz buffer | 60s wall-clock on CFB momentum deque |
| Analytics profiles | Coinbase-calibrated | Same tables until retrained on CFB history |
| Strike regen | Wakes on `live_state_updated` (≤1 Hz effective) | ≤1/min — OK for strike cadence |

---

## Feed health (tick drought)

While the Kalshi WS is connected, a background loop checks **per index** that a `cfbenchmarks_value` tick arrived recently. Unlike legacy Coinbase **unchanged-price** reconnect, flat index levels over minutes are normal; we only reconnect when **no tick** is received.

| Env | Default | Meaning |
|-----|---------|---------|
| `CFB_FEED_STALE_TICK_SEC` | `180` | Per-index max seconds without a tick → close WS and reconnect. `0` disables. |
| `CFB_FEED_STALE_GRACE_SEC` | `120` | After subscribe, skip drought checks for this many seconds (first prints). |
| `CFB_FEED_HEALTH_CHECK_INTERVAL_SEC` | `30` | Evaluation interval while connected. |

Implementation: `backend/core/cfbenchmarks_feed_health.py`, wired in `cfbenchmarks_price_watchdog.py`. Experiment meta includes `feed_healthy`, `feed_age_sec_by_index`, and `feed_health_summary`.

---

## Expiration `symbol_close` (trade_manager)

On contract expiry, ``trade_manager`` sets ``symbol_close`` to the **mean CFB spot** (`price`) from ``live_data.live_price_ring_90m_*`` for ticks in **(expiry − 60s, expiry]** (EST). No ``live_price_log_1s_*``. If the ring window is empty, falls back to current ``live_state`` spot.

| Env | Default |
|-----|---------|
| `CFB_EXPIRATION_SYMBOL_CLOSE_WINDOW_SEC` | `60` |

---

## PostgreSQL ring buffer (`CFBENCHMARKS_RING_PG`)

Default **on**. Async writes to `live_data.live_price_ring_90m_{btc,eth,sol,xrp}` (~90 minutes, `timestamp` + `price` only). Does **not** block WS or `live_state`; failures are logged and dropped.

On startup, `hydrate_startup_buffers()` loads the ring into `symbol_tick_buffer` and replays the CFB momentum deque so deltas (through 30m) are valid immediately, minus restart downtime.

| Env | Default | Meaning |
|-----|---------|---------|
| `CFBENCHMARKS_RING_PG` | `1` | `0` disables ring writes and startup hydrate |
| `CFBENCHMARKS_RING_PG_RETENTION_MIN` | `90` | Rolling window (minutes) |

Migration: `20260603_1200_live_price_ring_90m`.

---

## PostgreSQL (`CFBENCHMARKS_PG_TICKS`)

Default **off**. Legacy `insert_tick()` rebuilds metrics from the in-process buffer (Coinbase-style), not the CFB `tick_row` overrides.

Enable only after validating:

- Whether prod uses `LIVE_STATE_DUAL_WRITE_PG=0` (cache-only hot path)
- Whether `live_price_log_1s_*` at ~1 row/min is acceptable for expiry lookups and analytics

If PG is required with CFB-shaped rows, add a dedicated insert path (future task); do not change `symbol_price_watchdog.py`.

---

## Rollback

1. `supervisorctl stop cfbenchmarks_price_watchdog`
2. `supervisorctl start symbol_price_watchdog_btc symbol_price_watchdog_eth symbol_price_watchdog_sol symbol_price_watchdog_xrp`
3. Confirm `live_state` updates resume within seconds

---

## Local commands

```bash
# Experiment only (default)
./scripts/local/cfb_test_ui_stack.sh

# Staging-style validation (live_state only, no legacy WDs)
export CFBENCHMARKS_PUBLISH_MODE=live_state
./scripts/local/cfb_test_ui_stack.sh   # extend script to pass mode when needed

# Stop minimal stack
./scripts/local/cfb_test_ui_stack_stop.sh
```

---

## Code map

| File | Role |
|------|------|
| `backend/cfbenchmarks_price_watchdog.py` | Kalshi WS ingest + feed-health loop |
| `backend/core/cfbenchmarks_feed_health.py` | Tick-drought detection / reconnect signal |
| `backend/core/cfbenchmarks_tick_metrics.py` | Metrics row (legacy builder + CFB overrides) |
| `backend/core/cfbenchmarks_publish.py` | Mode-gated experiment vs `live_state` publish |
| `backend/core/cfbenchmarks_feed_cache.py` | Experiment Redis only |
| `backend/symbol_price_watchdog.py` | **Unchanged** — reference implementation |

---

## Sign-off checklist (before prod)

- [ ] Staging ran `live_state` mode ≥ 24h without strike/tradeflow regressions
- [ ] Spot vs index spread understood and acceptable for Kalshi markets
- [ ] 1m avg vs Coinbase diff bounded during shadow/staging review
- [ ] Supervisor program added; four legacy programs disabled
- [ ] Rollback tested once on staging
- [ ] Owner explicit go for production cutover
