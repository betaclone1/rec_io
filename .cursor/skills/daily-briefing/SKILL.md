# Daily briefing

Run when user wants morning routine. Concise briefing: high-level first, then next tasks. See .cursor/pm/DAILY_BRIEFING_COMMAND.md and 02_services_ports for details.

## Workflow (order)

1. **Memory** — Read INDEX, 15, then 14, 13, 06, 00 as needed. Note open tasks.
2. **G Drive** — Search/fetch notes (REC_IO / Cursor). Compare to daily_briefing_reviewed_drive.json; update log after review. Briefing: Drive section only when new/updated notes.
3. **Health (local + prod)** — For each: supervisorctl status, health (main_app :3000, trade_executor :8001), tail key logs for ERROR/FATAL/CRITICAL. Prod: ssh root@137.184.224.94, path /opt/rec_io_server. Briefing: "Local and prod: system health OK." or rundown by env.
4. **Monitor_confirmed** — Read log for previous days=7 total. Run `python3 scripts/diagnostics/check_monitor_confirmed_failures.py --days 7 --append-log`. Briefing: include only if current > 0 and (current > previous or previous > 0). One System bullet.
5. **Kalshi changelog** — Check docs.kalshi.com/changelog (RSS or page). Add tasks to 13. Briefing: section only when new/relevant entries.
6. **News** — One search: macro/crypto then Kalshi. Briefing: News only when relevant.
7. **Ongoing** — From 13, 14, TODO. Briefing: Where we are only when something to say.
8. **Output** — Sections: At a glance, System, Drive (if new), Kalshi (if new), News (if relevant), Where we are (if notable), Next to consider, VERIFY STATUS. Omit empty sections. Clear headings, bullets.

**If a step fails (MCP, SSH, script, fetch):** Do not skip. In the briefing include a "Failures" or inline note: what failed and the error. Retry once or try alternative. Never omit a failed step.
