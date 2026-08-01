---
description: "Production: commit, push, pull on prod, and restart only the specific scripts affected. Quick deploy for changes that don't need migrations or snapshots."
---

# Remote deploy (production)

**Prerequisite:** Export `REC_PROD_SSH_HOST` to the production server IP or DNS name (SSH).

**Current production:** IPv4 **`165.22.13.146`**. Example: `export REC_PROD_SSH_HOST=165.22.13.146`. Canonical: `docs/PRODUCTION_HOST.md`.

Quick deploy workflow: commit local changes, push to origin, pull on prod, and restart **only the specific supervisor programs affected** by the changes.

Use for straightforward changes that don't need migrations, snapshots, or the full changelog process. For changes requiring DB migrations, use `/push-commits-and-update-production` or `/apply-update-from-local` instead.

**Execute the full workflow** in `.cursor/skills/remote-deploy/SKILL.md`. Do not just describe the steps—run them.

**Summary:**
1. Stage and commit changes with a descriptive message
2. Push to origin
3. Pull on prod via SSH (`simple_git_pull_on_prod.sh`)
4. Analyze changed files to determine which programs need restart
5. Restart **only affected programs** via `supervisorctl restart <program>` (NOT full MASTER_RESTART unless absolutely necessary)
6. Verify restarted programs are running
7. Report outcome (what was deployed, which programs restarted)

**MASTER_RESTART is only used if:** supervisor config changed, requirements.txt changed, or broad infrastructure changes affect most programs.
