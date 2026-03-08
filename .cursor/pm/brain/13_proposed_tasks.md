# PM proposed tasks / next steps

When the PM proposes a short list of starting tasks or next steps for the project, record that list here so the CEO and future sessions can recall it. Update this doc whenever such a list is proposed; archive or trim when items are done or superseded.

---

## G Drive note (2026-03-08) — "Things we can work on today"

Source: REC_IO / Cursor — "Cursor Notes" on Google Drive.

1. **/prepare-update command** — When ready to push a commit. Integrate with @updater. Steps: (a) Check all current iterations of scripts running without errors. (b) Run an audit so changes are server-agnostic; flag issues before push. (c) Check changes/staged against changelog; update changelog accordingly. (d) Call @db / DB manager so all DB changes are in docs/scripts and called out in changelog. (e) When deemed ready: craft concise commit message and alert CEO that update is ready for publishing.
2. **Onboard Frontend agent** — Head of front-end development and maintenance. Expert in HTML, JS, CSS, mobile; immerse in our frontend UI; expert in UI/UX development. Add rule + AGENTS.md + ORG_CHART.
3. **Backend master agent (optional)** — If prudent: agent that all agents touching backend scripts and DB operations report to.
4. **/daily-briefing command** — Run first thing each morning. Flow: review latest memory + chat logs; verify system running; review recent script logs for abnormal behavior/errors; prod server health; external search for relevant news (financial/crypto); determine status of ongoing tasks; consolidate and suggest action items by priority; deliver daily briefing (conversational but itemized). Refine over time; keystone of daily workflow.
5. **MCP connections** — Investigate list of MCP connections that could be useful for the team.
6. **OpSec audit and security upgrade** — Audit current Operational Security behavior; frame full security upgrade process. Consider opsec agent (head of security, consulted on security-related issues).
7. **Use agent org efficiently** — Delegate when possible; update agent persistent context in docs; train agents.

---

## Current proposed list (ongoing)

**From 2026-03-08 (open):**

1. **account_history backfill on prod** — Migration added kalshi_id, vendor, rail; prod has 12 rows, all NULL in those columns. Backfill script broken (imports fetch_v1_deposits_page, fetch_v1_withdrawals_page, _backfill_account_history_vendor_rail from kalshi_account_sync_ws; those don’t exist). Fix: add the missing fetchers and backfill helper to sync module (or implement backfill using current API), then run backfill once on prod. We spent hours on this yesterday.

2. **main_app lifespan (non-critical)** — Replace @app.on_event("startup")/("shutdown") in backend/main.py with FastAPI lifespan context manager to clear DeprecationWarning. Do when touching that file or before FastAPI upgrade.

**From 2026-03-07 (still open):**

5. **Env conventions** — Normalize DB_* / REC_DB_* / POSTGRES_* usage across codebase so scripts and services use one pattern (e.g. load .env, map REC_DB_*→DB_*, use database.py). Reduces bugs and confusion.
6. **Auto_entry_supervisor consolidation** — Single process, multi-monitor loop (per TODO/open items). Simplifies deployment and monitoring.
7. **System-wide logging audit** — Identify high-volume log sources; define policy (INFO vs DEBUG); trim verbose per-tick/per-request output; keep operational/debug signal. Improves I/O and disk.

**Done (archived):** 1–4 (Kalshi fixed-point, bugs, DB audit local, Kalshi account history). G Drive note items (2026-03-08): /prepare-update, Frontend agent, Backend master (doc only), /daily-briefing, MCP investigation, OpSec audit+upgrade, delegate/train agents — all addressed. **2026-03-08:** account_history backfill — added fetch_v1_deposits_page, fetch_v1_withdrawals_page, _backfill_account_history_vendor_rail, _refresh_transfer_from_to_from_account_history to kalshi_account_sync_ws; backfill script runs on any server; ran on prod, 9/12 rows filled.

---

*Last updated: 2026-03-08.*
