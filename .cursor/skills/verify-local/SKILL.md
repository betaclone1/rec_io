# Verify local (post–MASTER_RESTART)

Run when the user has run MASTER_RESTART on the **local** server and wants to confirm the newest changes are in place and the system is running as intended **on this machine**.

Execute the local verification workflow in `.cursor/commands/verify-local.md` on the **local** server.

1. Health endpoints (main_app :3000, trade_executor :8001).
2. Supervisor status (`supervisorctl -c backend/supervisord.conf status`).
3. Recent logs (trade_executor, kalshi_account_sync, main_app, one kalshi_market_watchdog); only treat errors as current if after process start.
4. Summary and required status block (✅ All good / ⚠️ Investigate / 🔴 Critical).
5. If Investigate or Critical: diagnose.

Ports and logs: service ports in `backend/supervisord.conf`, project `logs/` directory. Run the checks; do not reply with instructions for the user to run themselves.
