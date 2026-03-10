# Daily briefing (morning routine)

Run when the user wants the morning routine. Deliver a **concise, conversational** briefing: high-level first, then down to a short list of next tasks to consider. Include a **G Drive check** for new or updated notes and track what you've reviewed.

## Workflow (execute in order)

1. **Memory and context** — Read INDEX.md, 15_chat_summary_log.md, and as needed 14, 13, 06, 00. Note open tasks and handoffs.

2. **Check G Drive** — Search Drive for notes (e.g. in REC_IO / Cursor; or use known docs like "Cursor Notes"). Fetch each. Compare to `.cursor/pm/daily_briefing_reviewed_drive.json`: if file_id missing or content changed, treat as new/updated and include in briefing. After review, **update the log** (entry per file with `last_reviewed` date; optional `content_signature` hash to detect changes next run). Log format: `{ "file_id": { "name": "Title", "last_reviewed": "YYYY-MM-DD", "content_signature": "optional" } }`. Create the file if it doesn't exist. This marks notes as reviewed.

3. **Comprehensive system health check (local and prod)** — Run **separately** for local dev and for production (prod via SSH). **Prod:** `ssh root@137.184.224.94`; project path on prod is `/opt/rec_io_server` (logs at `/opt/rec_io_server/logs`). For **each** environment: (a) supervisorctl status — any process not RUNNING? (b) health endpoints (main_app :3000, trade_executor :8001). (c) Tail key logs (e.g. last 150–200 lines): trade_manager, trade_executor, main_app, kalshi_account_sync, cascading_failure_detector, one ATS, one AES. Look for ERROR, FATAL, CRITICAL, or anomalous patterns (e.g. repeated restarts, connection refused). **Report:** If nothing notable on either environment: one line **"Local and prod: system health OK."** If any issues: concise rundown by environment (Local / Prod) and what needs attention; do not list healthy items.

3b. **Monitor_confirmed check** — Run the check and only mention it if there is a **rise in frequency** or **persistence**. (Some failures over 7 days are expected; user only needs to know when it gets worse or keeps happening.) Steps: (1) Read `scripts/diagnostics/monitor_confirmed_failures_log.txt` and from the most recent line with `days=7` parse `total=N` (previous 7-day total; use 0 if file missing or no line with days=7). (2) Run `python3 scripts/diagnostics/check_monitor_confirmed_failures.py --days 7 --append-log`. (3) From the script output get current total (e.g. "Total: N trades"). (4) **Only include in the briefing** if current > 0 **and** (current > previous **or** previous > 0). So: report when failures have **risen** (current > previous) or are **persistent** (we had failures last time too). Do not report on a one-off non-zero. When reporting: short System bullet with total and which monitors/strategies, and that it indicates ATS not tracking some trades (ref docs/DIAGNOSIS_MONITOR_CONFIRMED_FALSE.md).

4. **External news** — One web search focused on **macro/crypto items that could move BTC or ETH** (e.g. major rate or inflation prints, ETF or regulatory headlines, large liquidations) **first**, and **Kalshi/prediction-market items** second. In the briefing, lead the News section with **price action and macro/crypto context**, then mention Kalshi/prediction-market headlines at the end if they matter. When there are items worth mentioning: give 2–4 sentences or a few bullets (what happened, and why it might matter for our trading or price behavior). When nothing relevant: one sentence. Don't compress real news into a single vague line.

5. **Ongoing tasks** — From 13_proposed_tasks, 14, docs/changelog/TODO.md. Short paragraph or bullets: where things stand, what's blocked.

6. **Immediately actionable findings** — If, during any step of the daily briefing, you find something that is **clearly immediately actionable without further CEO input** (e.g. muting pure noise logs, fixing a safe non-prod-only warning, tightening a harmless configuration, or similar low-risk cleanups), you **should go ahead and implement it** as part of the daily-briefing run before reporting back.

7. **Briefing output** — Format **for human eyes**: clear section headings (e.g. ## At a glance, ## System), blank lines between sections, bullets for lists. Concise but readable; when something matters, give enough detail to be useful.
   - **At a glance** — One or two sentences overall; optional one-line status.
   - **System** — Result of comprehensive health check (local + prod): either "Local and prod: system health OK." or a concise rundown of notable issues by environment. Include monitor_confirmed only if rise/persistence (step 3b). Bullets if multiple points.
   - **Drive** — New/updated notes in a few lines or bullets if any; one line if nothing new. Mention if you updated the reviewed log.
   - **News** — If worth mentioning: 2–4 sentences or a few bullets, leading with **BTC/ETH price action and macro/crypto items** that could show up as anomalous behavior in our trading, and then (if applicable) briefly covering **Kalshi/prediction-market** items at the end. If nothing relevant: skip the section; no filler like "Nothing that affects us." **No internal doc refs in the briefing** (e.g. "From 13", "14"); use plain language ("open tasks", "our list", "changelog").
   - **Where we are** — Short paragraph or bullets: ongoing work, blockers.
   - **Next to consider** — Ranked list (bullets), one line per item.
   - **VERIFY STATUS** — Single line: All good / Investigate / Critical.

References: .cursor/pm/DAILY_BRIEFING_COMMAND.md, .cursor/pm/brain/02_services_ports.md, .cursor/pm/GOOGLE_DRIVE_MCP_SETUP.md.
