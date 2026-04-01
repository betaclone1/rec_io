---
description: "Production: pull latest commit on prod only. No snapshot, no restart, no migrations. For small pushes (e.g. frontend-only) that don't need the full backup/restart process."
---

# Simple pull (production)

**Prerequisite:** Export `REC_PROD_SSH_HOST` to the production server IP or DNS name (SSH).

Pull the latest commit on the **production** server and do nothing else. No snapshot, no MASTER_RESTART, no migrations, no changelog checklist.

Use for small pushes (e.g. frontend-only or config tweaks) where you've already pushed from local and just need prod to have the new code. Existing processes keep running; static assets and HTML are served from the updated tree on next request.

**Execute the workflow** in `.cursor/skills/simple-pull/SKILL.md`: SSH to prod and run `git fetch && git checkout main && git pull --ff-only origin main`, report result.

**Target:** `ssh root@$REC_PROD_SSH_HOST`; project path `/opt/rec_io_server`.
