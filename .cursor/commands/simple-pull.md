---
description: "Production: pull latest commit on prod only. No snapshot, no restart, no migrations. For small pushes (e.g. frontend-only) that don't need the full backup/restart process."
---

# Simple pull (production)

**Prerequisite:** Export `REC_PROD_SSH_HOST` to the production server IP or DNS name (SSH).

**Current production:** IPv4 **`165.22.13.146`**. Example: `export REC_PROD_SSH_HOST=165.22.13.146`. Canonical: `docs/PRODUCTION_HOST.md`.

Pull the latest commit on the **production** server and do nothing else. No snapshot, no MASTER_RESTART, no migrations, no changelog checklist.

Use for small pushes (e.g. frontend-only or config tweaks) where you've already pushed from local and just need prod to have the new code. Existing processes keep running; static assets and HTML are served from the updated tree on next request.

**Execute the workflow** in `.cursor/skills/simple-pull/SKILL.md`. Prefer from repo root: `./scripts/prod/simple_git_pull_on_prod.sh` (correct host resolution; avoids bash `VAR=value ssh root@$VAR` pitfall).

**Target:** `root@$REC_PROD_SSH_HOST` (or canonical IP default in the script); project path `/opt/rec_io_server`.
