# V4 direction (owner, 2026-10-21)

```yaml
doc_id: V4_DIRECTION
status: owner_direction
not: design, server_topology, milestone_plan, or implementation_steps
source: chat 2026-10-21, after AUDIT_V3_BASELINE
baseline: AUDIT_V3_BASELINE.md
postgres_working_assumption: self-managed on its own lean droplet (PG_AND_HOST_OPTIONS.md)
postgres_upgrade_gate: backbone system; updates and deprecations tested thoroughly before cutover (PG_AND_HOST_OPTIONS.md)
next: detail pass on that droplet (size, private networking, restore drill, PG 17 test plan). UI spec still undesigned
```

Agents treat the items below as constraints on later plans. Do not invent host counts, service maps, or a frontend information architecture until those discussions land in a new file in this folder.

---

## 1. CPU and process architecture

CPU load and how the system is deployed are a primary v4 workstream.

v3 production is one DigitalOcean droplet (`rec-io-server-new-york-1`, 8 vCPU, load about 7–9 at the 2026-10-21 audit) running nginx, PostgreSQL, Redis, live ingest, strike generation, automated trading, packaging, and the web app together. See `AUDIT_V3_BASELINE.md` §2.

v4 will explore breaking that into discrete production servers with separate responsibilities. Named areas so far:

| Area | Owns (intent) | v3 home today |
|------|----------------|---------------|
| `live_data_collection_and_archiving` | Market and index ingest, strike/snapshot capture, cycle packages, Drive or other archive | `market_watchdog_ws_kalshi`, `cfbenchmarks_price_watchdog`, `pyth_price_watchdog`, `strike_table_generator_ws_*`, `strike_snapshot_publisher`, `cycle_packager`, historical disk, Drive cron |
| `automated_trading` | Monitors, auto entry, active-trade stops, order placement, account sync, lifecycle | `auto_entry_supervisor_*`, `active_trade_supervisor_*`, `trade_manager_*`, `trade_executor_*`, `maker_edge_agent_*`, `taker_edge_agent_*`, `kalshi_account_sync_*`, `kalshi_lifecycle_consumer_*`, `monitor_manager_*`, `position_risk_engine` |
| `backtesting_and_analysis` | Historical replay, sweeps, research | Local scripts under `scripts/backtest/`, cycle packages, `analytics` schema. Not a production daemon tier today |
| `etc` | Unassigned. UI, bookkeeping, auth, and Postgres may land here or on their own hosts. Not decided |

Open (do not fill in):

- How many machines, which DigitalOcean products, and whether Postgres and Redis stay co-located with one tier or become shared services.
- What crosses the network (live_state, orders, packages) and what the latency budget is for the trading tier.
- Whether archiving stays on Google Drive or moves to object storage. The cycle-product note already says object storage is required only if the dataset is sold (`docs/HISTORICAL_CYCLE_DATA_PRODUCT.md`). That sale decision is separate from splitting servers.

---

## 2. Market scope for this push

Hourly trading is on the back burner. This push concentrates on **15-minute** markets.

```yaml
in_scope_interval: 15m
hourly: deferred
hourly_prod_flag: REC_ENABLE_HOURLY_LIVE=0
hourly_process_at_audit: strike_table_generator_ws_hourly was RUNNING with autostart=false
```

Do not plan hourly strategy work, hourly strike bandwidth, or hourly supervisor programs as part of the v4 push unless the owner reopens it. The still-running hourly strike process is an operational leftover from v3, not a requirement to keep.

Within 15m, scope widens:

- More crypto markets.
- More commodity markets.
- Other Kalshi categories are possible and not selected.

v3 symbol facts as of the 2026-10-22 production check (`AUDIT_V3_BASELINE.md` §0):

- Prod `symbols_list` with `live_data_level`: BTC and ETH `full`; SOL, XRP, GOLD, SILVER, WTI `market`; DOGE `none`.
- Strike generators take no `--symbols` list. Depth comes from that column.
- `live_data_level` is deployed. It is the current feed switch, not a v4 decision about which new symbols to add.

Maker Edge places outside the auto-entry supervisor. Taker Edge places in `taker_edge_agent` and, since v3.12.18, uses unified ATS for the floor stop and floor flip sell. Any 15m expansion has to say which execution path a new symbol uses and which `live_data_level` it gets.

Kalshi collateral stays per shard. Crypto orders debit `(exchange_index=2, subaccount=1)` today. A new category may be a different shard (`docs/KALSHI_EXCHANGE_SHARDING.md`). Do not assume one cash pool covers every new series.

---

## 3. Other top-line priority

A substantial UI frontend overhaul is a top-line v4 priority. Scope, surfaces (desktop, mobile, or both), and what stays are not specified yet.

v3 UI lives in `frontend/`, served by `main_app` (port 3000), with aggregate reads on `read_api` (port 3050) and realtime on `redis_switchboard` (port 3010). Parity rule in `AGENTS.md`: a frontend change should say whether the other surface needs the same behavior.

Bookkeeping (QuickBooks nightly journal) and Drive archives were audited and are not named as v4 themes in this note.

---

## 4. What a later design doc must answer

When the split and the UI are discussed, write a new file. Do not edit `AUDIT_V3_BASELINE.md` into a proposal. The design pass should at least record:

1. Process-to-host map for the areas in §1, including Postgres, Redis, nginx, cron (QuickBooks, droplet snapshot, DB dump).
2. Which 15m symbols are in the first trading set, and the feed depth each needs.
3. Which v3 processes are unused once hourly is ignored.
4. What the frontend overhaul is allowed to change (information architecture, tech stack, or both) and which API edges it still calls.
