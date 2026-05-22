# Production CPU & RAM baseline (pre–Kalshi market ingest refactor)

**Purpose:** Snapshot before deploying the unified `market_watchdog_ws` / live-state refactor. Re-run the same audit after deploy and compare sections side by side.

| Field | Value |
|-------|--------|
| **Captured (UTC)** | 2026-05-22T20:52:15Z |
| **Host** | `rec-io-server-new-york-1` (`165.22.13.146`) |
| **Uptime** | 51 days |
| **Deployed commit** | `51c69daf5f71cedd781d15d7b80dea743a50c9be` — `51c69da market-wide LP debug` |
| **Supervisor uptime** | ~4 days 4 hours (last restart ~2026-05-18) |

---

## How to re-run after deploy

From repo root (same machine / SSH key as prod):

```bash
chmod +x scripts/prod/prod_cpu_ram_audit.sh
./scripts/prod/prod_cpu_ram_audit.sh | tee docs/perf-audits/prod_audit_POST_$(date -u +%Y%m%dT%H%M%SZ).txt
```

Copy key tables into a new doc: `docs/perf-audits/PROD_CPU_RAM_POST_KALSHI_INGEST_REFACTOR_<date>.md`, or append a **Post-deploy** section below.

**Compare these first (refactor-sensitive):**

| Metric | Pre-deploy (this doc) | Post-deploy (fill in) |
|--------|----------------------|------------------------|
| `market_watchdog_ws` process count | 2 supervised (+ see note) | |
| `market_watchdog_ws` RSS total | **188.6 MB** (100.7 + 87.9) | |
| `market_watchdog_ws` CPU sum | **76.1%** | |
| Python `/opt/rec_io_server` RSS total | **1307.4 MB** | |
| Python process count | **23** | |
| Load avg (1m / 5m / 15m) | **8.87 / 7.63 / 7.52** | |
| Redis `used_memory_human` | **28.39M** | |
| Postgres `rec_io` backend RSS | **1025.5 MB** (12 backends) | |

---

## System summary

| Resource | Value |
|----------|--------|
| **vCPUs** | 8 (DO-Premium-AMD, 1 thread/core) |
| **RAM** | 16 GiB total |
| **RAM available** | ~13.7 GiB (`MemAvailable` 14,352,396 kB) |
| **RAM used (apps)** | ~1.4 GiB in `free` row; heavy page cache (~13 GiB buff/cache) |
| **Swap** | None (0 B) |
| **Disk /** | 310G ext4, **80G used (26%)**, 230G free |
| **Load average** | **8.87, 7.63, 7.52** on 8 CPUs → sustained **~100%+ CPU utilization** |

`vmstat` sample (3s): user CPU ~38–60%, idle often **1–2%** — host is CPU-bound under current workload.

---

## Supervisor programs (21 processes, user 0001 only)

All **RUNNING**. Sorted by RSS (snapshot at audit time).

| Program | PID | RSS (MB) | CPU % | %MEM | Uptime |
|---------|-----|----------|-------|------|--------|
| market_watchdog_ws_kalshi_hourly | 3544260 | **100.7** | **38.5** | 0.6% | 4d 4h |
| main_app | 3543268 | 95.6 | 5.3 | 0.5% | 4d 4h |
| trade_manager_0001 | 3550682 | 91.9 | 0.9 | 0.5% | 4d 4h |
| market_watchdog_ws_kalshi_15m | 3543750 | **87.9** | **37.6** | 0.5% | 4d 4h |
| read_api | 3545192 | 76.4 | 1.8 | 0.4% | 4d 4h |
| monitor_manager_0001 | 3544723 | 73.0 | 0.1 | 0.4% | 4d 4h |
| kalshi_account_sync_0001 | 3542299 | 71.4 | 0.2 | 0.4% | 4d 4h |
| auto_entry_supervisor_0001 | 3541345 | 68.7 | **21.9** | 0.4% | 4d 4h |
| active_trade_supervisor_0001 | 3541194 | 62.1 | 3.2 | 0.3% | 4d 4h |
| kalshi_lifecycle_consumer_0001 | 3542746 | 62.1 | 0.8 | 0.3% | 4d 4h |
| symbol_price_watchdog_btc | 3547219 | 58.5 | 9.6 | 0.3% | 4d 4h |
| symbol_price_watchdog_eth | 3547682 | 58.1 | 6.1 | 0.3% | 4d 4h |
| symbol_price_watchdog_xrp | 3548531 | 58.1 | 4.7 | 0.3% | 4d 4h |
| symbol_price_watchdog_sol | 3548105 | 58.0 | 4.6 | 0.3% | 4d 4h |
| trade_executor_0001 | 3549359 | 50.4 | 0.0 | 0.3% | 4d 4h |
| redis_switchboard | 3545676 | 46.5 | 5.7 | 0.2% | 4d 4h |
| system_monitor | 3548938 | 34.6 | 0.5 | 0.2% | 4d 4h |
| strike_table_generator_ws_hourly | 3546851 | 32.7 | 8.7 | 0.2% | 4d 4h |
| strike_table_generator_ws_15m | 3546464 | 32.6 | 8.1 | 0.2% | 4d 4h |
| strike_snapshot_publisher | 3546092 | 29.0 | 9.3 | 0.1% | 4d 4h |
| cascading_failure_detector | 3541807 | 23.9 | 0.0 | 0.1% | 4d 4h |

**Pre-refactor architecture note:** Production runs **two** Kalshi WS watchdog processes (`market_watchdog_ws_kalshi_15m` and `market_watchdog_ws_kalshi_hourly`). Local refactor target is a **single** `market_watchdog_ws_kalshi` with `--market` filtering — compare process count, combined RSS, and combined CPU after deploy.

---

## By backend script (`backend/*.py`)

One row per **script file**. Where supervisor runs multiple processes for the same script, instances are listed and totals are summed.

| Script | Supervisor instance(s) | Procs | RSS (MB) | CPU % | Notes |
|--------|------------------------|-------|----------|-------|--------|
| `market_watchdog_ws.py` | `market_watchdog_ws_kalshi_hourly`, `market_watchdog_ws_kalshi_15m` | 2 | **188.6** | **76.1** | `--market hourly` + `--market 15m` |
| `main.py` | `main_app` | 1 | 95.6 | 5.3 | Browser edge / WS hub |
| `trade_manager.py` | `trade_manager_0001` | 1 | 91.9 | 0.9 | |
| `read_api.py` | `read_api` | 1 | 76.4 | 1.8 | |
| `monitor_manager.py` | `monitor_manager_0001` | 1 | 73.0 | 0.1 | |
| `kalshi_account_sync_ws.py` | `kalshi_account_sync_0001` | 1 | 71.4 | 0.2 | |
| `auto_entry_supervisor.py` | `auto_entry_supervisor_0001` | 1 | 68.7 | 21.9 | `unified` |
| `active_trade_supervisor.py` | `active_trade_supervisor_0001` | 1 | 62.1 | 3.2 | `unified` |
| `kalshi_lifecycle_trade_consumer.py` | `kalshi_lifecycle_consumer_0001` | 1 | 62.1 | 0.8 | |
| `symbol_price_watchdog.py` | `symbol_price_watchdog_{btc,eth,sol,xrp}` | 4 | **232.7** | **25.0** | One process per symbol |
| `trade_executor.py` | `trade_executor_0001` | 1 | 50.4 | 0.0 | |
| `redis_switchboard.py` | `redis_switchboard` | 1 | 46.5 | 5.7 | |
| `system_monitor.py` | `system_monitor` | 1 | 34.6 | 0.5 | |
| `strike_table_generator_ws.py` | `strike_table_generator_ws_{hourly,15m}` | 2 | **65.3** | **16.8** | `--market hourly` + `15m` |
| `strike_snapshot_publisher.py` | `strike_snapshot_publisher` | 1 | 29.0 | 9.3 | |
| `cascading_failure_detector.py` | `cascading_failure_detector` | 1 | 23.9 | 0.0 | |

**Sum of scripted services above:** ~**1294 MB RSS**, ~**168% CPU** (instantaneous %CPU sums across cores; can exceed 100% on multi-core).

---

## Group totals (rec_io Python)

| Group | Processes | RSS (MB) | CPU sum (%) |
|-------|-----------|----------|-------------|
| **All python under `/opt/rec_io_server`** | 23 | **1307.4** | (see top-CPU; sum ~227% system-wide includes postgres) |
| market_watchdog_ws (all matching) | 3* | **191.7** | **76.1** |
| strike_table_generator_ws | 3* | **68.3** | **16.8** |
| symbol_price_watchdog (BTC/ETH/SOL/XRP) | 5* | **235.7** | **25.0** |

\*Process counts from `ps` grouping may include short-lived or duplicate argv lines; supervisor lists **2** watchdogs, **2** strike generators, **4** symbol watchdogs.

---

## Top CPU consumers (instantaneous)

| PID | RSS (MB) | CPU % | Command |
|-----|----------|-------|---------|
| 3544260 | 100.7 | 38.5 | `market_watchdog_ws.py --market hourly` |
| 3543750 | 87.9 | 37.6 | `market_watchdog_ws.py --market 15m` |
| 3541345 | 68.7 | 21.9 | `auto_entry_supervisor.py unified` |
| 929 | 24.3 | 13.4 | postgres main |
| 3543907 | 154.4 | 10.1 | postgres backend (rec_io_user) |
| 3547219 | 58.5 | 9.6 | `symbol_price_watchdog.py BTC` |
| 3546092 | 29.0 | 9.3 | `strike_snapshot_publisher.py` |
| 3546851 | 32.7 | 8.7 | `strike_table_generator_ws.py --market hourly` |
| 3546464 | 32.6 | 8.1 | `strike_table_generator_ws.py --market 15m` |

**Largest memory (non-Postgres):** same two `market_watchdog_ws` processes (~189 MB combined) plus `main_app` (~96 MB).

---

## Redis

| Metric | Value |
|--------|--------|
| used_memory | 28.39M |
| used_memory_rss | 37.89M |
| peak | 28.68M |
| fragmentation ratio | 1.34 |
| DBSIZE | 174 keys (158 with TTL) |

---

## PostgreSQL 14

| Metric | Value |
|--------|--------|
| Version | PostgreSQL 14.18 (Ubuntu) |
| Database size | **64 GB** |
| Connections (rec_io_db) | **15** |
| By state | idle in transaction: 6, idle: 5, active: 4 |
| rec_io backend RSS (sample) | **~1025 MB** across 12 client backends |

Several backends show elevated CPU (~9–10%) and ~160 MB RSS each (remote clients on `165.22.13.146`).

---

## System-wide process totals

| Scope | RSS (MB) | Process count |
|-------|----------|---------------|
| All processes on host | ~3143 | 204 |
| All `/opt/rec_io_server` | ~1310 | 23 |

---

## Observations for post-deploy review

1. **CPU headroom is tight:** load ~8.9 on 8 cores with watchdog + AES dominating. Any regression that adds a third full WS ingest path without removing the two existing ones will likely worsen latency.
2. **Watchdog split is the main refactor lever:** ~76% CPU and ~189 MB RSS tied to dual `market_watchdog_ws` — primary success metric is lower combined CPU/RSS with **one** healthy ingest process.
3. **RAM is not the bottleneck:** ~13 GiB available; focus on CPU and per-service RSS deltas.
4. **Postgres footprint is large** (64 GB DB, ~1 GB backend RSS) but stable; not expected to change with market ingest refactor.
5. Re-run at a **similar market/trading load** (e.g. same time of day, active 15m + hourly windows) for a fair A/B.

---

## Raw audit reference

Automated re-run script: `scripts/prod/prod_cpu_ram_audit.sh`  
SSH wrapper: `scripts/prod/rec_prod_ssh.sh`  
Production host: `docs/PRODUCTION_HOST.md`
