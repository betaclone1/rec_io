---
description: "Production: pull latest commit on prod only. No snapshot, no restart, no migrations. Aborts if the pull range includes scripts/migrations/*.up.sql."
---

# Simple pull (production)

**Prerequisite:** Export `REC_PROD_SSH_HOST` to the production server IP or DNS name (SSH).

**Current production:** IPv4 **`165.22.13.146`**. Example: `export REC_PROD_SSH_HOST=165.22.13.146`. Canonical: `docs/PRODUCTION_HOST.md`.

Pull the latest commit on the **production** server and do nothing else. No snapshot, no MASTER_RESTART, no migrations, no changelog checklist.

**Migration gate:** Before pulling, diff prod HEAD vs the commit to pull for `scripts/migrations/*.up.sql`. If any appear, **abort** and use `/apply-update-from-local` (pull does not enact schema). See `.cursor/rules/10-deploy-migrations-gate.mdc`.

Use for small pushes (e.g. frontend-only or config tweaks) where you've already pushed from local and just need prod to have the new code. Existing processes keep running; static assets and HTML are served from the updated tree on next request.

**Execute the workflow** in `.cursor/skills/simple-pull/SKILL.md`. Prefer from repo root: `./scripts/prod/simple_git_pull_on_prod.sh` (correct host resolution; avoids bash `VAR=value ssh root@$VAR` pitfall).

**Target:** `${REC_PROD_SSH_USER:-root}@$REC_PROD_SSH_HOST` (defaults in script); project path `/opt/rec_io_server`. See `docs/CURSOR_CLOUD_PROD_SSH_ACCESS_PROPOSAL.md` for Cursor Cloud SSH user and secrets.
