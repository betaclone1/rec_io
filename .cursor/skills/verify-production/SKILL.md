# Verify production

Run when the user wants to verify that the **production** server is running as intended. Use the **same verification workflow** as verify-local (`.cursor/commands/verify-local.md`), but run every step **on the production server** via SSH.

**Prerequisite:** Export `REC_PROD_SSH_HOST` to the production server IP or DNS name (SSH target).

**Current production:** IPv4 **`165.22.13.146`** (SSH and PostgreSQL on the same host). Example: `export REC_PROD_SSH_HOST=165.22.13.146`; for local scripts that open prod Postgres, also `export REC_PROD_DB_HOST=165.22.13.146`. Canonical: `docs/PRODUCTION_HOST.md`.

**Target:** `ssh root@$REC_PROD_SSH_HOST`. Project path on prod is **/opt/rec_io_server** (logs at `/opt/rec_io_server/logs`, supervisor config `/opt/rec_io_server/backend/supervisord.conf`). If `/opt/rec_io` is used and fails, try `/opt/rec_io_server`.

Execute each step by running the equivalent commands on the remote host (e.g. `curl -s localhost:3000/health`, `supervisorctl -c /opt/rec_io_server/backend/supervisord.conf status`, `tail -n 150 /opt/rec_io_server/logs/trade_executor.err.log`). Report results. End with the required status block (✅ All good / ⚠️ Investigate / 🔴 Critical). If status is Investigate or Critical, provide a short diagnosis.

Any changes to the workflow in VERIFY_COMMAND.md apply to both verify-local and verify-production. Run the checks; do not reply with instructions for the user to run themselves.
