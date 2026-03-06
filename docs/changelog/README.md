# Changelog

This folder holds:

- **MASTER_CHANGELOG.md** — Single internal changelog for production deployments.
- **CHANGELOG_AGENT_INSTRUCTIONS.md** — Instructions for the production agent (or `/changelog` action): read all open entries, execute each checklist fully, and update checkboxes. Use this when running the changelog workflow.
- **TODO.md** — Timestamped backlog of tasks to return to (checklist format, technical notes, milestones/completion). Check and update periodically. Tasks marked totally completed and older than 3 months may be moved to an archival doc to keep TODO.md lean.

- **When to update:** Add a new timestamped entry whenever you are about to push an update to production (e.g. after merging a feature branch to `main`).
- **What to include:** Summary of the change plus a **Production agent checklist**: markdown checkboxes (`- [ ]`) for every task the production agent must complete. Always include at least minimal items (e.g. "Confirm codebase changes", "Update local database" when schema changes exist). The agent both completes the tasks **and updates the checklist in `MASTER_CHANGELOG.md`** by checking off each box (`- [x]`) when done.
- **Workflow:** Merge to `main` → sync on production → production agent reads the latest changelog entry, works through the checklist (completing tasks **and** checking boxes in the file), then restarts services when complete. An update is not considered finished until the corresponding checklist items are marked as `[x]` in `MASTER_CHANGELOG.md`.
- **Running Python scripts:** Use the project venv so dependencies (e.g. `cryptography`) match the rest of the stack. From project root: `PYTHONPATH=$(pwd) venv/bin/python path/to/script.py` — not bare `python3`, which may point to a different environment and cause failures (e.g. missing `PSS.DIGEST_LENGTH` in Kalshi signing).
