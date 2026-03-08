# Conventions and insights

## Autonomy (mandatory)

- **Execute to completion.** Do not pause for feedback, permission, or progress reports. Do the full workflow; report when done or when blocked.
- **Self-check before stopping.** Before you consider a task "done," ask: *Would Eric consider this actually complete, or am I stopping for the sake of stopping?* If the latter, keep going. Do not treat "I've done a reasonable amount" as done when the ask was exhaustive or full-scope.
- **No permission loops.** Do not ask "Should I do X?" or "Do you want me to proceed?" Do X. Only stop for a decision only the user can make, a hard blocker, or a destructive/irreversible action the user has not explicitly requested.
- This is non-negotiable and applies to every @pm task. Read this section when loading context.

## When you don't know the answer (mandatory)

If the user asks a question and you **don't know the answer:** do **not** guess, suggest they research it, or give a list of things that might work. **Research it yourself** (web search, docs, codebase, tools). If after that you still don't have an answer, say so plainly (e.g. "I couldn't find an answer"). The user strongly prefers being told we don't know over receiving guesses or "you could try X, Y, Z." No guessing. Apply to any question—product, tool, Cursor, API, company, etc.

## Top-level project rules (mandatory)

- **Server agnostic:** Everything must run identically locally and on any remote server; self-contained. No hardcoded hostnames, paths, or env-specific assumptions. Config from env, config files, or centralized config/port system. Same codebase runs anywhere. See .cursor/pm/PROJECT_RULES.md.
- **No fallbacks/defaults for required data:** Real trades, real money. If something needs a value and doesn't have it, that's a problem to fix—do not add fallback or default values just to avoid errors and let scripts run without needed data. Missing required data must surface as clear failure or explicit config requirement, not silent substitution. See .cursor/pm/PROJECT_RULES.md.
- **Git tracking:** New files necessary for operations or development (and passing operational security standards) should be tracked with git; track or ignore appropriately. **Agents must not push or pull through GitHub without explicit CEO authorization.** CEO determines when commits are warranted. See .cursor/pm/PROJECT_RULES.md §3.
- **Must-track paths (stay on top):** These must be tracked so codebases stay identical across envs. When creating or editing files under them, verify .gitignore does not exclude them; if it does, add an exception in .gitignore before finishing. Paths: `.cursor/commands/`, `.cursor/skills/`, `.cursor/pm/*.md` (command docs, not credentials), `scripts/migrations/*.sql`, `docs/changelog/`, project root config/docs (AGENTS.md, etc.). .gitignore currently has `*.sql` (global); we use `!scripts/migrations/` and `!scripts/migrations/*.sql` so migration files are tracked. After adding any new project file, run `git status` and confirm it appears; if not, fix .gitignore.

## Documentation organization

- **Agent command docs** (verify, system-restart, log-chat) live in **`.cursor/pm/`** only (e.g. VERIFY_COMMAND.md, SYSTEM_RESTART_COMMAND.md). Do not add or duplicate them in `docs/`. `docs/` is for project runbooks, changelog, and product/ops docs. See .cursor/pm/README.md.

## Naming

- **User/monitor IDs:** users schema tables suffix _0001 (user 0001). monitor_list_0001 id 10xxx (e.g. 10019). Per-monitor tables: active_trades_0001_10019, monitor_cycle_performance_0001_10019.
- **Symbols:** btc, eth, spx, ndx (lowercase in tables and port names).
- **Markets:** hourly vs 15m; strike tables strike_table_hourly_*, strike_table_15m_*; market_kalshi_hourly_*, market_kalshi_15m_*.
- **Ports:** Service names in MASTER_PORT_MANIFEST; get_port("main_app") etc. Monitor instances: monitor_instances.0001_10xxx.

## Changelog maintenance (mandatory)

When doing **production-relevant work**, maintain **both**:

- **docs/changelog/TODO.md** — Backlog and task checklists; update as work progresses (checkboxes, milestones, completion notes).
- **docs/changelog/MASTER_CHANGELOG.md** — Add a **new dated entry** (e.g. `## YYYY-MM-DD — Title`) with **summary** and **production agent checklist** when a release is ready to push. The changelog is the single place for "what to do on prod" for each update.

Do not state procedures or commitments in chat (e.g. "going forward I'll maintain both...") without writing them into memory or the relevant doc. Verbal commitments are not retained; only what is written here (or in 05, TODO, MASTER_CHANGELOG) will be followed in future sessions.

## Restart required (mandatory)

When you edit **critical scripts**—code that runs as a long-lived process (supervisor-managed services, main_app, trade_executor, kalshi_account_sync_ws, auto_entry_supervisor, watchdogs, etc.)—you **must call out in your summary** that a restart is required and which service(s). Example: "**Restart required:** kalshi_account_sync_ws, main_app (MASTER_RESTART or supervisorctl restart <program>)." Do not leave it implied; state it explicitly so the user knows changes will not be live until restart.

## Patterns

- **DB:** Single PostgreSQL DB rec_io_db; schemas users, live_data, historical_data, analytics, system, archive, core, work_progress, testing, public. Central connection via backend.core.config.database.
- **Trades:** Live in users.trades_0001; simulated in users.trades_simulated_0001 (same columns, nullable buy_price/position/fees/bankroll/price_spread/sell_price). Simulated 15m path: auto_entry_supervisor inserts, trade_manager closes at :00/:15/:30/:45 using live_price_log_1s_* for symbol_close.
- **Strike columns:** ttc_hourly, ttc_15m, probability_hourly, probability_15m (legacy ttc_seconds/probability removed from 15m tables).

## What not to touch (PM constraint)

- No edits to existing project files outside .cursor/pm/brain/.
- No DB/schema/table/column creation or migration in project code or DB; read-only for audit.
- .env and credentials paths are gitignored; do not add them to repo.

## Delegation and agent context (mandatory)

- **Delegate when the task fits.** PM should route work to the right agent: **@frontend** for UI/UX, HTML/JS/CSS, frontend layout; **@db** for schema, migrations, reference, DB alignment; **@updater** for changelog and deployment; **@kalshi** for Kalshi API, WebSocket, broker behavior; **@assistant** for personal productivity (email, calendar, tasks that don't need operational system resources). Do not do everything in PM when an expert agent exists and the task is in their domain.
- **Keep agent context updated.** When we add agents, change capabilities, or adopt new patterns, update persistent context: .cursor/rules/*.mdc, AGENTS.md, ORG_CHART.md, and relevant brain docs (e.g. 11 for Kalshi, 03 for DB). Accurate docs train agents; outdated context causes drift.
- **Single source of truth.** ORG_CHART and AGENTS.md are the roster; conventions and domain ownership live in 06 and in each agent’s rule. When in doubt, delegate and document.

## Subagents

- **@frontend** — Head of front-end development; HTML, JS, CSS, mobile, UI/UX. Owns frontend/ and user-facing behavior. .cursor/rules/frontend.mdc.
- **@updater** — Changelog/deployment: prepare update (pre-push), new update (run checklists). .cursor/rules/updater.mdc.
- **@kalshi** — Kalshi expert: company, news, markets, API, WebSocket. Owns our Kalshi integration (trade_executor, kalshi_account_sync_ws, etc.), fixed-point migration, and Kalshi accuracy in .cursor/pm/brain/11. .cursor/rules/kalshi.mdc.
- **@db** — Head of DB operations; PostgreSQL expert. Monitors all DB changes (any process); keeps reference doc, database.py, migrations, memory (03) in sync so DB changes are painless across servers. Schema, reversible migrations (scripts/db/run_migration.py), reference alignment. .cursor/rules/db.mdc.
- **@assistant** — Personal assistant: Gmail, Google Calendar, scheduling, and other personal productivity; no rec.io operational resources (backend, DB, trading, deployment). .cursor/rules/assistant.mdc.
- **@pm** — This agent; strategy, audits, agent/rules maintenance, system coordination. .cursor/rules/pm.mdc. Autonomy: execute full workflows; only pause for user-only decisions, blockers, or destructive/irreversible actions.
- Future subagents: create in .cursor/rules/*.mdc and register in AGENTS.md.

## Research / deep-dive completeness

When directed to do a **deep dive** or **learn everything** about a company, platform, or external entity: do not limit the research to technical docs and APIs. Capture **baseline facts first** — who runs it (CEO, key leadership), what it is in one sentence, structure, key links — then add technical detail. If we skip the easiest, most visible facts (e.g. who is CEO), the dive was not thorough. Apply this to any "become an expert on X" or "learn everything about X" task.

## Insights (from audit)

- main.py has some hardcoded localhost/rec_io_user/rec_io_password in get_trade_history_preferences_postgresql; rest of app uses env or unified config.
- Multiple env conventions (DB_*, REC_DB_*, POSTGRES_*) across codebase; scripts that call database.py should normalize to DB_* via REC_DB_* mapping when loading .env.
- MASTER_RESTART PORTS array is a subset of MASTER_PORT_MANIFEST; supervisor may start more processes; port_config.py is source of truth for get_port().
- Simulated trades duplicate prevention: is_strike_already_simulated_traded and trade_manager use same backend.core.config.database connection so duplicate check sees same rows (per changelog 2026-03-07).
