# Verification workflow (shared by verify-local and verify-production)

**Used by:** `/verify-local` (runs on the local server) and `/verify-production` (runs on the production server via SSH). **Any changes to this workflow apply to both commands.** Define the steps here only once; each command specifies where they run (local vs prod).

When the user invokes **/verify-local** or **/verify-production**, they want to confirm (on the chosen server) that: (1) the newest changes are in place, and (2) the system is running as intended.

## Agent behavior

The agent must **run the verification**, not just describe how. Execute checks on the target server (local or prod via SSH) and report results.

## Verification workflow

1. **Health endpoints** — Request main_app (port 3000) and trade_executor (port 8001) `/health`; confirm HTTP 200 and healthy payload. Note: trade_manager may not expose `/health`; 404 there is expected.
2. **Supervisor status** — If possible in the environment, run `supervisorctl -c backend/supervisord.conf status` and report process states. If blocked (e.g. permission/sandbox), note that and report what was checked.
3. **Recent logs** — Tail recent stderr/stdout for key services (e.g. trade_executor, kalshi_account_sync, main_app, one kalshi_market_watchdog). Look for tracebacks, fatal errors, or repeated failures. **Only treat an error as current if it occurred after the process started.** Logs are append-only; errors from before the last restart are stale. Get each service’s process start time (e.g. `ps -p <pid> -o lstart=` or supervisor uptime) and compare log timestamps. If an error line has no timestamp, use the timestamp of the preceding line in the same run. Do not flag stale errors as Investigate/Critical.
4. **Summary** — Report: health results, any supervisor summary, log findings, and a short conclusion (e.g. "system running as intended" or "issue found: …").
5. **Status (required, prominent)** — You MUST end the report with the status block. Output it exactly as follows (nothing after it). Choose one:
   - **✅ All good** — Everything is fine; all checks passed, no issues.
   - **⚠️ Investigate** — Potential issues that should be investigated (e.g. non-critical warnings, one service lagging, errors in logs).
   - **🔴 Critical** — Critical problems (e.g. health failures, processes not RUNNING, tracebacks or fatal errors in logs).
   **Format (output this block verbatim at the very end):**
   ```
   ---
   ## VERIFY STATUS
   ✅ All good
   ```
   Or use ⚠️ Investigate / 🔴 Critical as appropriate. The status line with the icon MUST appear. If there are any **current** errors in logs (timestamp after process start), do NOT report "All good"; use Investigate or Critical. Stale errors (before process start) do not count.

6. **If status is Investigate or Critical** — Do not stop at the status. Investigate the issue (e.g. read relevant code, check logs, run a diagnostic). Provide a short diagnosis: likely cause and, if possible, a recommended fix or next step.

Ports and log paths: see `.cursor/pm/brain/02_services_ports.md` and project `logs/` directory (e.g. `logs/main_app.out.log`, `logs/trade_executor.err.log`, `logs/kalshi_account_sync.out.log`).
