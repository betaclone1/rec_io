---
description: "After MASTER_RESTART: verify newest changes and system health. Run health checks, supervisor status, and recent logs; report results."
---

# Verify system (post–MASTER_RESTART)

MASTER_RESTART has been run. Verify that the newest changes are implemented and the system is running as intended.

**Run the verification** (do not just describe how). Execute:

1. **Health** — main_app :3000 and trade_executor :8001 `/health` → expect 200.
2. **Supervisor** — `supervisorctl -c backend/supervisord.conf status` → report RUNNING processes.
3. **Logs** — Tail recent output for trade_executor, kalshi_account_sync, main_app, one kalshi_market_watchdog; look for tracebacks or errors. **CRITICAL: Only treat an error as current if it occurred after the process started.** Log files are append-only; errors from previous runs (before the last restart) are stale. Get each service’s process start time (e.g. `ps -p <pid> -o lstart=` or supervisor uptime), then compare log timestamps to that. If an error line has no timestamp, use the timestamp of the immediately preceding line in the same run (e.g. balance sync at 14:25 → the next line is from that same 14:25 run). Do not report "Investigate" or "Critical" for errors that are before the current process start.
4. **Summary** — Report results and conclude (e.g. system running as intended, or issue found).
5. **Status (required, prominent)** — On its own line at the very end of the report, output exactly one of these (icon + text so it’s visible even if the icon doesn’t render):
   - **✅ All good** — Everything is fine; all checks passed, no issues.
   - **⚠️ Investigate** — Potential issues that should be investigated (e.g. non-critical warnings, one service lagging, deprecation warnings).
   - **🔴 Critical** — Critical problems (e.g. health failures, processes not RUNNING, tracebacks or fatal errors in logs).
   You MUST end the report with the status block below (nothing after it). If there are any **current** errors in logs (errors with timestamps after the relevant process started), do NOT report "All good"; use Investigate or Critical. Stale errors (before process start) do not count. Format (output verbatim at the very end):
   ```
   ---
   ## VERIFY STATUS
   ✅ All good
   ```
   Or use ⚠️ Investigate / 🔴 Critical. The status line with the icon MUST appear.

6. **If status is Investigate or Critical** — Do not stop at the status. Investigate the issue (e.g. read relevant code, check logs, run a diagnostic). Provide a short diagnosis: likely cause and, if possible, a recommended fix or next step.

See .cursor/pm/VERIFY_COMMAND.md and .cursor/pm/brain/02_services_ports.md for ports and log paths.
