---
description: "Verify system health on the production server (SSH). Same workflow as verify-local but run on prod: health, supervisor, logs, summary, status block."
---

# Verify production

Verify that the **production** server is running as intended. Use the **same verification workflow** as verify-local (`.cursor/commands/verify-local.md`), but run every step **on the production server** via SSH.

**Target:** `ssh root@137.184.224.94`; project path `/opt/rec_io_server` (logs at `/opt/rec_io_server/logs`). See `service ports in `backend/supervisord.conf`` (Production server section).

**Execute the workflow on prod:** Run each step by SSHing and executing the equivalent commands on the remote host (e.g. `curl -s localhost:3000/health`, `supervisorctl -c /opt/rec_io_server/backend/supervisord.conf status`, `tail -n 150 /opt/rec_io_server/logs/trade_executor.err.log`, etc.). Report results and end with the required status block (✅ All good / ⚠️ Investigate / 🔴 Critical). If status is Investigate or Critical, diagnose.

Any changes to the verification steps in VERIFY_COMMAND.md apply to both verify-local and verify-production.
