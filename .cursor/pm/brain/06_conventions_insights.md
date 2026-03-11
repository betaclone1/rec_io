# Conventions (single source of truth)

## Autonomy

Execute to completion. No permission loops. Stop only for: user-only decision, blocker, or destructive/irreversible action. Self-check: would the user consider this complete?

## When you don't know

Research first (web, docs, codebase). If still unknown, say so. No guessing.

## Context files and commits

**Paths:** `.cursor/pm/brain/`, `.cursor/rules/`, `.cursor/skills/`, `.cursor/commands/`

**Rule:** When you edit any of these, stage them and amend (or create) the single unpushed `ctx:` commit. One ctx commit only; no spam. Amend only while unpushed. CHANGES panel stays clear of context-only edits.

**PM backstop:** At end of every PM response, run `git status` on context paths; if modified, stage and amend ctx.

## Project rules

- **Server agnostic:** Same codebase runs locally and on prod; config from env. See PROJECT_RULES.md.
- **Git:** No push/pull without CEO approval. Must-track paths: .cursor/commands, .cursor/skills, .cursor/pm (md + brain), .cursor/rules; scripts/migrations/*.sql; docs/changelog; AGENTS.md. Confirm .gitignore doesn't exclude them when you add files.
- **Changelog/DB/restart:** See docs/changelog, APPLY_UPDATE_COMMAND.md, PROJECT_RULES.md. DB verification required before confirming any update. Simple schema = checklist DDL or init_database, not new migration files.

## Naming

users _0001; monitor_list_0001 id 10xxx; active_trades_0001_10xxx. Symbols: btc, eth, spx, ndx. Ports: MASTER_PORT_MANIFEST, get_port("main_app").

## Delegation

@frontend UI/UX. @db schema, migrations, reference. @analyst analytics, backtests, strategy. @updater changelog, deploy. @kalshi API, WebSocket. @assistant email, calendar. Roster: AGENTS.md, ORG_CHART.md. Conventions: this doc only; do not duplicate.
