# PM / agent docs

Dedicated space for PM and agent documentation: behavior, memory, subagents, commands, and conventions. Kept here instead of in the main `docs/` folder.

**Tracking:** All custom command definitions and their rules/behaviors are tracked in git so they are available on every server. Tracked: `.cursor/commands/`, `.cursor/skills/`, `.cursor/pm/*.md` (and brain/), `.cursor/rules/`. Not tracked: `.cursor/mcp.json`, credentials, `gdrive-auth-url.txt`, and per-machine state (e.g. `*reviewed_drive*.json`). See .gitignore and brain/06_conventions_insights.md § Must-track paths.

**Organization:** Agent command documentation (verify, system-restart, log-chat, apply-update, confirm-update, prepare-update, daily-briefing) lives **only** in `.cursor/pm/`. Do not add or duplicate these in `docs/`; `docs/` is for project runbooks, changelog, and product/ops docs.

- **brain/** — PM memory / persistent context (INDEX, 00–15). Read on session start; write decisions, outcomes, handoff notes.
- **Command reference** — VERIFY_COMMAND.md, SYSTEM_RESTART_COMMAND.md, LOG_CHAT_COMMAND.md, APPLY_UPDATE_COMMAND.md, CONFIRM_UPDATE_COMMAND.md.
- **Org & rules** — ORG_CHART.md, PROJECT_RULES.md.
- **DB** — DB_REVERSIBLE_MIGRATIONS.md (revertible migration convention and runner).

`AGENTS.md` at repo root points here for org chart and command docs.
