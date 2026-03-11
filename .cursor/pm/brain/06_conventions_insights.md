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
- **Must-track paths (stay on top):** These must be tracked so codebases stay identical across envs. When creating or editing files under them, verify .gitignore does not exclude them; if it does, add an exception in .gitignore before finishing. Paths: **Custom commands (all servers):** `.cursor/commands/`, `.cursor/skills/`, `.cursor/pm/` (all `*.md` and brain; exclude only local state like `*reviewed_drive*.json`), `.cursor/rules/`; **Codebase:** `scripts/migrations/*.sql`, `docs/changelog/`, project root config/docs (AGENTS.md, etc.). .gitignore excludes only .cursor secrets and local state (mcp.json, credentials, gdrive-auth-url.txt, *reviewed_drive*.json). After adding any new command/skill/pm/rule file, run `git status` and confirm it is tracked; if not, fix .gitignore.

## Agent context files and commits (mandatory)

We maintain a growing set of **agent context files** (rules, skills, brain docs, command docs, etc.). From the CEO’s perspective, the **Cursor “CHANGES” panel should show only real system changes** (code, config, schema), not day‑to‑day context tweaks. At the same time, context must be safely versioned and stay in sync across environments.

- **Context paths (owned by agents):** Treat the following as **agent context** rather than “system files”:  
  - `.cursor/pm/brain/` (all non-local-state docs, e.g. INDEX, 11_external_ecosystem, 13_proposed_tasks, 14_context_retention, 16_LOGGING_AUDIT_INITIATIVE, etc.).  
  - `.cursor/rules/` (agent rule .mdc files).  
  - `.cursor/skills/` (SKILL.md files).  
  - `.cursor/commands/` (command docs).  
  - Other clearly agent-only docs we explicitly designate later (e.g. additional memory docs under `.cursor/pm/`).
- **Single rolling context commit:** On `main`, keep **at most one local “context” commit** on top of the last pushed commit, e.g. `ctx: agent context updates`. When context files change:
  - Stage only the context paths.
  - Commit them into this single context commit, **amending that commit** as long as it has **not** been pushed and still only touches context paths.
  - This immediately removes context edits from the CHANGES panel so the CEO sees only system-file changes while we work.
- **No commit spam:** Do **not** create a new git commit for every small context edit. Use the single rolling `ctx:` commit and amend it until it is time to prepare a release. There should never be a long chain of tiny context commits between releases; **at any time there is at most one unpushed `ctx:` commit.**
- **Amend rules:** Never use `git commit --amend` on any commit that has already been pushed to a shared remote. The rolling `ctx:` commit may be amended **only while unpushed** and only when its diff is restricted to the context paths above.
- **Release behavior:** During `/prepare-update` and `/confirm-update`, it is acceptable for the release to include **one separate `ctx:` commit** alongside the system changes. We do not need a special branch for context; context is kept on `main`, but isolated to a single, clearly labelled commit so the timeline stays readable and the CHANGES panel is not cluttered with context edits.

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
- **docs/changelog/MASTER_CHANGELOG.md** — Add a **new dated entry** (e.g. `## YYYY-MM-DD — Title`) with **summary** and **Production checklist** when a release is ready to push. The changelog is the single place for "what to do on prod" for each update.

Do not state procedures or commitments in chat (e.g. "going forward I'll maintain both...") without writing them into memory or the relevant doc. Verbal commitments are not retained; only what is written here (or in 05, TODO, MASTER_CHANGELOG) will be followed in future sessions.

## DB changes: migrations vs direct DDL (mandatory)

**Do not add a ton of migration scripts for routine schema work.** Unless we're doing something **very special** (versioned, reversible schema that must run on every env and needs rollback), **do not create new migration files.** For normal adds and adjustments (columns, tables, indexes), use **direct DDL**: document the exact SQL or command in the MASTER_CHANGELOG Production checklist; apply-update runs it on prod via SSH. Or use `init_database()` / database.py if the change belongs in bootstrap. Migration files (`scripts/migrations/*.sql` + `run_migration.py`) clutter the repo and both servers and cause exactly the kind of headaches we avoid: use them only when we need versioned, reversible schema. **Default: simple schema change = checklist command or init_database, not a new migration script.**

## Update confirmation: DB verification non-negotiable (mandatory)

**Not a single update is ever confirmed unless DB updates are 100% confirmed.** We **never ever** skip this step. When an open changelog entry has any DB-related checklist item (e.g. "Apply migrations," "Update local database," "Run ... SQL"), we must **verify the DB state on the target server** (or run the step and then verify) before marking that item or the update complete. Do not mark checklist items done, do not report "all good," and do not consider the update confirmed if any DB step was skipped or left unverified. If migration files are missing from the commit but the schema is already present on prod, verify the schema on prod (e.g. information_schema) and only then mark the entry complete. If the schema is not present and the migration files are not in the repo, do not mark the entry complete; status is not "all good."

## One-time migration and backfill scripts (cleanup tracking)

We keep track of one-time migration and backfill scripts so they can eventually be archived or removed after they have been run everywhere they are needed. **Where we track:** (1) **MASTER_CHANGELOG.md** — each update that includes a one-time script has a checklist task (e.g. "Optional one-time backfill... run once"); (2) **docs/changelog/todo_docs/HOUSEKEEPING_SCRIPTS_INVENTORY.md** — classifies scripts as active, archived, or archive candidate; one-off migrations and backfills are marked there and many have already been moved to archive/2026-03-housekeeping/scripts/. **Practice:** When adding a new one-time script to a changelog entry, note it in the checklist and add or update its row in HOUSEKEEPING_SCRIPTS_INVENTORY with status (e.g. "Changelog; one-off backfill for account_history"). After the script has been run on all relevant envs and is no longer needed in the active path, mark it archived and move to the housekeeping archive so we eventually clean it up. **Prefer checklist-step commands over new scripts:** for simple one-off DB work, use a checklist item with the exact command or SQL instead of creating a new script file.

## Restart required (mandatory)

When you edit **critical scripts**—code that runs as a long-lived process (supervisor-managed services, main_app, trade_executor, kalshi_account_sync_ws, auto_entry_supervisor, watchdogs, etc.)—you **must call out in your summary** that a restart is required and which service(s). Example: "**Restart required:** kalshi_account_sync_ws, main_app (MASTER_RESTART or supervisorctl restart <program>)." Do not leave it implied; state it explicitly so the user knows changes will not be live until restart.

## Logging (mandatory for new and changed log calls)

All **new or changed** logging must follow the project logging standards so format, timestamps, errors, and heartbeats are consistent. Use the `logging` module (no `print()` for operational messages); one timestamp format (ISO 8601 + TZ, EST); one line format `{timestamp} {level} [{logger}] {message}`; errors with level + description + exception; consistent startup/restart/heartbeat phrasing. **Real-time visibility:** supervisor-captured logs must flush after each line. **Single destination:** no duplication — log only to stdout (supervisor captures it); no FileHandler or script-owned log files for supervised processes unless documented. (e.g. use a `StreamHandler` subclass that flushes in `emit()`, or `print(..., flush=True)` if still using print). Full details: `.cursor/pm/brain/16_LOGGING_AUDIT_INITIATIVE.md` §5 (including §5.8) and `docs/LOGGING_INVENTORY.md` (top). When adding or editing log calls, adhere to these rules unless an exception is documented.

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
- Multiple env conventions (DB_*, REC_DB_*, POSTGRES_*) across codebase; scripts that call database.py should normalize to DB_* via REC_DB_* mapping when loading .env. **Opportunistic cleanup:** When touching a file for other work, if it uses POSTGRES_* or its own DB config, switch it to get_postgresql_connection()/get_database_config() from backend.core.config.database. Flag for a full pass only if it becomes a bigger problem.
- MASTER_RESTART PORTS array is a subset of MASTER_PORT_MANIFEST; supervisor may start more processes; port_config.py is source of truth for get_port().
- Simulated trades duplicate prevention: is_strike_already_simulated_traded and trade_manager use same backend.core.config.database connection so duplicate check sees same rows (per changelog 2026-03-07).
