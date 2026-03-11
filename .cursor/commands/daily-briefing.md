---
description: "Morning routine: memory, Drive notes, verify, news, tasks; concise conversational briefing with high-level first, then next tasks to consider."
---

# Daily briefing (morning routine)

Run first thing each morning (or when requested). Delivers a **concise, conversational** briefing: high-level first, then drill down to a short list of next tasks to consider.

**Execute the full workflow** (do not just describe it):

1. **Memory and context** — Read `.cursor/pm/brain/INDEX.md`, then `15_chat_summary_log.md` and as needed 14, 13, 06, 00. Note open tasks and handoff items.
2. **Check G Drive** — Search Drive (e.g. REC_IO / Cursor, "Cursor Notes"). Fetch each note. Compare to `.cursor/pm/daily_briefing_reviewed_drive.json`; if doc missing or content changed, treat as new/updated. After review, update the log (last_reviewed, optional content_signature). **In briefing:** Include **Drive** only when there are new or updated notes; otherwise omit the section.
3. **Verify system (local + prod)** — Full health check per VERIFY_COMMAND (supervisor, health endpoints, key log tails). Prod via SSH (root@137.184.224.94, /opt/rec_io_server). Only errors after process start count. Conclude: All good / Investigate / Critical.
4. **Monitor_confirmed** — Run `scripts/diagnostics/check_monitor_confirmed_failures.py --days 7 --append-log`. **In briefing:** Include only if rise or persistence (see skill/DAILY_BRIEFING_COMMAND).
5. **Kalshi changelog** — Check https://docs.kalshi.com/changelog (always available). Prefer RSS; if RSS fails, fetch the page via web. **Derive actionable tasks** (migrate deprecated, verify after breaking change, new endpoints) and **add them to the central backlog** (13). **In briefing:** Include **Kalshi changelog** when relevant and call out any tasks added.
6. **External news** — One web search (macro/crypto first, then Kalshi/prediction-market). **In briefing:** Include **News** only when relevant; otherwise omit.
7. **Ongoing tasks** — From 13, 14, changelog TODO. **In briefing:** Include **Where we are** only when there is something to say; otherwise omit.
8. **Deliver the briefing** — Format for human eyes: clear headings, blank lines, bullets. **Omit any section that has nothing new or nothing to report** (no filler like "Nothing new on Drive," "No news," "No Kalshi updates").
   - **At a glance** — One or two sentences overall; optional one-line status.
   - **System** — Health and logs; bullets if multiple points; include monitor_confirmed only if rise/persistence.
   - **Drive** — Only when new/updated notes; otherwise omit.
   - **Kalshi changelog** — Only when RSS has new/relevant entries; otherwise omit.
   - **News** — Only when relevant; otherwise omit. No internal doc refs; use plain language.
   - **Where we are** — Only when there is something to say; otherwise omit.
   - **Next to consider** — Ranked list (bullets), one line per item.
   - **VERIFY STATUS** — One line: All good / Investigate / Critical.

End with VERIFY STATUS so the briefing stays consistent with verify-local/verify-production.

See .cursor/pm/DAILY_BRIEFING_COMMAND.md for format details and Drive reviewed-log.
