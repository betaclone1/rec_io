# Daily briefing (morning routine)

Run when the user wants the morning routine. Deliver a **concise, conversational** briefing: high-level first, then down to a short list of next tasks to consider. Include a **G Drive check** for new or updated notes and track what you've reviewed.

## Workflow (execute in order)

1. **Memory and context** — Read INDEX.md, 15_chat_summary_log.md, and as needed 14, 13, 06, 00. Note open tasks and handoffs.

2. **Check G Drive** — Search Drive for notes (e.g. in REC_IO / Cursor; or use known docs like "Cursor Notes"). Fetch each. Compare to `.cursor/pm/daily_briefing_reviewed_drive.json`: if file_id missing or content changed, treat as new/updated and include in briefing. After review, **update the log** (entry per file with `last_reviewed` date; optional `content_signature` hash to detect changes next run). Log format: `{ "file_id": { "name": "Title", "last_reviewed": "YYYY-MM-DD", "content_signature": "optional" } }`. Create the file if it doesn't exist. This marks notes as reviewed.

3. **Verify system** — Health (main_app :3000, trade_executor :8001), supervisorctl status, tail logs for trade_executor, kalshi_account_sync, main_app, one kalshi_market_watchdog. Only current errors (after process start). Result: All good / Investigate / Critical.

4. **Production** — If prod health URL is documented, check it; one line in briefing.

5. **External news** — One web search (Kalshi, prediction markets, crypto/financial). When there are items worth mentioning: give 2–4 sentences or a few bullets (what happened, why it might matter). When nothing relevant: one sentence. Don't compress real news into a single vague line.

6. **Ongoing tasks** — From 13_proposed_tasks, 14, docs/changelog/TODO.md. Short paragraph or bullets: where things stand, what's blocked.

7. **Briefing output** — Format **for human eyes**: clear section headings (e.g. ## At a glance, ## System), blank lines between sections, bullets for lists. Concise but readable; when something matters, give enough detail to be useful.
   - **At a glance** — One or two sentences overall; optional one-line status.
   - **System** — Health and logs; bullets if multiple points; a sentence or two of detail for any real issues.
   - **Drive** — New/updated notes in a few lines or bullets if any; one line if nothing new. Mention if you updated the reviewed log.
   - **News** — If worth mentioning: 2–4 sentences or a few bullets. If nothing relevant: skip the section; no filler like "Nothing that affects us." **No internal doc refs in the briefing** (e.g. "From 13", "14"); use plain language ("open tasks", "our list", "changelog").
   - **Where we are** — Short paragraph or bullets: ongoing work, blockers.
   - **Next to consider** — Ranked list (bullets), one line per item.
   - **VERIFY STATUS** — Single line: All good / Investigate / Critical.

References: .cursor/pm/DAILY_BRIEFING_COMMAND.md, .cursor/pm/brain/02_services_ports.md, .cursor/pm/GOOGLE_DRIVE_MCP_SETUP.md.
