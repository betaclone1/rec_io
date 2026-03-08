# Agent instructions

Project-specific agents are in `.cursor/rules/`.

**Org chart & standards:** [.cursor/pm/ORG_CHART.md](.cursor/pm/ORG_CHART.md) — CEO/PM, departments (Technical, Analysis, Operations, Integrations), governance (real money → CEO; task flow through PM).

**/verify** — After MASTER_RESTART: verify newest changes and system health. PM runs the checks and reports. See [.cursor/pm/VERIFY_COMMAND.md](.cursor/pm/VERIFY_COMMAND.md).

**/system-restart** — Run MASTER_RESTART, wait for completion, then run the full verify workflow. See [.cursor/pm/SYSTEM_RESTART_COMMAND.md](.cursor/pm/SYSTEM_RESTART_COMMAND.md).

**/log-chat** — User's tool to request a chat summary: append a dated, timestamped entry to .cursor/pm/brain/15_chat_summary_log.md. The PM may also update that log on its own when helpful. On new chat, review all memory docs including this log. See [.cursor/pm/LOG_CHAT_COMMAND.md](.cursor/pm/LOG_CHAT_COMMAND.md).

**/prepare-update** — Before pushing: verify system, audit server-agnostic, update changelog and DB docs (with @updater/@db), then report ready for publishing and suggest commit message. See [.cursor/pm/PREPARE_UPDATE_COMMAND.md](.cursor/pm/PREPARE_UPDATE_COMMAND.md).

**/apply-update** — Production: review latest MASTER_CHANGELOG entries and instruction docs, run each open production checklist, and calibrate this server with the latest update. See [.cursor/pm/APPLY_UPDATE_COMMAND.md](.cursor/pm/APPLY_UPDATE_COMMAND.md). Equivalent: @updater new update.

**/confirm-update** — After apply-update and any prod adjustments: review all changes and notes, mark everything up so that when you push, pull on dev (and other envs) keeps codebases and docs in sync. See [.cursor/pm/CONFIRM_UPDATE_COMMAND.md](.cursor/pm/CONFIRM_UPDATE_COMMAND.md).

**/daily-briefing** — Morning routine: memory, check G Drive for new/updated notes (track reviewed in .cursor/pm/daily_briefing_reviewed_drive.json), verify system, prod, news, tasks; deliver concise conversational briefing (high-level first, then next tasks to consider). See [.cursor/pm/DAILY_BRIEFING_COMMAND.md](.cursor/pm/DAILY_BRIEFING_COMMAND.md).

---

## @pm — Project Manager

**First step when invoked:** Before answering or acting, refresh context from memory: read `.cursor/pm/brain/INDEX.md`, then `15_chat_summary_log.md` (and other memory docs as needed). If the user asks whether you remember prior work or what you were discussing, answer from that context after this review—do not say you lack prior context without having checked memory.

**Works autonomously:** executes full workflows without asking permission each step. Use **@pm** for strategy, audits, agent/rules maintenance, and system-wide coordination. Only pauses for true blockers or decisions only you can make. See `.cursor/rules/pm.mdc`.

---

## @kalshi — Kalshi expert

**In-house authority on Kalshi:** company, news, markets, and especially API and WebSocket. Use **@kalshi** for anything Kalshi-related: API/WS behavior, fixed-point migration, our integration (trade_executor, kalshi_account_sync_ws, etc.), changelog impact. Research-first; no guessing. See `.cursor/rules/kalshi.mdc`.

---

## @frontend — Head of front-end development

**Head of front-end development and maintenance.** Expert in HTML, JS, CSS, mobile; owns our frontend UI and UI/UX. Use **@frontend** for frontend work, layout, responsiveness, and UX. See `.cursor/rules/frontend.mdc`.

---

## @db — Head of DB operations / PostgreSQL expert

**Head of DB operations:** Monitors all DB changes (from any process); ensures associated files and docs are updated so DB changes are painless across servers. Use **@db** for schema design, migrations, reference alignment, and anything that changes or depends on DB structure. Must use reversible migration pairs and `scripts/db/run_migration.py`; no ad hoc DDL. When the DB changes, @db ensures reference doc, database.py, migrations, memory (03), and changelog stay in sync. See `.cursor/rules/db.mdc`.

---

## @updater — Changelog / deployment

- **@updater prepare update** — Review changes, update changelog and DB docs before push.
- **@updater new update** — Run outstanding MASTER_CHANGELOG checklist tasks (production).

---

## @digitalocean — DigitalOcean expert

**In-house authority on DigitalOcean:** production server host and web domain host. Use **@digitalocean** for DO API, snapshots, backups, droplets, domains. Priority: see, create, modify, and delete snapshots and backups. Research-first; no guessing. See `.cursor/rules/digitalocean.mdc` and `.cursor/pm/DIGITALOCEAN_INTEGRATION.md`.

---

## @assistant — Personal assistant

**Personal assistant** for email, calendar, and other tasks that do not use rec.io operational system resources. Use **@assistant** for Gmail (search, read, draft, send), Google Calendar (events, free time), scheduling, and personal productivity. Does not touch backend, DB, trading, or deployment; for those, use @pm or the relevant domain agent. See `.cursor/rules/assistant.mdc`.
