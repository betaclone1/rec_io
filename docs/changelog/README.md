# Changelog

This folder holds:

- **MASTER_CHANGELOG.md** — Single internal changelog for production deployments.
- **CHANGELOG_AGENT_INSTRUCTIONS.md** — Instructions for the production agent (or `/apply-update` action): read all open entries, execute each checklist fully, and update checkboxes. Use this when running the changelog workflow.
- **TODO.md** — Pointer to task tracking: active backlog is in `.cursor/plans/`. Historical changelog backlog was archived to `archive/2026-03-housekeeping/docs/TODO_changelog_backlog.md`; we work from the PM system (plans) from here on.

- **When to update:** Add a new timestamped entry whenever you are about to push an update to production (e.g. after merging a feature branch to `main`).
- **What to include:** Summary of the change plus a **Production checklist**: markdown checkboxes (`- [ ]`) for every task to complete when applying the update (from local via /apply-update-from-local or on prod via /apply-update). Always include at least minimal items (e.g. "Confirm codebase changes", "Update local database" when schema changes exist). The agent both completes the tasks **and updates the checklist in `MASTER_CHANGELOG.md`** by checking off each box (`- [x]`) when done.
- **Workflow:** Merge to `main` → sync on production → production agent runs **/apply-update** (reads latest changelog entry, works through the checklist, completes tasks and checks boxes, restarts when needed). After any prod-only adjustments (fixes, backfills, docs), run **/confirm-update** to review all changes and notes and mark everything up so that a **push** plus **pull on dev** keeps all environments in sync. An update is not considered finished until the corresponding checklist items are marked as `[x]` in `MASTER_CHANGELOG.md` and confirm-update has been run if there were prod adjustments.
- **Confirm-update:** Run on prod after apply-update (and any tweaks). Reviews git changes, MASTER_CHANGELOG checkboxes, and notes (e.g. `.cursor/pm/brain/`, optional `docs/changelog/CONFIRM_UPDATE_NOTES.md`). Produces a confirmation summary and ensures the repo is ready to push so dev can pull and stay identical.
- **Running Python scripts:** Use the project venv so dependencies (e.g. `cryptography`) match the rest of the stack. From project root: `PYTHONPATH=$(pwd) venv/bin/python path/to/script.py` — not bare `python3`, which may point to a different environment and cause failures (e.g. missing `PSS.DIGEST_LENGTH` in Kalshi signing).
