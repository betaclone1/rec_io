---
description: "After MASTER_RESTART (local): verify newest changes and system health on the local server. Run health checks, supervisor status, and recent logs; report results."
---

# Verify local (post–MASTER_RESTART)

MASTER_RESTART has been run on the **local** server. Verify that the newest changes are implemented and the system is running as intended **on this machine**.

**Run the verification** (do not just describe how). Execute the local verify workflow: health endpoints (main_app :3000, trade_executor :8001), supervisorctl status, tail key logs, summary, required status block, and if Investigate/Critical then diagnose.

Ports and log paths: service ports in `backend/supervisord.conf` and project `logs/` directory.
