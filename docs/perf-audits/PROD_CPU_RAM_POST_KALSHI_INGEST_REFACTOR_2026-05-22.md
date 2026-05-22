# Production CPU & RAM — post Kalshi ingest refactor (v3.7.0)

**Compare to:** [PROD_CPU_RAM_BASELINE_PRE_KALSHI_INGEST_REFACTOR_2026-05-22.md](./PROD_CPU_RAM_BASELINE_PRE_KALSHI_INGEST_REFACTOR_2026-05-22.md)

| Field | Value |
|-------|--------|
| **Captured (UTC)** | 2026-05-22T21:26:49Z |
| **Host** | `rec-io-server-new-york-1` (`165.22.13.146`) |
| **Uptime** | 51 days |
| **Deployed commit** | `82afb9c` — Release v3.7.0 (unified Kalshi live_state ingest) |
| **Supervisor uptime** | ~5 min most programs; `market_watchdog_ws_kalshi` ~17 min (post-deploy restart + LIVE_STATE fix) |

**Raw audit:** [prod_audit_POST_20260522T212649Z.txt](./prod_audit_POST_20260522T212649Z.txt)

---

## Headline comparison (refactor-sensitive)

| Metric | Pre-deploy | Post-deploy | Delta | Notes |
|--------|------------|-------------|-------|-------|
| `market_watchdog_ws` supervised count | **2** (`_15m` + `_hourly`) | **1** (`--market all`) | −1 process | Primary refactor goal |
| `market_watchdog_ws` RSS (supervisor) | **188.6 MB** | **83.0 MB** | **−105.6 MB (−56%)** | Single process |
| `market_watchdog_ws` CPU (instant) | **76.1%** | **54.0%** | **−22.1 pts** | One WS ingest vs two |
| `symbol_price_watchdog` RSS | **232.7 MB** | **267.7 MB** | +35 MB | Now writing live_state (was skipped pre-fix) |
| `symbol_price_watchdog` CPU | **25.0%** | **68.9%** | +43.9 pts | Hot-path Redis + tick work restored |
| `strike_table_generator_ws` RSS | **65.3 MB** | **80.1 MB** | +14.8 MB | Generating ladders (was failing) |
| `strike_table_generator_ws` CPU | **16.8%** | **66.5%** | +49.7 pts | Active regen vs idle errors |
| Python `/opt/rec_io_server` RSS | **1307.4 MB** | **1225.4 MB** | **−82 MB** | Net down despite busier pipeline |
| Python process count | **23** | **22** | −1 | One fewer watchdog |
| Load avg (1m / 5m / 15m) | **8.87 / 7.63 / 7.52** | **10.03 / 8.70 / 7.61** | +1.16 / +1.07 / +0.09 | See caveats below |
| Redis `used_memory_human` | **28.39M** | **28.52M** | +0.13M | Stable |
| Redis `DBSIZE` | **174** | **434** | +260 keys | live_state symbol + strike_ladder keys |
| Postgres `rec_io` backend RSS | **1025.5 MB** (12) | **175.7 MB** (8) | N/A | Post snapshot ~5 min after restart; not comparable |

---

## System summary

| Resource | Pre | Post |
|----------|-----|------|
| **vCPUs** | 8 | 8 |
| **RAM available** | ~13.7 GiB | ~13.9 GiB (`MemAvailable` 14,592,364 kB) |
| **Load (1m)** | 8.87 | 10.03 |
| **Disk /** | 80G / 26% | 80G / 26% |
| **vmstat idle** | often 1–2% | ~5–10% (3s sample) |

Host remains **CPU-bound** on 8 cores; 1m load slightly higher immediately after pipeline recovery.

---

## Architecture change (confirmed)

| Pre | Post |
|-----|------|
| `market_watchdog_ws_kalshi_15m` + `market_watchdog_ws_kalshi_hourly` | `market_watchdog_ws_kalshi` (`--exchange kalshi --market all`) |
| Dual WS connections, ~189 MB RSS, ~76% CPU | Single process, **83 MB RSS**, **54% CPU** |

---

## Supervisor snapshot (post)

20 programs RUNNING. Top RSS / CPU:

| Program | RSS (MB) | CPU % | Uptime at audit |
|---------|----------|-------|-----------------|
| market_watchdog_ws_kalshi | 83.0 | 54.0 | 17m |
| main_app | 92.1 | 21.2 | 5m |
| auto_entry_supervisor_0001 | 80.8 | 26.7 | 5m |
| symbol_price_watchdog_btc | 66.8 | 23.2 | 5m |
| redis_switchboard | 58.0 | **61.2** | 5m |
| strike_table_generator_ws_15m | 38.5 | 33.3 | 5m |
| strike_table_generator_ws_hourly | 38.6 | 33.3 | 5m |

**New top CPU:** `redis_switchboard` (61%) — likely burst fanout after live_state recovery; re-check after 24h steady state.

---

## Interpretation

### Wins (refactor intent)

1. **Unified market watchdog:** ~56% less RSS and ~29% less instantaneous CPU vs dual processes, with one supervised program.
2. **Net Python RSS** down ~82 MB despite a **working** symbol + strike pipeline (pre-deploy strike gen was error-looping without `LIVE_STATE_CACHE_ENABLED` on those programs).

### Expected increases (healthy pipeline)

- **Symbol watchdog CPU/RSS** rose because ticks now publish to Redis (`LIVE_STATE_CACHE_ENABLED` on all pipeline services after hotfix).
- **Strike generator CPU** rose because tables are regenerating (was `LIVE_STATE_CACHE_ENABLED is required` before env fix).

### Not apples-to-apples

- Pre baseline: **4+ day** process uptime, steady-state.
- Post snapshot: **~5–17 minutes** after deploy + supervisord regen; load and `redis_switchboard` CPU may reflect catch-up, not steady-state.
- Postgres backend RSS sample is **not** comparable (fewer warm connections right after restart).

### Recommended follow-up

Re-run the same audit **24h later** at a similar market window (active 15m + hourly) for steady-state comparison:

```bash
./scripts/prod/prod_cpu_ram_audit.sh | tee docs/perf-audits/prod_audit_STEADY_$(date -u +%Y%m%dT%H%M%SZ).txt
```

---

## Re-run command

```bash
chmod +x scripts/prod/prod_cpu_ram_audit.sh
./scripts/prod/prod_cpu_ram_audit.sh | tee docs/perf-audits/prod_audit_POST_$(date -u +%Y%m%dT%H%M%SZ).txt
```
