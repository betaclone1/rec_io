# Script crash investigation (system_monitor, active_trade_supervisor) — 2026-03-14

**Status:** Complete. Revisit if system_monitor or similar crash recurs (no crash in months before this; may have been one-off). If it happens again, check `logs/supervisord.log` and system_monitor logs for the window before the failure; see docs/CRITICAL_ASSET_LOGGING.md.

---

## What actually happened (prod) — user observation

**Only two processes actually crashed:** system_monitor and one ATS iteration. Everything else was still RUNNING and had been up for over 12 hours. The “33 failed” in the logs was **not** reality; it was a false report (see below).

So the real unknowns are: **why did system_monitor crash, and why did that one ATS crash?** We have no log evidence that answers either.

---

## How the “33 failed” log fits (and why it’s wrong)

Prod logs show system_monitor reporting “Found 33 failed services” at 07:14 EDT and then running recovery (restarting services). Supervisor log shows it stopping and respawning main_app, trade_manager, etc. So in the logs it looks like “everything was down and system_monitor recovered them.” But the user saw only system_monitor and one ATS down; the rest were fine.

Plausible sequence that matches both the logs and the user:

1. **Earlier (unknown time):** system_monitor and one ATS (10009) actually crashed — cause unknown. No one was left to report; the other 31 processes kept running.
2. **Supervisor may have restarted system_monitor** (autorestart). When system_monitor came back up it ran its first health check. Due to a bug or race (e.g. wrong config path, or checking before supervisor state was consistent) it **incorrectly** saw all 33 as failed.
3. **07:14–07:16 EDT:** system_monitor’s recovery loop ran “restart” on every “failed” service. That (a) restarted processes that were already running, and (b) when it got to itself, it ran `supervisorctl restart system_monitor`, got SIGTERM, and never came back. ATS_10009 was also in the list; supervisor stopped it but the spawn never completed (or was lost), so it stayed down.
4. **~10:51 EDT (8am PST):** User manually started system_monitor and that ATS.

So the “33 failed” was system_monitor’s **mistaken** view after it had restarted, not a true mass outage. The two things we still don’t know: **what caused system_monitor to crash the first time, and what caused that one ATS to crash.** No exception or trigger was captured in the logs we have.

---

## Summary (short)

- **Prod:** Only system_monitor and one ATS actually went down; everything else stayed up 12+ hours. The “33 failed” in the log was a false report (system_monitor wrongly thought everyone was down after it came back and then killed itself by “restart self”). You manually started system_monitor and that ATS at ~8am PST. **Fixes implemented:** system_monitor no longer restarts itself synchronously (uses detached child + exit); ATS failsafe handles None DB conn. **Still unknown:** root cause of the original system_monitor crash and the original ATS crash.
- **Local:** system_monitor is STOPPED. ATS failsafe bug (None DB conn → restart loop) is fixed.

## Fixes (implemented)

- **active_trade_supervisor:** In `check_monitoring_failsafe()`, after `conn = get_db_connection()`, if `conn is None`, log that the failsafe is skipped (no DB connection; restart would not help) and `return`. Do not call `conn.cursor()` and do not escalate to process restart when the failure is DB unreachable.
- **system_monitor:** When `system_monitor` is in the failed list, we launch a **detached child** that sleeps 2s then runs `supervisorctl restart system_monitor`; then we **exit(0)**. The child (not us) asks supervisor to restart system_monitor; we are already gone, so supervisor spawns a new instance. Recovery still covers the whole system including self.

## Recommendations

- **Local:** Start system_monitor: `supervisorctl -c backend/supervisord.conf start system_monitor`.
- **Local:** Use a local PostgreSQL when developing so ATS does not depend on prod DB; or accept that when prod DB is unreachable from local, ATS will stay down until connectivity returns (with the fix, it will no longer restart in a loop).
- **Prod:** Fix deployed: system_monitor restarts itself via detached child + exit so the whole system (including self) is recovered. The initial cause of “all 33 failed” is still unknown (no log of what happened just before 07:14); if it recurs, check what triggers a full supervisor/process tree down (deploy, manual command, OOM, config reload).

---

## Log archive check (2026-03-14)

**Where we looked:** Prod `logs/archive` (rotated service logs), `logs/system_monitor.err.log.1` and `.2`, and `/tmp/supervisord.log` (no rotation; full history).

**Findings:** Rotated `system_monitor.err.log.1` contains past "Found 1 failed services" (single services), successful restarts, and "Maximum restart attempts reached - triggering MASTER RESTART" / "MASTER RESTART DISABLED". No timestamped "33 failed" or 07:14-specific lines (that line is in current `system_monitor.out.log`). Supervisor main log is a single file back to 2026-02-20.

**Conclusion:** Archive was checked; it does not contain evidence of the initial trigger for the 07:14 "33 failed" run.

**Follow-up (2026-03-14):** Critical-asset logging policy added so the same gap does not recur: see docs/CRITICAL_ASSET_LOGGING.md. Supervisord log is now under logs/ with rotation; system_monitor and cascading_failure_detector get higher retention.
