---
description: "Morning routine: memory, Drive notes, verify, news, tasks; concise conversational briefing with high-level first, then next tasks to consider."
---

# Daily briefing (morning routine)

Run first thing each morning (or when requested). Delivers a **concise, conversational** briefing: high-level first, then drill down to a short list of next tasks to consider.

**Execute the full workflow** (do not just describe it):

1. **Memory and context** — Read `.cursor/pm/brain/INDEX.md`, then `15_chat_summary_log.md` and as needed 14, 13, 06, 00. Note open tasks and handoff items.
2. **Check G Drive for new or updated notes** — Search Drive (e.g. query for files in REC_IO / Cursor folder, or use known note docs like "Cursor Notes"). Fetch each note. Compare to `.cursor/pm/daily_briefing_reviewed_drive.json`: if a doc is not in the log or its content has changed (e.g. hash or significant change), treat as **new or updated** and surface in the briefing. After reviewing, **update the reviewed log** (add or update entry with `last_reviewed` date and optionally a short content signature so next run can detect updates). This "marks" that you have seen the note. See DAILY_BRIEFING_COMMAND.md for the log format.
3. **Verify system** — Health (main_app :3000, trade_executor :8001), supervisor status, recent logs for key services. Only errors after process start count. Conclude: All good / Investigate / Critical.
4. **Production** — If prod is documented and reachable (e.g. health URL), check and report in one line.
5. **External news** — One short web search (Kalshi, prediction markets, or crypto/financial). One or two sentences only.
6. **Ongoing tasks** — From 13, 14, changelog TODO: where things stand and what's blocked (one short paragraph).
7. **Deliver the briefing** formatted **for human eyes**: clear section headings, blank lines between sections, bullets for lists. Concise but readable — when something is worth mentioning (news, Drive updates, log issues), give enough detail to be useful.
   - **At a glance** — One or two sentences overall; optional one-line status.
   - **System** — Health and logs; bullets if multiple points; a sentence or two of detail for any real issues.
   - **Drive** — New/updated notes in a few lines or bullets if any; one line if nothing new. Mention if you updated the reviewed log.
   - **News** — When there are items worth mentioning: 2–4 sentences or a few bullets (what happened, why it might matter). When nothing relevant: skip or move on; do not add filler like "Nothing that affects us." Do not use internal doc references (e.g. "From 13"); use plain language ("open tasks", "our list", "changelog", etc.).
   - **Where we are** — Short paragraph or bullets on ongoing work and blockers.
   - **Next to consider** — Ranked list (bullets), one line per item.
   - **VERIFY STATUS** — One line: All good / Investigate / Critical.

End with VERIFY STATUS so the briefing stays consistent with /verify.

See .cursor/pm/DAILY_BRIEFING_COMMAND.md for format details and Drive reviewed-log.
