# Agents

**Chat:** Use normal markdown (bold, headers, lists). Do not strip formatting.

**Autonomy / no interrogation (non-negotiable):** Execute simple operational and investigative prompts without questionnaires or multiple-choice “how should I proceed?” menus. Infer scope, choose sensible defaults, and return findings. Rare exceptions: true blockers, destructive/irreversible confirmation, real-money approval, or git actions that require an explicit instruction. See `.cursor/rules/01-core-operating-law.mdc`.

**NO FALLBACKS (non-negotiable):** Do **not** add code that substitutes guessed, cached, or second-best data when the authoritative source is missing — especially for persisted fields (`trades_*`, settlements, `market_result`, `win_loss_confirmed`, prices, fills). Missing data stays **NULL** or the operation **fails** until the real source delivers (WS, API poll, retry, scheduler). Fallbacks that write to the DB are **data corruption**, not resilience. Full rule: `.cursor/rules/00-no-fallbacks.mdc`.

**DB changes (non-negotiable):** Schema **evolution** (new/changed tables, columns, indexes, types) happens **only** through intentional migration pairs in `scripts/migrations/` applied with `python3 scripts/db/run_migration.py up <migration_id>` (or `up` for all pending). Do **not** add new `ALTER` / `ADD COLUMN` / type fixes to `init_database()` for production-shaped objects; that function is legacy **greenfield bootstrap** only. Full protocol when changing schema: (1) add the `.up.sql` / `.down.sql` pair, (2) run `run_migration.py up <migration_id>` on the developer DB so `system.schema_migrations` matches the repo, (3) update `docs/MASTER_DB_SCHEMA_REFERENCE.md`, (4) optionally align `init_database()` **CREATE TABLE** templates only if greenfield installs must match (no new repair DDL there — use migrations), (5) run `scripts/db/check_db_schema_drift.py`. **Plans and todos:** If the task includes a migration, step (2) must be done on **local** Postgres before migration-related work is considered complete (or say explicitly in chat that apply was skipped and why, e.g. no DB in this environment). Passing unit tests that mock SQL does **not** replace step (2). **Local-only DDL without a committed migration is invalid:** production deploy must replay the same `up` migration. See `docs/TENANT_INIT_AND_MIGRATIONS.md`.

**Schema drift while debugging (non-negotiable):** If Postgres errors or logs show **`UndefinedColumn`**, **`UndefinedTable`**, or any mismatch between code and catalog, **stop and treat it as a migration problem** before adding app-layer try/except or “hardening.” Search `scripts/migrations/` for an existing pending id; if none applies, **add a new migration pair**, run `python3 scripts/db/run_migration.py up <migration_id>` on the DB you are using (local when fixing local), and **state in the chat** which migration was missing, newly added, or applied. Do not end the task without telling the operator that a migration was required. Restarting services or editing `init_database()` does **not** substitute for applying migrations on existing databases.

**Migration hygiene (non-negotiable for agents):** One logical schema change → **one** migration id (pair of files), batched DDL when it belongs together. Search existing migrations before adding a new id. If a draft was never applied, delete superseded pairs in the same change. Do not delete pairs that are already applied on prod without explicit owner decision (breaks `down` / history). See `.cursor/rules/05-db-migration-hygiene.mdc`.

**Tenant schema DDL parity (non-negotiable):** Any structural change to per-tenant tables (patterns under `users` and `users_NNNN`, e.g. `monitor_list_*`, `trades_*`) must be applied to **every** relevant tenant schema in migrations and matching bootstrap code, not a single hardcoded slot. See `.cursor/rules/06-tenant-users-schema-parity.mdc`.

**Git command boundary (non-negotiable):** Agents must **never** run `git push`, `git pull`, or create git commits unless the user gives an explicit instruction for that specific action in the current chat. If not explicit, stop and ask first. Do not infer permission from deployment workflows or prior tasks.

**Production server:** Canonical SSH/DB host and paths are in `docs/PRODUCTION_HOST.md` (agents should use `REC_PROD_SSH_HOST` / `REC_PROD_DB_HOST`, not hardcoded IPs in new code). For non-interactive SSH, prefer `./scripts/prod/rec_prod_ssh.sh '…'` or `./scripts/prod/simple_git_pull_on_prod.sh` from repo root—do not use `REC_PROD_SSH_HOST=… ssh root@$REC_PROD_SSH_HOST '…'` on one line (bash expands the destination before the assignment; see `PRODUCTION_HOST.md`).

**Tenant vs system PostgreSQL (non-negotiable for new code):** Per-tenant data lives in schemas `users_NNNN`. Use `get_postgresql_connection()` (or explicit `tenant_user_no=` / worker `REC_USER_SCHEMA`) for any access to those tables. Global daemons that only touch shared schemas (`live_data`, `system`, etc.) must use `get_system_postgresql_connection()` or `SystemThreadedConnectionPool` — not tenant-wrapped connections. Do not add DML against `users_*` from global market-ingest processes; fan out via Redis and per-tenant workers (see `docs/TENANT_TOUCH_REGISTRY.md`). Operator scripts that mutate tenant tables must accept `--user-no` / document env defaults via `backend/core/tenant_script_args.py`.

**Lean `main_app` (standing preference):** `backend/main.py` is **wiring only** (ports, `FastAPI` factory, lifespan, middleware, `register_main_app_routers()`). Do **not** add handlers, SQL, or domain logic there. New or moved HTTP on the browser edge belongs in **`backend/web/routers/`** (see `register_main_app_routers.py` for attach order) or in a dedicated module those routers import—same pattern as `main_realtime.py`, `read_api_proxy.py`, `trade_actions.py`, etc. For **new or refactored read/aggregate HTTP** (dashboards, history, stats, lists), prefer **`read_api`** (`backend/read_api.py`, port `get_port('read_api')`) with existing tenant/session patterns—**not** new surface on `main_app` unless there is a concrete reason (e.g. must share process with a writer or WebSockets only colocated on `main`). Use **Redis** per `docs/REALTIME_BACKBONE.md` for **signals and small cached values**; do **not** treat Redis as the system of record for large entity graphs unless the owner specifies a cache/projection design. Shared cache-control for tenant JSON: `backend/web/response_cache_headers.py`. Logging setup: `backend/web/main_app_logging.py` (logger name `main_app` unchanged).

---

## Workflow agents (PM, Explorer, Builder, Reviewer)

| Agent | Role | Entrypoints |
|-------|------|-------------|
| **PM** | Thin orchestration. Interprets requests, delegates to Explorer/Builder/Reviewer, maintains plan lifecycle. Does not implement code or write plans itself; delegates. | Default when task coordination is needed; `/start-task`. |
| **Explorer** | Surface inspection and scoping. Produces findings and scope; may create or update a plan. No code edits. | `/inspect-surface`, task-planning skill. |
| **Builder** | Implements from a plan. Edits code/docs per plan steps; does not change rules or AGENTS.md unless part of an explicit knowledge-promotion. | `/implement-plan`, code-implementation skill. |
| **Reviewer** | Reviews changes (diff, tests, safety). Produces review outcome; may request rework. No direct edits to the change set. | `/review-change`, change-review skill. |

### Delegation rules

- **PM** delegates to Explorer for scoping and plan creation; to Builder for implementation; to Reviewer for review. PM does not perform Explorer/Builder/Reviewer work directly.
- **Explorer** hands off to Builder via a plan file (path and step pointer). Explorer does not implement.
- **Builder** works from a plan; on completion, may hand off to Reviewer or report to PM.
- **Reviewer** consumes plan + changed files; output is review result (pass / conditional pass / rework). No edits.

### Output schemas

- **Explorer:** `{ scope_summary, plan_path, steps[], completion_criteria, blockers[] }` — plan file at `.cursor/plans/<task>.md`.
- **Builder:** `{ plan_path, steps_done[], steps_remaining[], files_changed[], restart_required? }`.
- **Reviewer:** `{ outcome: pass | conditional_pass | rework, findings[], suggested_actions[] }`.

### Persistence policy

- **Plans:** One plan file per active task in `.cursor/plans/`. Plan is the single source of truth for that task; update in place. No rolling logs or append-only context files.
- **Rules and AGENTS.md:** Updated only when explicitly changing governance or agent definitions (e.g. knowledge promotion). Routine task execution does not modify them.
- **Ephemeral default:** Chat and task context are ephemeral unless a plan exists or knowledge promotion adds to docs/rules.

---

## Domain roster (delegate from PM when task fits)

| Agent | Role | Rule |
|-------|------|------|
| @db | DB operations, schema, migrations, reference. | .cursor/rules/db.mdc (or archive) |
| @analyst | Production trade/price analysis, **auto-trade backtests** (`docs/BACKTESTING.md`), **hypothetical fill pricing** (`docs/BACKTEST_PRICE_ESTIMATOR.md`), strategy diagnostics. | `docs/BACKTESTING.md`; `docs/BACKTEST_PRICE_ESTIMATOR.md`; legacy `docs/backtests/` if present. |
| @frontend | Frontend, HTML/JS/CSS, mobile, UI/UX. | .cursor/rules/frontend.mdc (or archive) |
| @updater | Changelog, prepare update, production checklist. | .cursor/rules/updater.mdc (or archive) |
| @kalshi | Kalshi API, WebSocket, broker. | .cursor/rules/kalshi.mdc (or archive) |
| @digitalocean | DO API, snapshots, backups, droplets. | .cursor/rules/digitalocean.mdc (or archive) |
| @assistant | Gmail, Calendar, personal productivity. No backend/DB/trading. | .cursor/rules/assistant.mdc (or archive) |

### Real-time backbone (scope and anti-bloat)

When touching redis_switchboard, stream_registry, or adding real-time streams/consumers: follow docs/REALTIME_BACKBONE.md Section 0 (scope and boundaries) and Section 9 (checklist). The switchboard carries signals only; do not add application HTTP APIs or per-stream logic there. New capability = new stream (registry + trigger) or new service, not new endpoints on the switchboard.

### Frontend/mobile parity convention

- When making **frontend changes** (desktop or mobile), always ask: **“Does this need a counterpart on the other surface?”**
  - If yes, either implement the corresponding change on the other surface in the same task/PR, or explicitly note why parity is not needed.
  - When in doubt, favor keeping **core flows and key views** (e.g. dashboards, account history, trade details) reasonably in sync between desktop and mobile.

**Commands (see .cursor/commands/ and .cursor/):** /verify-local, /verify-production, /system-restart-local, /system-restart-production, /prepare-update, /push-commits-and-update-production, /apply-update, /apply-update-from-local, /simple-pull, /confirm-update, /daily-briefing. Workflow: /start-task, /inspect-surface, /implement-plan, /review-change, /promote-knowledge.
