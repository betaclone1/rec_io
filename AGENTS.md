# Agents

**Chat:** Use normal markdown (bold, headers, lists). Do not strip formatting.

**DB changes (non-negotiable):** When the user asks to add or modify anything in the database (column, table, schema, etc.), do the full protocol: (1) create migration up/down in `scripts/migrations/`, (2) run `python3 scripts/db/run_migration.py up <migration_id>`, (3) update `docs/MASTER_DB_SCHEMA_REFERENCE.md`, (4) update `backend/core/config/database.py` and schema brain, (5) run `scripts/db/check_db_schema_drift.py`. No DB change is done until the migration has been applied.

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
| @frontend | Frontend, HTML/JS/CSS, mobile, UI/UX. | .cursor/rules/frontend.mdc (or archive) |
| @analyst | Trades logs, historical/live data, analytics pipelines; tradebook; strategy description, optimization, and design. Expert on crypto market movements and Kalshi-style prediction market mechanics. | .cursor/rules/analyst.mdc |
| @updater | Changelog, prepare update, production checklist. | .cursor/rules/updater.mdc (or archive) |
| @kalshi | Kalshi API, WebSocket, broker. | .cursor/rules/kalshi.mdc (or archive) |
| @digitalocean | DO API, snapshots, backups, droplets. | .cursor/rules/digitalocean.mdc (or archive) |
| @assistant | Gmail, Calendar, personal productivity. No backend/DB/trading. | .cursor/rules/assistant.mdc (or archive) |

### Frontend/mobile parity convention

- When making **frontend changes** (desktop or mobile), always ask: **“Does this need a counterpart on the other surface?”**
  - If yes, either implement the corresponding change on the other surface in the same task/PR, or explicitly note why parity is not needed.
  - When in doubt, favor keeping **core flows and key views** (e.g. dashboards, account history, trade details) reasonably in sync between desktop and mobile.

**Commands (see .cursor/commands/ and .cursor/pm/):** /verify-local, /verify-production, /system-restart, /prepare-update, /apply-update, /apply-update-from-local, /confirm-update, /daily-briefing. Workflow: /start-task, /inspect-surface, /implement-plan, /review-change, /promote-knowledge.
