# Production CPU optimization plan

**Status:** active  
**Last audit:** 2026-09-04T21:13:17Z (post Phase 1; idle ~28%, load 1m ~9–11)  
**Deployed:** `03aee7b` — CPU OPTIMIZATION - PHASE 1

## Product priority (non-negotiable)

**TOP PRIORITY — not close:** **BTC 15m High Water Scalp** (and the 15m ladder / AES / ATS / TM path that feeds it).

**Hourlies are an afterthought.** Do not trade 15m HWS freshness, isolation, or fail-closed behavior for hourly CPU/RAM wins.

Implications for later phases:
- **Do not merge STG (B4)** if it couples hourly failure/starvation into the 15m process — prefer keeping `strike_table_generator_ws_15m` isolated; starve or slow *hourly* first if reclaiming CPU.
- **B1 shared prob lookup:** 15m consumers must fail closed on missing/stale cache; never let hourly preload races delay BTC 15m.
- **Phase 3:** if splitting droplets, protect **15m ingest + trading** first; hourly can ride degraded or stay on a crowded host longer.
- **Phase 1 B2** (`STRIKE_REGEN_MIN_INTERVAL_SEC=1.0`) applies to both gens — if 15m HWS needs tighter regen, override **15m only** via env / process-specific setting rather than rolling back host-wide for hourlies.

## Current host picture

| Metric | Value |
|--------|-------|
| Host | `rec-io-server-new-york-1` 8 vCPU / 16 GiB |
| Load | **16.7 / 16.7 / 17.5** |
| Idle (mpstat 15s) | **~2.3%** |
| Python `/opt/rec_io_server` | **~416–422% CPU**, **~8.3 GB RSS**, 20–22 procs |
| Postgres (all procs) | **~26% CPU sum**, **~1.25 GB RSS**, DB **~5.1 GB** |
| Redis | **~15% CPU**, ~52 MB RSS |
| Active monitors | **15** (was 22 on Sep 1) |

### Top CPU (lifetime % at audit)

| Program | CPU % | RSS |
|---------|-------|-----|
| `auto_entry_supervisor` unified | **93.8** | 94 MB |
| `strike_table_generator_ws` hourly | **72.7** | 1.63 GB |
| `market_watchdog_ws_kalshi` | **71.9** | 236 MB |
| `strike_table_generator_ws` 15m | **61.9** | 1.63 GB |
| `redis_switchboard` | **35.6** | 64 MB |
| `active_trade_supervisor` unified | **26.5** | 1.70 GB |
| `auto_entry` btc15m_exp_scalp | **13.5** | 86 MB |
| `main_app` | **14.3** | 125 MB |
| postgres (postmaster + backends) | **~15–26 sum** | ~1.25 GB |

**Tier share (approx of Python stack):** trading supervisors ~34% · market data pipeline ~50% · switchboard ~9% · app/API ~7%.

### Trajectory

| | Sep 1 audit | **Sep 4 (today)** |
|--|-------------|-------------------|
| Load 1m | ~21 | **~17** |
| AES unified | 93% | **94%** |
| Strike gens (sum) | ~117% | **~135%** |
| MW | 58% | **72%** |
| Switchboard | 33% | **36%** |
| ATS unified | 54% | **27%** |
| Python RSS | ~8.1 GB | **~8.3 GB** |
| Active monitors | 22 | **15** |

Slightly better load; same structural pin. ATS quieter; MW + strike gens hotter.

## Ranking principle

Prefer work that does **not** change fire/entry semantics. Treat Exp Scalp fire-path changes as product decisions, not perf knobs.

---

## Phase 1 — Safe code / config (local first; deploy only when ordered)

**Status: implemented in tree (not deployed).** Restart after deploy: `active_trade_supervisor`, `auto_entry_supervisor`, `strike_table_generator_ws` (hourly + 15m).

| ID | Change | Est. save | Trading risk | Done |
|----|--------|-----------|--------------|------|
| **A5** | ATS live_state wake-only (no inline mark refresh); Redis MONITORING log throttle | 10–25% of ATS | Low | Yes |
| **A2** | `AES_LANE_PARALLELISM` / `ATS_LANE_PARALLELISM` default **12** | 10–20% of AES | Low–med | Yes |
| **A4** | Throttle `cooldown_timer` display writes ≥1s; gates use `cooldown_start_time` | 10–20% switchboard + PG | Low | Yes |
| **B2** | `STRIKE_REGEN_MIN_INTERVAL_SEC` default **1.0** | 15–25% of strike gens | Med | Yes |
| **B3** | Coalesce identical `strike_pipeline_health` upserts (5s; no NOTIFY on table) | PG write storm | Low–med | Yes |

**Hold:** **A1** stale-gen fire backoff / `AES_REFUSE_STALE_FIRE`.

**Realistic Phase 1 outcome:** load 17 → maybe **11–14** if A5+A2+A4+B2 all land. Still tight on 8 cores.

**Env overrides (reversible):** `AES_LANE_PARALLELISM`, `ATS_LANE_PARALLELISM`, `AES_COOLDOWN_TIMER_WRITE_MIN_SEC`, `STRIKE_REGEN_MIN_INTERVAL_SEC`, `STRIKE_PIPELINE_HEALTH_UPSERT_MIN_INTERVAL_SEC`.

---

## Phase 2 — Memory / structure

**Status: implemented in tree (not deployed).** B4 deferred. Restart after deploy: both `strike_table_generator_ws_*`, both `active_trade_supervisor_*` (mmap attach / rebuild). Prefer restart **15m STG first**, then ATS, then hourly.

| ID | Change | Benefit | Status |
|----|--------|---------|--------|
| **B1** | Shared probability lookup via numpy **mmap** (`var/prob_lookup_mmap/`, `PROB_LOOKUP_SHARED_MMAP=1` default) | One physical copy per symbol; BTC preload first; hourly STG skips startup preload by default (`STRIKE_HOURLY_SKIP_PROB_PRELOAD=1`) | **Done** |
| **B4** / merge strike gens | One STG process | — | **Deferred / avoid** (HWS blast radius) |

**Monitor (programmatic):** `scripts/diagnostics/monitor_phase2_trading_health.py`

```bash
# one-shot (exit 0/1/2 = ok/warn/critical)
cd /opt/rec_io_server && PYTHONPATH=. venv/bin/python \
  scripts/diagnostics/monitor_phase2_trading_health.py --once --user-no 0001

# continuous after Phase 2 deploy
nohup venv/bin/python scripts/diagnostics/monitor_phase2_trading_health.py \
  --hours 24 --interval 60 --log logs/phase2_trading_health.log \
  > logs/phase2_trading_health.nohup.out 2>&1 &
```

Watches: BTC 15m `strike_pipeline_health`, High Water* BTC 15m monitors, active/touched trades, mmap files, MemAvailable + STG/ATS **PSS** (RSS overcounts shared mmap).

**Env:** `PROB_LOOKUP_SHARED_MMAP`, `PROB_LOOKUP_MMAP_DIR`, `STRIKE_HOURLY_SKIP_PROB_PRELOAD`, `PROBABILITY_LOOKUP_RAM`, `PROB_LOOKUP_USE_INDEX` (default on; `0` = full scan).

**Note:** `ps` RSS may still look large per process; judge RAM win by `MemAvailable` and `pss_stg_ats_mb` in the monitor.

### Phase 2.1 — Indexed neighbor lookup (local first)

**Status: local only (not on prod).** Same filters/interp as full scan; `(mom, round(ttc))` index into mmap rows. Tie-break `(dist, ttc, buf)` for deterministic neighbors.

- Code: `backend/core/probability_lookup_cache.py`
- Tests: `tests/unit/test_probability_lookup_index_parity.py` (incl. BTC table golden sample)
- Rollback: `PROB_LOOKUP_USE_INDEX=0`
- Prod: only after local observe; restart STG then ATS


---

## Phase 3 — Splinter droplets

Cannot in-place add cores on current droplet.

### 3A — Postgres on a secondary droplet (sizing)

**What moves:** entire PostgreSQL 14 instance (`rec_io_db` + all roles). App keeps using `REC_DB_HOST` / `DB_HOST` (already remote-shaped). `redis_switchboard` LISTEN stays on app host but connects to remote PG.

**Direct CPU freed on main host (measured today):**

| Component | Approx |
|-----------|--------|
| All `postgres` processes CPU sum | **~20–30% of one core** (~**0.25–0.4 of 8 cores**, i.e. **~3–5% of total host capacity**) |
| Postgres RSS / cache pressure | **~1.2 GB** process RSS (+ OS page cache for DB files today) |

**Honest ceiling:** PG-only move is a **small** main-host CPU win. The pin is Python (AES / MW / STG / switchboard), not Postgres. Expect load **16–17 → maybe 15–16** from PG move alone, unless second-order lock contention drops more (possible but not guaranteed).

**Second-order (possible, unquantified):**
- Fewer `monitor_list` / WAL lock waits amplifying AES/ATS
- Cycle OB archive PG writer no longer competing for local disk/CPU with hot path
- Switchboard still burns **~35%** on the **app** host (NOTIFY fanout stays there)

**What does *not* move with PG:** AES, MW, strike gens, switchboard Python CPU, Redis.

**Secondary droplet size recommendation:**

| Spec | Why |
|------|-----|
| **Minimum** | **2 vCPU / 4–8 GB RAM / 80+ GB SSD** — DB is 5.1 GB; current PG CPU peak is sub-1 core |
| **Recommended** | **4 vCPU / 8 GB RAM / 100+ GB SSD** — headroom for vacuum, nightly dump, parallel queries, growth, connection storms |
| **Managed alternative** | DO Managed Postgres NYC same region — similar vCPU class; less ops |

Do **not** undersize to 1 vCPU: backups + autovacuum + write bursts (OB delta archive, `monitor_list`) will stall.

**Network:** same DO NYC region / VPC. Expect +0.3–2 ms RTT vs localhost. Hot path trading reads should stay on Redis `live_state`; PG latency mainly hits writes, LISTEN, and cold reads.

**Risk:** migration cutover (dump/restore or streaming replica promote); `pg_hba` + private networking; update all `REC_DB_*` / cron / backup scripts; LISTEN/NOTIFY over TCP must stay reliable for switchboard.

### 3B — After PG (bigger wins)

| Droplet | Moves | Est. CPU off main |
|---------|-------|-------------------|
| **Ingest** | MW + strike gens + CFB + snapshot publisher | **~200–220%** (~2.0–2.5 cores) |
| **Trading** | AES/ATS/TM/TE/monitor_manager | **~140%** |
| **Edge** (optional) | main_app / read_api / nginx | **~20%** |

Constraint: trading ↔ Redis same AZ.

---

## Implementation order (default)

1. Phase 1: A5 → A2 → A4 → measure → B2 trial  
2. Phase 2 memory if RSS still crushing  
3. Phase 3A PG droplet if wanting isolation / unlock for ingest split (**not** as primary CPU fix)  
4. Phase 3B ingest droplet for real headroom  

## Explicit non-goals

- `AES_REFUSE_STALE_FIRE` without product sign-off  
- Prod deploy/mutate without explicit instruction  
- Fallbacks that write substitute market/trade data  

## Related

- Raw audit: re-run `./scripts/prod/prod_cpu_ram_audit.sh`  
- OB overnight: `/opt/rec_io_server/logs/ob_hotpath_gaps.log`  
- `docs/UNIFIED_AES_TICK_CONTRACT.md`, `docs/perf-audits/*`
