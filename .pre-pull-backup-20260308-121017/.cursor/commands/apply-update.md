---
description: "Production: review latest MASTER_CHANGELOG entries and instruction docs, run each open checklist, and calibrate this server with the latest update."
---

# Apply update (production)

Run when this server (e.g. production or another deployment) has pulled the latest code and should be **calibrated with the latest update**: review the latest changelog entries and instruction docs, then execute every open production checklist so this server matches the release.

**Execute the full workflow** (do not just describe it):

1. **Read the agent instructions** — Open `docs/changelog/CHANGELOG_AGENT_INSTRUCTIONS.md` and follow it in full.
2. **Find open entries** — In `docs/changelog/MASTER_CHANGELOG.md`, list every entry that has at least one unchecked Production agent checklist item (`- [ ]`). Process **newest-first** (by date in the heading).
3. **Execute each open entry** — For each such entry, in order:
   - Confirm codebase (e.g. `git status`, `git log -1`; ensure this server has latest `main` or the commit you intend).
   - Run any "Update local database" step (e.g. `init_database()`, or the exact command in the checklist).
   - Run any one-time scripts the checklist specifies (from project root, with `PYTHONPATH=$(pwd) venv/bin/python` or as written).
   - Restart services if the checklist says so (e.g. `scripts/MASTER_RESTART.sh` or the listed services).
   - Run any verification steps (DB, logs, UI) the checklist asks for.
   - After completing each task, update `MASTER_CHANGELOG.md`: change that item from `- [ ]` to `- [x]`.
4. **Report** — Summarize what was done (which entries, which tasks, any failures or blocks).

If a task cannot be completed (e.g. missing env, user intervention required), report clearly and do not mark it `[x]` until it is done.

See `.cursor/commands/apply-update.md` and `docs/changelog/CHANGELOG_AGENT_INSTRUCTIONS.md`. Equivalent: **@updater new update**.
