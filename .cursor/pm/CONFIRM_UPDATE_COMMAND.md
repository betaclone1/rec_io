# /confirm-update command

Run **after** apply-update (and any prod adjustments) to ensure the update is fully documented and ready to sync. When you **push**, a **pull on dev** (and other environments) should result in **identical codebases and docs**.

## When to use

- Apply-update has run on prod.
- You (or the agent) made any adjustments on prod: code fixes, backfills, config or doc tweaks.
- You want to **push** and have **dev (and others) pull** so everything stays in sync.

## What the agent does

1. **Review all changes** — `git status`, `git diff`, `git diff --staged`. List every modified, added, or deleted file. Ensure nothing that should be shared is only in local state.
2. **Review MASTER_CHANGELOG** — Applied entries have Production checklists fully checked (`- [x]`). If an adjustment (e.g. fix or backfill) isn’t in the changelog, add a short note to the latest entry or to `docs/changelog/CONFIRM_UPDATE_NOTES.md` (create if needed).
3. **Review notes from the update** — Check `.cursor/pm/brain/` and any docs updated during/after apply-update. Ensure decisions/outcomes that affect sync are recorded in the repo.
4. **Mark everything up** — Every shared change is staged or listed. Run server-agnostic check; call out anything prod-only.
5. **Create commit message** — Output a commit message that **starts with `UPDATE CONFIRMED`** (on its own line), then a blank line, then a **rundown of everything done post git pull**: which MASTER_CHANGELOG entries were applied, which migrations or scripts ran, any fixes or backfills, new or updated commands/docs, and any other adjustments. Use short bullet lines. End with: "After push, run `git pull` on dev (and other envs) to sync."

## Defined in

- **Slash command:** `.cursor/commands/confirm-update.md`
- **Skill:** `.cursor/skills/confirm-update/SKILL.md`

If `/confirm-update` does not appear when you type `/`, try typing `/confirm-update` anyway, or say "confirm update".

## Relation to other commands

- **prepare-update** — Before push (e.g. on dev): verify, audit, update changelog/DB docs, get ready to publish.
- **apply-update** — On prod: run MASTER_CHANGELOG checklists, migrate, restart, verify.
- **confirm-update** — After apply-update (and any prod adjustments): review changes and notes, mark everything up so push + pull keeps all environments in sync.
