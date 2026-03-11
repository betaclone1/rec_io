# Changelog agent instructions

When the user runs **/apply-update-from-local** (from local) or **/apply-update** (when already on the prod server), the agent runs the production checklist **fully autonomously**. From local, follow `.cursor/commands/apply-update-from-local.md` (SSH to prod for each step). On prod, follow `.cursor/commands/apply-update.md`. Do not pause for permission; execute with the permissions needed for migrations, restart, and verify to succeed. The agent must do **both** of the following.

---

## 1. Read all open changelog entries

- Open `docs/changelog/MASTER_CHANGELOG.md`.
- Parse entries from newest to oldest (by date in the heading, e.g. `## 2026-03-07 — ...`).
- An entry is **open** if its **Production checklist** contains at least one unchecked box (`- [ ]`). Skip entries where every checklist item is already `- [x]`.

---

## 2. Follow the instructions fully for each open entry

For **each open entry** (only those with unchecked boxes), in **newest-first order**:

1. **Migration pre-flight (if checklist includes "Apply migrations")** — Before any pull or migration on the target server: verify every migration file referenced in the entry (e.g. `scripts/migrations/YYYYMMDD_HHMM_slug.up.sql` and `.down.sql`) is in the commit you are deploying (e.g. `git show --name-only HEAD`). If any is missing: **abort.** Do not pull, do not run migrations, do not restart. Report **🔴 Critical — update aborted.** Migration files reach prod only via git (commit and push); this command does not push. Do not SCP or copy migration files.
2. **Read the full entry** — Summary and every checklist item, including any sub-bullets or inline commands.
3. **Execute each unchecked task** in order:
   - **Confirm codebase** — Ensure the server (where the agent is running) has latest `main` (e.g. `git status`, `git log -1`). If not, pull (or tell the user to pull); do not proceed until codebase is synced (or user confirms).
   - **Update local database** — If the checklist says to run `init_database()`, run from project root:  
     `PYTHONPATH=$(pwd) venv/bin/python -c "from backend.core.config.database import init_database; init_database()"`
   - **Any one-time scripts** — If the checklist specifies a script (e.g. dedupe, historical ingest), run it exactly as written, from project root, with `PYTHONPATH=$(pwd) venv/bin/python` (or the exact command given). Run each such script only as many times as the entry says (e.g. "run once").
   - **Restart application services** — If the checklist says to restart, run `scripts/MASTER_RESTART.sh` (or the services/order specified). Run it blocking until complete; use the permissions required for it to succeed (e.g. full/unrestricted so supervisor and ports can be managed). After all checklist tasks, run the verify workflow (health, supervisor status, recent logs, status block).
   - **Verification steps** — Run any DB queries, log checks, or UI checks the checklist asks for.
4. **Update the checklist in MASTER_CHANGELOG.md** — After completing each task, change its `- [ ]` to `- [x]` in the file. Do this as you go (or immediately after finishing all tasks for that entry).
5. If a task cannot be completed (e.g. missing env, user intervention required), report clearly and do not mark it `[x]` until it is done.

---

## 3. Optional: internal “what changed” summary

If the /apply-update command is also defined to produce a **daily/weekly summary** of merged PRs/commits for the team (fun internal changelog):

- Use the **time period** specified (e.g. last 24 hours, last 7 days).
- Use `git log main --oneline`, and optionally `gh pr list --state merged`, to build the summary.
- That summary is **separate** from the production checklist work above. Do **both**: first complete all open production checklists (steps 1–2), then if requested generate the internal summary.

---

## Reference

- **Changelog workflow:** `docs/changelog/README.md`
- **Master list and checklists:** `docs/changelog/MASTER_CHANGELOG.md`
- **Python/venv:** From project root use `PYTHONPATH=$(pwd) venv/bin/python` for any script or one-liner; do not use bare `python3`.
