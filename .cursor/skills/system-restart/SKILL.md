# System restart (MASTER_RESTART + verify)

Run MASTER_RESTART, wait for it to finish, then **run the verify command** so the same report (including the required status block) is always produced.

## Steps

1. **Run MASTER_RESTART**
   - From project root: `bash scripts/MASTER_RESTART.sh` (or `./scripts/MASTER_RESTART.sh`).
   - Invoke it as a blocking command so it runs to completion. Do not run it in the background.
   - **Run with full permissions:** The script stops supervisor and kills processes on ports. Use unrestricted/sandbox-disabled permissions for this invocation (e.g. request `all`); otherwise it will fail with PermissionError or "Failed to free port."
   - Wait for the script to exit before continuing.

2. **Run the verify command** — Execute the full verify workflow **exactly as the verify command/skill specifies** (Health, Supervisor, Logs, Summary, and the **required status block** at the end: `---` then blank line then `## ✅ All good` or `## ⚠️ Investigate` or `## 🔴 Critical`). Do not omit any verify step.

Ports: .cursor/pm/brain/02_services_ports.md. Logs: project `logs/` (e.g. logs/main_app.out.log, logs/trade_executor.err.log, logs/kalshi_account_sync.out.log). Full verify spec: .cursor/commands/verify.md and verify skill.

Execute the restart and all checks; do not reply with instructions for the user to run themselves.
