# Verify (post–MASTER_RESTART)

Run this when the user has executed MASTER_RESTART and wants to confirm the newest changes are in place and the system is running as intended.

## What to do

1. **Health endpoints** — Request main_app (port 3000) and trade_executor (port 8001) `/health`; confirm HTTP 200 and healthy payload. (trade_manager may not expose `/health`; 404 there is expected.)
2. **Supervisor status** — Run `supervisorctl -c backend/supervisord.conf status` and report process states. If blocked (e.g. permission), note it and report what was checked.
3. **Recent logs** — Tail recent stderr/stdout for trade_executor, kalshi_account_sync, main_app, and one kalshi_market_watchdog. Look for tracebacks or fatal errors. **Only treat an error as current if it occurred after the process started.** Logs are append-only; errors from before the last restart are stale. Get each service’s process start time (e.g. `ps -p <pid> -o lstart=` or supervisor uptime) and compare log timestamps. If an error line has no timestamp, use the timestamp of the preceding line in the same run. Do not flag stale errors as Investigate/Critical.
4. **Summary** — Report health results, supervisor summary, log findings, and a short conclusion (e.g. "system running as intended" or "issue found: …").
5. **Status (required, prominent)** — On its own line at the very end of the report, output exactly one of these (icon + text so it’s visible even if the icon doesn’t render):
   - **✅ All good** — Everything is fine; all checks passed, no issues.
   - **⚠️ Investigate** — Potential issues that should be investigated.
   - **🔴 Critical** — Critical problems (health failures, processes not RUNNING, tracebacks or fatal errors).
   End the report with the status block (nothing after it). If there are any **current** errors in logs (timestamp after process start), do NOT report "All good". Stale errors (before process start) do not count. Format (output verbatim at the very end):
   ```
   ---
   ## VERIFY STATUS
   ✅ All good
   ```
   Or substitute ⚠️ Investigate / 🔴 Critical. The line with the icon MUST appear.

6. **If status is Investigate or Critical** — Investigate the issue (code, logs, diagnostic) and provide a short diagnosis: likely cause and recommended fix or next step.

Ports: see .cursor/pm/brain/02_services_ports.md. Logs: project `logs/` directory (e.g. logs/main_app.out.log, logs/trade_executor.err.log, logs/kalshi_account_sync.out.log).

Run the checks; do not reply with instructions for the user to check themselves.
