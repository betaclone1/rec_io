---
description: "One-shot: prepare-update, commit and push with suggested message, then apply-update-from-local. For lighter, high-confidence updates."
---

# Push commits and update production

Single command that runs the full pre-push and deploy flow: **prepare-update** (snapshot, verify, changelog, suggested commit message), then **commit and push** all changes with that message, then **apply-update-from-local** (run production checklist on prod via SSH, verify, fidelity).

Use for lighter, high-confidence updates when you want a one-stop shop. For larger or riskier changes, run `/prepare-update` and `/apply-update-from-local` separately so you can review the commit and changelog before pushing.

**Production host:** IPv4 **`165.22.13.146`** — set `REC_PROD_SSH_HOST` before SSH steps (`docs/PRODUCTION_HOST.md`).

**Execute the full workflow** (do not just describe it):

1. **Run prepare-update** — Execute the prepare-update workflow (see `.cursor/skills/prepare-update/SKILL.md`): prod snapshot (blocking), verify local system, server-agnostic audit, plans → changelog and DB docs, flag issues, then produce the **suggested commit message** and report readiness. If prepare-update reports **blocking issues**, stop here; do not commit or push. Report the blocking issues and that the flow was aborted.

2. **Commit and push** — If prepare-update reported **ready for publishing** and produced a suggested commit message:
   - Stage all changes: `git add -A` (or the set of files that are part of this update).
   - Commit using the **exact suggested commit message** produced in step 1 (use the title + bullets as the commit message body).
   - Push to the current branch (typically `main`): `git push origin <branch>`.
   - If there is nothing to commit (e.g. already committed), run `git push` if the branch is ahead of origin.

3. **Run apply-update-from-local** — Execute the apply-update-from-local workflow (see `.cursor/skills/apply-update-from-local/SKILL.md`): confirm code is pushed, read changelog agent instructions, find open MASTER_CHANGELOG entries, execute each checklist task on prod via SSH, verify production, fidelity check, report outcome.

**References:** `.cursor/skills/prepare-update/SKILL.md`, `.cursor/skills/apply-update-from-local/SKILL.md`, `.cursor/commands/prepare-update.md`, `.cursor/commands/apply-update-from-local.md`.
