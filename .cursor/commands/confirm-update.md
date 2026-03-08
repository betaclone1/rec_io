---
description: "After apply-update and any prod adjustments: review changes and notes, mark everything up so push + pull keeps all environments in sync."
---

# Confirm update (post–apply-update)

Run **after** apply-update has run on production and after any adjustments made to bring prod up to date (e.g. code fixes, backfills, doc updates). The goal: ensure all changes and notes from the update process are captured and marked up so that when you **push**, a **pull on dev** (or any other environment) brings the repo into perfect sync—identical codebases and docs everywhere.

**Execute (do not only describe):**

1. **Review all changes** — Run `git status`, `git diff`, `git diff --staged`. List every modified, added, or deleted file (code, docs, changelog, memory). Ensure nothing that should be shared is left only in local state.
2. **Review MASTER_CHANGELOG** — Confirm the entries that were applied on prod have their Production agent checklists fully checked (`- [x]`). If any adjustment (e.g. a fix or backfill) is not yet reflected in the changelog, add a short note to the latest entry or to `docs/changelog/CONFIRM_UPDATE_NOTES.md` (create if needed) describing what was done so the push carries that record.
3. **Review notes from the update** — Check `.cursor/pm/brain/` (e.g. 14_context_retention, 13_proposed_tasks) and any other docs updated during or after apply-update. Ensure any decisions or outcomes that affect sync (e.g. "we use amount_cents/created_ts on prod") are recorded in the repo so dev gets them when they pull.
4. **Mark everything up** — Ensure every change that should be in the repo is staged or explicitly listed. Run a server-agnostic check: no paths, hosts, or secrets in changed files that would break elsewhere; call out anything prod-specific.
5. **Create commit message** — Output a commit message that **starts with `UPDATE CONFIRMED`** (on its own line), then a blank line, then a **rundown of everything done post git pull**: what was applied (e.g. which MASTER_CHANGELOG entries, which migrations, which scripts), any fixes or backfills run, new or updated commands/docs, and any other adjustments. Use short bullet lines so the message doubles as the confirmation record. End with a line: "After push, run `git pull` on dev (and other envs) to sync."

See .cursor/pm/CONFIRM_UPDATE_COMMAND.md and docs/changelog/README.md.
