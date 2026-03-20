# Project operating model

How persistence and the default workflow are organized in this repo.

## Persistence hierarchy

1. **Stable operating law** — `.cursor/rules/` (01–04). Core behavior, code safety, doc policy, planning standard. Rarely changed; not updated by routine tasks.
2. **Roles and handoffs** — `AGENTS.md`. Workflow agents (PM, Explorer, Builder, Reviewer), delegation rules, output schemas, persistence policy. Domain roster for delegation. Updated only when changing governance or agent definitions.
3. **Active task memory** — `.cursor/plans/`. One plan file per task; single source of truth for that task. Created at start, updated in place, closed when done. No rolling logs or append-only context files.
4. **Reference docs** — `docs/`, schema ref, changelog. Updated when DB or release-relevant changes occur (see code-change-safety and planning-standard).
5. **Ephemeral** — Chat and ad-hoc context. Default for conversation; no persistent artifact unless a plan exists or knowledge promotion is explicitly run.

**No:** Memory banks, rolling chat-summary vaults, or auto-updates to rules/AGENTS.md from task execution.

## Default workflow

1. **Task request** — User describes what they want. PM interprets (or user invokes a command).
2. **Start task** — `/start-task`. PM delegates to Explorer if scope is non-trivial: Explorer produces scope and a plan at `.cursor/plans/<task>.md`.
3. **Implement** — `/implement-plan` with plan path. Builder executes steps from the plan, edits code/docs, reports progress. No edits to rules or AGENTS.md unless plan includes knowledge promotion.
4. **Review** — `/review-change`. Reviewer checks changes against plan and safety rules; outputs pass / conditional_pass / rework. No edits to the change set.
5. **Knowledge promotion** — Only when justified. `/promote-knowledge` or explicit user request: add/update rules, AGENTS.md, or reference docs. Minimal, stable edits; one place per concept.

## Entrypoints

| Intent | Entrypoint |
|--------|------------|
| Start a task (PM coordinates) | `/start-task` |
| Scope only (Explorer) | `/inspect-surface` |
| Implement from plan (Builder) | `/implement-plan` |
| Review changes (Reviewer) | `/review-change` |
| Add durable rule/doc | `/promote-knowledge` |

Skills: `.cursor/skills/task-planning/`, `code-implementation/`, `change-review/`, `knowledge-promotion/`. Commands: `.cursor/commands/start-task.md`, `inspect-surface.md`, `implement-plan.md`, `review-change.md`, `promote-knowledge.md`.

## Domain agents

For domain-specific work (DB, frontend, analytics, deployment, Kalshi, DigitalOcean, personal assistant), PM delegates to the domain roster in AGENTS.md. Those agents use their own rules (e.g. `.cursor/rules/db.mdc` or archive). The workflow agents (PM, Explorer, Builder, Reviewer) handle task lifecycle and plans; domain agents handle expertise.
