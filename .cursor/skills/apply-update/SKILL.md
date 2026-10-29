# Apply update (production)

When the user invokes **/apply-update** (or "apply update", "follow the changelog instructions"), they want the production server calibrated with the latest update. **Fully autonomous:** apply all necessary changes (including DB migrations), run `scripts/MASTER_RESTART.sh` when the checklist requires a restart (blocking until complete), then run the verify workflow. Do not pause for permission; execute with the permissions needed for migrations, restart, and verify to succeed.

**Use this only when the agent is already on the production server.** From local, use **/apply-update-from-local** (SSH target: `docs/PRODUCTION_HOST.md`, currently **165.22.13.146**).

## What to do

1. **Read the agent instructions** — Open and follow `docs/changelog/CHANGELOG_AGENT_INSTRUCTIONS.md` in full. It defines how to find open entries and how to execute each task.
2. **List open entries** — In `docs/changelog/MASTER_CHANGELOG.md`, find every entry whose **Production checklist** has at least one `- [ ]`. Process entries **newest-first** (by date in the heading, e.g. `## 2026-03-08 — ...`).
3. **For each open entry** — In order: read the full entry (summary + every checklist item). Execute each unchecked task: confirm codebase (production has latest `main`), run migrations or one-time scripts exactly as written (**pull → `run_migration.py up` → restart**; git files alone do not change the DB — `.cursor/rules/10-deploy-migrations-gate.mdc`), **run `scripts/MASTER_RESTART.sh` when the checklist requires a restart** (blocking until complete), run any verification steps. After completing a task, change its `- [ ]` to `- [x]` in MASTER_CHANGELOG.md. If a task cannot be completed (e.g. missing env), report and do not mark it done.
4. **Orphan migration scan** — Compare `scripts/migrations/*.up.sql` on disk to `run_migration.py list`. Apply any shipped-but-unapplied ids before claiming success; otherwise VERIFY **🔴 Critical**.
5. **After all checklist tasks** — Run the verify workflow (health endpoints, supervisor status, recent logs, status block per `.cursor/commands/verify-local.md`) to confirm the system is up and running. Do not report All good if required migrations were not applied.

## Reference

- Full instructions: `docs/changelog/CHANGELOG_AGENT_INSTRUCTIONS.md`
- Master checklist: `docs/changelog/MASTER_CHANGELOG.md`
- Command doc: `.cursor/commands/apply-update.md`
- Deploy gate: `.cursor/rules/10-deploy-migrations-gate.mdc`
