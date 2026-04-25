# Simple pull (production)

**Prerequisite:** Export `REC_PROD_SSH_HOST` to the production server IP or DNS name (SSH).

**Current production:** IPv4 **`165.22.13.146`**. Example: `export REC_PROD_SSH_HOST=165.22.13.146`. Canonical: `docs/PRODUCTION_HOST.md`.

Run when the user wants to **only** pull the latest commit on production—no snapshot, no restart, no migrations. For small pushes (e.g. frontend-only) that don't require the full backup/restart process.

## What to do

1. **Pull on prod via SSH** — From the **repo root**, run (uses `REC_PROD_SSH_HOST` or defaults to the IPv4 in `docs/PRODUCTION_HOST.md`):
   ```bash
   ./scripts/prod/simple_git_pull_on_prod.sh
   ```
   **Do not** use a one-liner like `REC_PROD_SSH_HOST=… ssh root@$REC_PROD_SSH_HOST '…'`: in bash the `$REC_PROD_SSH_HOST` in the destination is expanded **before** that assignment applies, so the host becomes empty and SSH fails. The script avoids that.

   **Alternative (manual):** export the host, then SSH:
   ```bash
   export REC_PROD_SSH_HOST=165.22.13.146   # or your DNS name; see PRODUCTION_HOST.md
   ssh root@$REC_PROD_SSH_HOST 'cd /opt/rec_io_server && git fetch && git checkout main && git pull --ff-only origin main'
   ```

2. **Report outcome** — If the command succeeded, report the pull result (e.g. "Already up to date" or the commit that was pulled). If it failed (e.g. not fast-forward, SSH error), report the error and do not claim success.

## What this does not do

- No snapshot or backup
- No migrations
- No MASTER_RESTART or supervisorctl
- No changelog checklist or verification steps

Existing processes keep running. Updated static files (HTML, JS, CSS, images) are served from the new tree on the next request. For changes that need a restart (e.g. backend Python), use `/apply-update-from-local` or the full prepare/apply flow instead.
