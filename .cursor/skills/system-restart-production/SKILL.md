# System restart production (MASTER_RESTART on prod + verify-production)

Run **MASTER_RESTART on the production server** via SSH, wait for it to finish, then **run verify-production** so the same report (including the required status block) is produced for the production server.

**Prerequisite:** Export `REC_PROD_SSH_HOST` to the production server IP or DNS name.

**Current production:** IPv4 **`165.22.13.146`** (SSH and PostgreSQL co-located). Example: `export REC_PROD_SSH_HOST=165.22.13.146` (and `REC_PROD_DB_HOST` for local DB scripts). Canonical: `docs/PRODUCTION_HOST.md`.

**Target:** `ssh root@$REC_PROD_SSH_HOST`. Project path on prod: **/opt/rec_io_server**.

## Steps

1. **Run MASTER_RESTART on prod**
   - From your **local** workspace, run:  
     `ssh root@$REC_PROD_SSH_HOST 'cd /opt/rec_io_server && ./scripts/MASTER_RESTART.sh'`
   - Invoke as a **blocking** command so it runs to completion. Do not run it in the background.
   - **Permissions:** SSH requires network access. The script runs on the remote host as root, so it can stop supervisor and free ports there.
   - Wait for the script to exit before continuing.
   - Note on console output: Supervisor may print internal `uncaptured python exception` / `FileNotFoundError` tracebacks during restart on macOS (kqueue/poller teardown). This is expected noise if the verification steps pass; do not treat it as an automatic failure.

2. **Run verify-production** — Execute the full verification workflow **exactly as the verify-production skill specifies** (Health, Supervisor, Logs, Summary, and the **required status block** at the end: `---` then blank line then `## ✅ All good` or `## ⚠️ Investigate` or `## 🔴 Critical`). Run all checks **on the production server via SSH**. Workflow: `.cursor/commands/verify-local.md`. Prod paths: logs at `/opt/rec_io_server/logs`, supervisor config `backend/supervisord.conf` (from project root `/opt/rec_io_server`).

Execute the restart and all checks; do not reply with instructions for the user to run themselves.
