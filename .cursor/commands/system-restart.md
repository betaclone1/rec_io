---
description: "Run MASTER_RESTART, wait for completion, then run verify-local (health, supervisor, logs, summary on local server)."
---

# System restart and verify-local

Run a full system restart on the **local** server, then run **verify-local** so the same report (including the required status block) is always produced.

**Execute in order (do not skip or only describe):**

1. **Run MASTER_RESTART** — From the project root, run: `bash scripts/MASTER_RESTART.sh` (or `./scripts/MASTER_RESTART.sh`). Use a single blocking invocation so the command runs to completion. Do not background it. **Important:** The script must stop supervisor and kill processes on ports; run it with full/unrestricted permissions (e.g. request `all` or disable sandbox for this invocation) so it can succeed. Sandboxed runs will fail with PermissionError or "port in use."
2. **Wait for completion** — The script exits when the restart is done. Proceed only after it has finished.
3. **Run verify-local** — Execute the full verification workflow **exactly as the verify-local command specifies** (`.cursor/commands/verify-local.md` and verify-local skill). That means: Health, Supervisor, Logs, Summary, and **the required status block at the end** (the `---` / `## VERIFY STATUS` / status line with icon and text, e.g. `✅ All good`; do not report "All good" if there are errors in logs). Do not omit any step.

Ports and log paths: service ports in `backend/supervisord.conf` and project `logs/` directory. Full verify spec: `.cursor/commands/verify-local.md`.
