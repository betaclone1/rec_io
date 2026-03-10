# PM proposed tasks / next steps

When the PM proposes a short list of starting tasks or next steps for the project, record that list here so the CEO and future sessions can recall it. Update this doc whenever such a list is proposed; archive or trim when items are done or superseded.

**Central backlog ("our list"):** This doc is the **central list of suggested tasks**, ordered by priority and roughly tagged as **short / medium / long term**. When the user asks for the list, "what's next?", "what should we work on today?", or to "go back to our list," produce one **comprehensive** ranked list by: (1) merging **this doc** (ongoing + G Drive daily list section), (2) **docs/changelog/TODO.md** open items, and (3) **current G Drive "Cursor Notes"** content (fetch via `node scripts/gdrive/read-file.js <Cursor Notes file_id>`; file_id in `daily_briefing_reviewed_drive.json`). Dedupe and prioritize: near-term, user-facing work first; then stability/observability; then medium/long-term initiatives (Redis, major frontends, etc.). Mark items inline as `[S]`, `[M]`, or `[L]` when helpful.

**Maintenance rules:** When we complete a task, mark it done here (and in TODO.md if applicable). When new tasks arise in chat, daily briefing, or Drive notes, **fold them into this doc** (section below) and adjust ordering so this remains the single source of truth for priorities.

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

1. ~~**account_history backfill on prod**~~ — **Done.** Fetchers and _backfill_account_history_vendor_rail added; backfill script fixed (server-agnostic); ran on prod: 9/12 rows have kalshi_id/vendor/rail; 3 legacy rows remain NULL (optional to retry if API ever matches).

2. ~~**main_app lifespan (non-critical)**~~ — **Done.** `backend/main.py` now uses a FastAPI `lifespan` context manager (with startup/shutdown logging) instead of deprecated `@app.on_event` handlers; DeprecationWarning cleared and verified in logs after restart.

**From 2026-03-07 (still open):**

5. **Env conventions (opportunistic)** — When touching a file for other work, if it uses POSTGRES_* or its own DB config, switch to get_postgresql_connection() / get_database_config(). No dedicated full pass unless it becomes a bigger problem; then flag for full pass.
6. **Auto_entry_supervisor consolidation** — Single process, multi-monitor loop (per TODO/open items). Simplifies deployment and monitoring.
7. **System-wide logging audit** — Full initiative: (1) inventory every supervisor script + key one-offs — what each logs and where; (2) script-by-script cleanup: remove unnecessary writes, consolidate, standardize on logging→stdout; (3) fix log rotation (supervisor maxbytes/backups; no unbounded growth); (4) later: consolidated MASTER log for 30k view + drill-down. See 16_LOGGING_AUDIT_INITIATIVE.

7. **Redis platform initiative (future, major)** — Full-scale Redis for pub/sub and optional cache to replace internal HTTP broadcast mesh and slim main.py. Not scheduled. Plan drafted in REDIS_PLATFORM_INITIATIVE.md: current state, vision, scope (main, trade_manager, ATS, AES, monitor_manager, kalshi_account_sync, frontend WS), phases (research/pilot/migration/main slim-down), risks, agent implications (possible @infra/@redis or extend @db). When we set a timeline: refine phases, consider onboarding Redis/infra agent.

**G Drive — Cursor Notes (daily list, folded in 2026-03-10):**

Source: REC_IO / Cursor — "Cursor Notes" on Google Drive. When presenting "our list" or "next tasks," merge this with the ongoing list above and with docs/changelog/TODO.md open items; prioritize and present one comprehensive list.

- **MTB / account balance & dashboard** — Update account balance DB table to track Master Trading Bankroll (MTB); work with front-end to display MTB instead of bankroll; live switch performance displays to reflect MTB when that display is selected.
- **Mobile dashboard auto refresh** — Examine mobile dashboard auto refresh; behavior is inconsistent and sometimes requires hard reloads.
- **Account history strategy filters** — Update strategy list filters in account history front end to read full strategy list values and enable filtering by all strategies listed.
- **Front-end rule: mobile parity** — Rule for front-end dev should include check if revs should be applied to mobile as well as desktop.
- **Remote notifications** — Explore mechanisms for system agents to remotely notify CEO when necessary (SMS, email, iOS notifications); MCP integrations; open to suggestions.
- **Candlestick charting (major frontend)** — Design candlestick charting system using internally collected OHLC symbol price data; Trading View–style charts; overlay our data; integrate into trade history UI and future backtesting.
- **Kalshi market sync (major)** — Migrate from REST brute-force market polling to WebSocket order book subscription/delta updates; new system for WS-updated order books per strike market; feed into existing market/strike table infra; requires parallel testing with existing infrastructure.
- ~~**Daily-briefing immediately actionable**~~ — **Done.** Skill updated so clearly actionable findings during briefing are implemented before reporting.
- **PM/agent workflow review** — Review PM/agent workflow; ensure we're building it right with no bad practices; aim for a bulletproof framework portable to other projects; are there better practices?

**Done (archived):** 1–4 (Kalshi fixed-point, bugs, DB audit local, Kalshi account history). G Drive note items (2026-03-08): /prepare-update, Frontend agent, Backend master (doc only), /daily-briefing, MCP investigation, OpSec audit+upgrade, delegate/train agents — all addressed. **2026-03-08:** account_history backfill — added fetch_v1_deposits_page, fetch_v1_withdrawals_page, _backfill_account_history_vendor_rail, _refresh_transfer_from_to_from_account_history to kalshi_account_sync_ws; backfill script runs on any server; ran on prod, 9/12 rows filled.

---

*Last updated: 2026-03-10.*
