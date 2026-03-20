# System restart local (MASTER_RESTART + verify-local)

Run MASTER_RESTART **on the local server**, wait for it to finish, then **run verify-local** so the same report (including the required status block) is always produced on the local server.

## Steps

1. **Run MASTER_RESTART**
   - From project root: `bash scripts/MASTER_RESTART.sh` (or `./scripts/MASTER_RESTART.sh`).
   - Invoke it as a blocking command so it runs to completion. Do not run it in the background.
   - **Run with full permissions:** The script stops supervisor and kills processes on ports. Use unrestricted/sandbox-disabled permissions for this invocation (e.g. request `all`); otherwise it will fail with PermissionError or "Failed to free port."
   - Wait for the script to exit before continuing.
   - Note on console output: Supervisor may print internal `uncaptured python exception` / `FileNotFoundError` tracebacks during restart on macOS (kqueue/poller teardown). This is expected noise if the verification steps pass; do not treat it as an automatic failure.

2. **Run verify-local** — Execute the full verification workflow **exactly as the verify-local command/skill specifies** (Health, Supervisor, Logs, Summary, and the **required status block** at the end: `---` then blank line then `## ✅ All good` or `## ⚠️ Investigate` or `## 🔴 Critical`). Do not omit any step. Workflow steps: .cursor/commands/verify-local.md.

Ports: service ports in `backend/supervisord.conf`. Logs: project `logs/` (e.g. logs/main_app.out.log, logs/trade_executor.err.log, logs/kalshi_account_sync.out.log).

Execute the restart and all checks; do not reply with instructions for the user to run themselves.
