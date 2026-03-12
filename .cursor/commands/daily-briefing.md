---
description: "Morning briefing: run steps 1–8 in order, then output the section template. No skips."
---

# Daily briefing

Execute **steps 1–8 in order**. Then output the **briefing** using the **exact section template** at the end. Do not skip steps. If a step fails, note the failure in the relevant section and continue.

---

## Step 1 — Open tasks

List files in `.cursor/plans/` (only `*.md`, exclude `README.md`). For each file, read the line that starts with `**Status:**`. Note which plans have status **draft** or **in progress**. Those are open tasks.

---

## Step 2 — Drive

From **repo root** run:

```bash
node scripts/gdrive/daily-briefing-drive-check.js
```

- If the script exits 0 and stdout is JSON with `"error": null`: check the `files` array. If any element has `"changed": true`, note "Drive: [name] has new or updated content." Otherwise note "Drive: No new or updated notes."
- If the script exits non-zero or JSON has `"error": "..."`: note "Drive: Check failed — [error message]."
- **Integrate Cursor Notes into tasks:** Get the Cursor Notes file ID from the script output (`files[0].id`) or from `.cursor/archive/pm/daily_briefing_reviewed_drive.json` (first key). Run `node scripts/gdrive/read-file.js FILE_ID` to read the full content. Parse the content for task-like items (bullets, numbered lines, clear to-dos). When filling **Where we are** and **Next to consider** in Step 8, merge these items with open plans: include a "From Cursor Notes:" subsection in Where we are (or fold the note items into the list), and add any Cursor Notes items that are not already covered by a plan into **Next to consider**. The briefing must reflect the current content of Cursor Notes, not only whether it "changed."

---

## Step 3 — Local health

From **repo root** run these in sequence:

1. `supervisorctl -c backend/supervisord.conf status` — confirm processes show RUNNING.
2. `curl -sS -o /dev/null -w "%{http_code}" http://127.0.0.1:3000/health` — expect 200.
3. `curl -sS -o /dev/null -w "%{http_code}" http://127.0.0.1:8001/health` — expect 200.
4. `tail -n 50 logs/trade_executor.out.log logs/main_app.out.log 2>/dev/null | grep -iE 'ERROR|FATAL|CRITICAL'` — note any matches or "none".

Summarize in one line: e.g. "All RUNNING, health 200, no errors in tail" or list what failed.

---

## Step 4 — Prod health

Run:

```bash
ssh -o BatchMode=yes -o ConnectTimeout=10 root@137.184.224.94 "cd /opt/rec_io_server && supervisorctl -c backend/supervisord.conf status | head -5 && curl -sS -o /dev/null -w 'main_app:%{http_code}' http://127.0.0.1:3000/health && echo '' && curl -sS -o /dev/null -w 'trade_executor:%{http_code}' http://127.0.0.1:8001/health && echo '' && (tail -n 30 logs/trade_executor.out.log logs/main_app.out.log 2>/dev/null | grep -iE 'ERROR|FATAL|CRITICAL' || echo 'no errors')"
```

Summarize: "Prod: RUNNING, 200/200, no errors" or list what failed. If SSH fails, say "Prod: SSH failed — [reason]."

---

## Step 5 — Monitor_confirmed

From **repo root** run:

```bash
python3 scripts/diagnostics/check_monitor_confirmed_failures.py --days 7 --append-log
```

Note the first line of stdout (e.g. "monitor_confirmed = FALSE ... Total: N trades"). If **N > 0**, use this later for VERIFY STATUS (choose **Investigate** unless everything else is clean).

---

## Step 6 — Kalshi changelog

Fetch the page **https://docs.kalshi.com/changelog**. Scan for entries from the last 7 days. Note: either "No new or relevant items" or one or two sentences describing any new/relevant changelog items.

---

## Step 7 — News

Run **one** web search for recent macro/crypto and Kalshi or prediction-market news (include current year/month). Note in one or two sentences any relevant headlines, or "No relevant headlines."

---

## Step 8 — Output the briefing

Reply with **exactly** the sections below, in this order. Use the section headings as written. Fill each from the steps above. Every section must appear; if there is nothing to report, use one short line (e.g. "None" or "No new items.").

---

## At a glance

[One or two sentences: overall status. Local and prod up or down; any single critical point.]

## System

- **Local:** [Summary from Step 3.]
- **Prod:** [Summary from Step 4.]
- **Monitor_confirmed:** [First line or summary from Step 5; if Total > 0, say so.]

## Drive

[Result from Step 2: new/updated notes, or "No new or updated notes.", or "Check failed — ..."]

## Kalshi Changelog

[Result from Step 6: new changelog items or "No new items."]

## News

[Result from Step 7: one or two sentences or "No relevant headlines."]

## Where we are

[Bullet list: one line per outstanding task, combining open plans (Step 1) and task-like items from Cursor Notes (Step 2). No special label is needed for Cursor Notes; treat them exactly like tasks typed directly into chat.]

## Next to consider

[Numbered list 1–5: next actions from open plans and from Cursor Notes. Include any task-like items from Cursor Notes that are not already covered by an existing plan.]

## VERIFY STATUS

[Exactly one of: **All good** | **Investigate** | **Critical** — plus one short sentence why. Use **Investigate** if monitor_confirmed Total > 0 or any non-critical health issue; **Critical** if prod is down or a critical failure.]
