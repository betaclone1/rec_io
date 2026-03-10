# /daily-briefing command

**Defined in:** `.cursor/commands/daily-briefing.md` and `.cursor/skills/daily-briefing/SKILL.md`.

Morning routine: refresh context, check Drive for new notes, verify system, skim news, then deliver a **concise, conversational** briefing. High-level first, then drill down to a short list of next tasks to consider.

---

## Briefing format (for human eyes)

Format the output so it is **easy to read and scan**: use clear section headings, blank lines between sections, and bullets for lists. Be concise but not cramped — when something is worth mentioning (e.g. news items, a new Drive note, a real log issue), give enough detail to be useful.

**Structure** — Output in this order, with a **heading for each section** (e.g. `## At a glance`, `## System`, `## Drive`, etc.) and a blank line after each heading before the content.

1. **At a glance** — One or two sentences: how things are overall (system, prod, Drive new or not, any standout). Optional one-line status if helpful.

2. **System** — Health and logs in a short, readable block. Use bullets if there are multiple points (e.g. main_app 200, trade_executor 200, supervisor all RUNNING). If there are log issues worth noting, give a sentence or two of detail; if all quiet, say so in one line.

3. **Drive** — New or updated notes: if any, summarize in a few lines or bullets so the reader knows what's new. If nothing new, one line ("Nothing new since last run."). Mention if you updated the reviewed log.

4. **News** — **When there are items worth mentioning:** give a little more than one sentence — 2–4 sentences or a few bullets (what happened, why it might matter). **When nothing is relevant:** skip the section or move on; do not add filler like "Nothing that affects us" or "Nothing else in the search."

5. **Where we are** — Short paragraph on ongoing work and blockers. Bullets are fine if there are several threads.

6. **Next to consider** — Ranked list (bullets or numbers), high-level to tactical. One line per item; easy to scan.

7. **VERIFY STATUS** — Single line at the end: All good / Investigate / Critical.

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
2. **G Drive** — Search → fetch notes → compare to reviewed log → surface new/updated in briefing → update log.
3. **Comprehensive system health check** — Run **separately** for local and for prod (SSH root@137.184.224.94; prod path /opt/rec_io_server). For each: supervisorctl status, health endpoints (main_app, trade_executor), tail key logs (trade_manager, trade_executor, main_app, kalshi_account_sync, cascading_failure_detector, one ATS, one AES) and look for ERROR/FATAL/CRITICAL or anomalies. **Report:** If nothing notable: "Local and prod: system health OK." If issues: concise rundown by environment (Local / Prod) and what needs attention.
4. **Monitor_confirmed check** — Run check with `--days 7 --append-log`. Read log for previous total. Report only if current > 0 and (current > previous or previous > 0): rise or persistence.
5. External news (one search; when relevant, give enough detail to be useful — 2–4 sentences or a few bullets).
6. Ongoing tasks (short paragraph from 13, 14, TODO).
7. Deliver briefing in the format above; end with VERIFY STATUS.
