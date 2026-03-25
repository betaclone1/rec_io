# Unified 15m data plane + consolidated 15m supervisors

## Scope (explicit)

### Data plane (15m only)

- Monitors with **`monitor_list.market = '15m'`** only: read from unified tables `live_data.strike_table_15m`, `live_data.market_kalshi_15m` with **strict** `WHERE` on **`exchange`** (execution venue; rename from legacy `broker` in DDL/code as part of this effort) **and** `symbol`, **deterministic latest row** (`ORDER BY timestamp` / `updated_at`), and **post-fetch checks** (header `symbol` matches the monitor in context).
- **`market = 'hourly'`:** unchanged **data plane** — keep per-symbol tables (`strike_table_hourly_{symbol}`, `market_kalshi_hourly_{symbol}`), existing query shapes.

### Process model (15m only) — **refactor goal**

- **One** `auto_entry_supervisor` process (15m pool) that, each tick, **iterates all monitors** with `market = '15m'` (and `auto_trade` / eligibility rules as today), using **per-monitor context** (symbol, settings, cooldowns, state) so behavior stays isolated.
- **One** `active_trade_supervisor` process (15m pool) that **iterates all 15m monitors** and runs auto-stop / monitoring logic **per monitor**, again with explicit `monitor_id` (and user number) everywhere.
- **Hourly monitors — intentionally untouched for this initiative:** keep **one AES + one ATS per hourly monitor**, same scripts, ports, and logic. **Do not** fold hourlies into the global 15m processes.
  - **Reason:** Hourly is a **different animal**: each hourly monitor is oriented around **many strikes** (full chain / watchlist-style behavior). 15m, by product definition here, is **one strike per monitor/cycle**, so iterating many 15m monitors in one process is simpler and lower risk. Consolidating hourly would need its own design pass (state, bracket rules, multi-strike scans) and is **explicitly deferred**.

## Active trades storage

- **Still no single merged `active_trades` table required.** Each 15m monitor keeps **`users.active_trades_{user_number}_{monitor_id}`**. The **single 15m ATS** loop selects the correct table name from the current `monitor_id` in context (same table layout as today, one process that fans out in software).
- Rationale: proven schema, UI can stay monitor-scoped; only **process count and routing** change for 15m.

## Routing and ops (must design in implementation)

- **Supervisor / spawner:** define program names (e.g. `auto_entry_supervisor_15m`, `active_trade_supervisor_15m`) and **remove** per-monitor 15m AES/ATS program entries; keep per-monitor entries **only** for hourly monitors.
- **Ports:** move from `get_monitor_port("auto_entry_supervisor", monitor_suffix)` for 15m to **fixed ports** for the two global processes; update [`backend/core/port_config.py`](backend/core/port_config.py), monitor_manager / unified supervisor config, and any main-app or frontend URLs that hit per-monitor 15m supervisor ports.
- **HTTP APIs:** 15m AES/ATS Flask routes must accept **`monitor_id`** (path or query) wherever state is monitor-specific (indicator, health, manual triggers); no reliance on `MONITOR_IDENTIFIER` from argv for 15m global process.
- **Redis ATS enrollment ([`ats_enrollment_redis.py`](backend/core/ats_enrollment_redis.py)):** publisher already carries `monitor_suffix`; the **single 15m ATS** subscribes once and **dispatches** enrollment to the correct in-memory / DB context for that monitor (or equivalent). Verify no assumption that one Redis subscriber == one monitor process.
- **trade_manager / notifications:** confirm HTTP fallback URLs for ATS use the **15m global** port with monitor routing if needed.

## Naming: `broker` → `exchange` (system-wide)

- **Policy:** Anywhere the codebase or schema used **`broker`** to mean execution venue, use **`exchange`** instead (columns, JSON keys, SQL `WHERE` clauses, comments, watchdog/generator configs). This aligns with the trades-layer exchange plan and avoids two competing terms.
- **Migrations:** rename `broker` → `exchange` on affected tables (e.g. unified `strike_table_15m`, `market_kalshi_15m` if present, plus any other venue-key columns uncovered in inventory). Follow normal migration hygiene (one logical change per id where practical).

## Dev server testing (rollout)

- **Validate on the dev server first:** deploy unified 15m AES/ATS scripts, wire them into the **supervisor stack**, and **stop/disable the old per-monitor 15m supervisor programs** (the individual `auto_entry_supervisor_*` / `active_trade_supervisor_*` entries for **15m-only** monitors) so only the global pair owns 15m during the test window.
- Leave **hourly** per-monitor supervisor entries running unchanged.
- After confidence, mirror the same supervisor config pattern toward production (separate cutover step).

## Components

| Component | 15m | Hourly (default) |
|-----------|-----|------------------|
| AES / ATS **process count** | **1 + 1** global | **1 + 1 per monitor** |
| Strike / snapshot **reads** | Unified `strike_table_15m`, `market_kalshi_15m` + filters | Per-symbol tables, current queries |
| `active_trades` | Per-monitor table; global ATS **iterates** | Per-monitor table; per-monitor ATS |

## Related work

- **Exchange rename on trades** ([exchange plan](/Users/ericwais1/.cursor/plans/auto-trade_broker_metadata_c724589f.plan.md)): orthogonal; can land in same PR with care.
- **[`auto-entry-supervisor-consolidation.md`](.cursor/plans/auto-entry-supervisor-consolidation.md):** same spirit (single loop, per-monitor state); this 15m plan **narrows scope to 15m + unified live_data** and adds **matching ATS consolidation**.

## Completion criteria

- [ ] Unified 15m SQL: symbol + venue + ordering; no cross-symbol bleed under multi-monitor load.
- [ ] Exactly **one** 15m AES and **one** 15m ATS in production config; no duplicate 15m supervisor rows per monitor.
- [ ] Hourly supervisors unchanged in behavior and deployment (per-monitor).
- [ ] All 15m auto-entry and auto-stop paths keyed by explicit `monitor_id` (and user) in the global processes; staging with multiple 15m monitors shows correct isolation.

## Todos

- Supervisor inventory: [`monitor_manager`](backend/monitor_manager.py), spawner, unified config generation — 15m global vs hourly per-monitor.
- Port and HTTP contract: `port_config`, main/frontend call sites for 15m AES/ATS.
- Refactor 15m AES: unified live_data reads + **multi-monitor loop** + per-monitor state (replace global `MONITOR_ID` assumptions on 15m code paths).
- Refactor 15m ATS: unified live_data reads + **multi-monitor loop** + per-table `active_trades_*` access + Redis enroll dispatch.
- Refactor `main.py` 15m strike/API paths as needed.
- Optional: feature flag to run old per-monitor 15m vs new global pair during cutover.
- Migration / code grep: `broker` → `exchange` for venue semantics across `live_data`, supervisors, and related scripts.
