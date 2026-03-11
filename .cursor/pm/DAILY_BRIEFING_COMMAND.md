# /daily-briefing command

**Defined in:** `.cursor/commands/daily-briefing.md` and `.cursor/skills/daily-briefing/SKILL.md`.

Morning routine: refresh context, check Drive for new notes, verify system, skim news, then deliver a **concise, conversational** briefing. High-level first, then drill down to a short list of next tasks to consider.

---

## Briefing format (for human eyes)

Include these sections when they have content. Omit any section with nothing to report.

**Structure** — Output in this order. **Omit any section that has nothing new or nothing to report**; do not add filler like "Nothing new on Drive," "No news," or "No Kalshi updates." Use a heading only for sections you include (e.g. `## At a glance`, `## System`, `## Drive`), with a blank line after each heading before the content.

1. **At a glance** — One or two sentences: how things are overall (system, prod, any standout). Optional one-line status if helpful.

2. **System** — Health and logs in a short, readable block. Use bullets if there are multiple points. If there are log issues worth noting, give a sentence or two of detail; if all quiet, say so in one line.

3. **Drive** — Include only when there are new or updated notes; summarize in a few lines or bullets. If nothing new, omit the section.

4. **Kalshi changelog** — Include only when the Kalshi changelog RSS (or changelog page) has new or relevant entries (API changes, deprecations, new fields). If nothing relevant or feed unavailable, omit the section.

5. **News** — Include only when there is relevant macro/crypto or prediction-market news; give 2–4 sentences or a few bullets (what happened, why it might matter). If nothing relevant, omit the section.

6. **Where we are** — Short paragraph on ongoing work and blockers when there is something to say; otherwise omit or keep to one line.

7. **Next to consider** — Ranked list (bullets or numbers), high-level to tactical. One line per item; easy to scan.

8. **VERIFY STATUS** — Single line at the end: All good / Investigate / Critical.

**Tone:** Conversational. Prefer "we" and clear, concrete detail over either lengthy prose or telegraphic one-liners when the content warrants it.

**No internal jargon in the briefing.** Do not refer to memory doc numbers or file names (e.g. "From 13", "14", "15", "13_proposed_tasks"). Use plain language the reader understands: "open tasks", "our task list", "recent sessions", "Drive", "changelog backlog", etc.

---

## G Drive: new/updated notes and "reviewed" tracking

Part of the routine is to **check G Drive** (REC_IO / Cursor folder, or known note docs like "Cursor Notes") for **new or updated notes** you haven't seen before.

- **How:** Use the G Drive MCP **search** (e.g. query for Cursor folder or "Cursor Notes"), then **fetch** each note resource (`gdrive:///FILE_ID`). Read the content.
- **Detecting new/updated:** Keep a local log so we know what's been reviewed:
  - **File:** `.cursor/pm/daily_briefing_reviewed_drive.json`
  - **Format:** `{ "file_id": { "name": "Doc title", "last_reviewed": "YYYY-MM-DD", "content_signature": "optional_hash_or_short_checksum" } }`
  - If a doc is **not** in the log, treat it as new; include it in the briefing.
  - If you store `content_signature` (e.g. hash of first 500–1000 chars or of key lines), and on a later run the same doc has a different signature, treat it as **updated** and surface in the briefing.
  - After you've reviewed a note (read it and included any new/updated content in the briefing), **update the log**: set `last_reviewed` to today, and optionally update `content_signature`. Create the file if it doesn't exist.
- **"Mark when reviewed":** Updating this JSON is how we "mark" that we've reviewed the note. Next run can then tell "already seen on YYYY-MM-DD" or "content changed since then."

**If migrating from /daily-update:** Rename `.cursor/pm/daily_update_reviewed_drive.json` to `daily_briefing_reviewed_drive.json` so existing reviewed state is kept.

---

## Workflow summary

1. Memory and context (INDEX, 15, 14, 13, 06, 00).
2. **G Drive** — Search → fetch notes → compare to reviewed log → update log. In briefing: include **Drive** section only when there are new or updated notes; otherwise omit.
3. **Comprehensive system health check** — Run **separately** for local and for prod (SSH root@137.184.224.94; prod path /opt/rec_io_server). For each: supervisorctl status, health endpoints (main_app, trade_executor), tail key logs (trade_manager, trade_executor, main_app, kalshi_account_sync, cascading_failure_detector, one ATS, one AES) and look for ERROR/FATAL/CRITICAL or anomalies. **Report:** If nothing notable: "Local and prod: system health OK." If issues: concise rundown by environment (Local / Prod) and what needs attention.
4. **Monitor_confirmed check** — Run check with `--days 7 --append-log`. Read log for previous total. Report only if current > 0 and (current > previous or previous > 0): rise or persistence.
5. **Kalshi changelog** — Check https://docs.kalshi.com/changelog (always available). Prefer RSS at /changelog/rss.xml; if RSS fails, fetch the changelog page via web. **Derive actionable tasks** (migrate off deprecated fields, verify after breaking change, use new endpoint) and **add them to the central backlog** (13_proposed_tasks). In briefing: include **Kalshi changelog** when there are new/relevant entries and call out any tasks added to the list.
6. External news (one search; when relevant, give enough detail — 2–4 sentences or bullets). In briefing: include **News** only when relevant; otherwise omit.
7. Ongoing tasks (short paragraph from 13, 14, TODO). In briefing: include **Where we are** only when there is something to say; otherwise omit.
8. Deliver briefing in the format above (omit any section with nothing to report); end with VERIFY STATUS.
