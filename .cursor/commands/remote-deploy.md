---
description: "Production: commit, push, pull on prod, and restart prod scripts if needed. Quick deploy for changes that don't need migrations or snapshots."
---

# Remote deploy (production)

**Prerequisite:** Export `REC_PROD_SSH_HOST` to the production server IP or DNS name (SSH).

**Current production:** IPv4 **`165.22.13.146`**. Example: `export REC_PROD_SSH_HOST=165.22.13.146`. Canonical: `docs/PRODUCTION_HOST.md`.

Quick deploy workflow: commit local changes, push to origin, pull on prod, and restart prod services **only if the changes require it**.

Use for straightforward changes that don't need migrations, snapshots, or the full changelog process. For changes requiring DB migrations, use `/push-commits-and-update-production` or `/apply-update-from-local` instead.

**Execute the full workflow** in `.cursor/skills/remote-deploy/SKILL.md`. Do not just describe the steps—run them.

**Summary:**
1. Stage and commit changes with a descriptive message
2. Push to origin
3. Pull on prod via SSH (`simple_git_pull_on_prod.sh`)
4. Analyze changed files to determine if restart is needed
5. If restart needed: run `MASTER_RESTART.sh` on prod via SSH
6. Report outcome (what was deployed, whether restart ran)
