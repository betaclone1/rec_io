# Conventions and insights

## Autonomy (mandatory)

- **Execute to completion.** Do not pause for feedback, permission, or progress reports. Do the full workflow; report when done or when blocked.
- **Self-check before stopping.** Before you consider a task "done," ask: *Would Eric consider this actually complete, or am I stopping for the sake of stopping?* If the latter, keep going. Do not treat "I've done a reasonable amount" as done when the ask was exhaustive or full-scope.
- **No permission loops.** Do not ask "Should I do X?" or "Do you want me to proceed?" Do X. Only stop for a decision only the user can make, a hard blocker, or a destructive/irreversible action the user has not explicitly requested.
- This is non-negotiable and applies to every @pm task. Read this section when loading the brain.

## When you don't know the answer (mandatory)

If the user asks a question and you **don't know the answer:** do **not** guess, suggest they research it, or give a list of things that might work. **Research it yourself** (web search, docs, codebase, tools). If after that you still don't have an answer, say so plainly (e.g. "I couldn't find an answer"). The user strongly prefers being told we don't know over receiving guesses or "you could try X, Y, Z." No guessing. Apply to any question—product, tool, Cursor, API, company, etc.

## Naming

- **User/monitor IDs:** users schema tables suffix _0001 (user 0001). monitor_list_0001 id 10xxx (e.g. 10019). Per-monitor tables: active_trades_0001_10019, monitor_cycle_performance_0001_10019.
- **Symbols:** btc, eth, spx, ndx (lowercase in tables and port names).
- **Markets:** hourly vs 15m; strike tables strike_table_hourly_*, strike_table_15m_*; market_kalshi_hourly_*, market_kalshi_15m_*.
- **Ports:** Service names in MASTER_PORT_MANIFEST; get_port("main_app") etc. Monitor instances: monitor_instances.0001_10xxx.

## Patterns

- **DB:** Single PostgreSQL DB rec_io_db; schemas users, live_data, historical_data, analytics, system, archive, core, work_progress, testing, public. Central connection via backend.core.config.database.
- **Trades:** Live in users.trades_0001; simulated in users.trades_simulated_0001 (same columns, nullable buy_price/position/fees/bankroll/price_spread/sell_price). Simulated 15m path: auto_entry_supervisor inserts, trade_manager closes at :00/:15/:30/:45 using live_price_log_1s_* for symbol_close.
- **Strike columns:** ttc_hourly, ttc_15m, probability_hourly, probability_15m (legacy ttc_seconds/probability removed from 15m tables).

## What not to touch (PM constraint)

- No edits to existing project files outside docs/pm_brain/.
- No DB/schema/table/column creation or migration in project code or DB; read-only for audit.
- .env and credentials paths are gitignored; do not add them to repo.

## Subagents

- **@updater** — Changelog/deployment: prepare update (pre-push), new update (run checklists). .cursor/rules/updater.mdc.
- **@kalshi** — Kalshi expert: company, news, markets, API, WebSocket. Owns our Kalshi integration (trade_executor, kalshi_account_sync_ws, etc.), fixed-point migration, and Kalshi accuracy in docs/pm_brain/11. .cursor/rules/kalshi.mdc.
- **@pm** — This agent; strategy, audits, agent/rules maintenance, system coordination. .cursor/rules/pm.mdc. Autonomy: execute full workflows; only pause for user-only decisions, blockers, or destructive/irreversible actions.
- Future subagents: create in .cursor/rules/*.mdc and register in AGENTS.md.

## Research / deep-dive completeness

When directed to do a **deep dive** or **learn everything** about a company, platform, or external entity: do not limit the research to technical docs and APIs. Capture **baseline facts first** — who runs it (CEO, key leadership), what it is in one sentence, structure, key links — then add technical detail. If we skip the easiest, most visible facts (e.g. who is CEO), the dive was not thorough. Apply this to any "become an expert on X" or "learn everything about X" task.

## Insights (from audit)

- main.py has some hardcoded localhost/rec_io_user/rec_io_password in get_trade_history_preferences_postgresql; rest of app uses env or unified config.
- Multiple env conventions (DB_*, REC_DB_*, POSTGRES_*) across codebase; scripts that call database.py should normalize to DB_* via REC_DB_* mapping when loading .env.
- MASTER_RESTART PORTS array is a subset of MASTER_PORT_MANIFEST; supervisor may start more processes; port_config.py is source of truth for get_port().
- Simulated trades duplicate prevention: is_strike_already_simulated_traded and trade_manager use same backend.core.config.database connection so duplicate check sees same rows (per changelog 2026-03-07).
