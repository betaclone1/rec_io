# Confirm update (post–apply-update)

Run this **after** apply-update has run on production and after any adjustments (fixes, backfills, doc updates) made to bring prod up to date. The goal is to **mark everything up** so that when the user **pushes**, a **pull on dev** (and other envs) results in **identical codebases and docs**—perfect sync across environments.

## What to do

1. **Review all changes** — `git status`, `git diff`, `git diff --staged`. List every modified/added/deleted file. Ensure no shared change is only local.
2. **Review MASTER_CHANGELOG** — Entries that were applied on prod should have their Production checklists fully checked (`- [x]`). If an adjustment (fix, backfill, etc.) isn’t reflected in the changelog, add a short note to the latest entry or to `docs/changelog/CONFIRM_UPDATE_NOTES.md` (create if needed) so the push carries that record.
3. **Review notes from the update** — Check `.cursor/plans/` (14_context_retention, 13_proposed_tasks, etc.) and any docs updated during/after apply-update. Ensure decisions or outcomes that affect sync are in the repo so dev gets them on pull.
4. **Mark everything up** — Every change that should be shared is staged or listed. Run server-agnostic check; call out anything prod-only.
5. **Create commit message** — Output a commit message that **starts with `UPDATE CONFIRMED`** (own line), then a blank line, then a **rundown of everything done post git pull**: MASTER_CHANGELOG entries applied, migrations/scripts run, fixes or backfills, new/updated commands or docs, and any other adjustments. Short bullet lines. End with: "After push, run `git pull` on dev (and other envs) to sync."

## Reference

- Command doc: `.cursor/commands/confirm-update.md`
- Changelog workflow: `docs/changelog/README.md`, `docs/changelog/MASTER_CHANGELOG.md`
