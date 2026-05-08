# Slim `main.py` — architecture and phased migration

## Paramount constraint: do not interrupt auto trading

**Non-negotiable:** Changes must not degrade or momentarily break **auto trading** — `auto_entry_supervisor`, Redis/job fanout, `trade_manager` / `trade_executor` flows, monitor_manager–driven settings, or any path AES/ATS relies on.

Concrete guardrails for every phase:

- **No “big bang” route removals** on mutating or fanout-adjacent endpoints without proving they are UI-only and unused by supervisors or internal callers (grep + runtime checklist).
- **Proxy-first migrations:** implement heavy read logic in `read_api` (or a module), keep **identical paths on main** as thin `requests` proxies until one or more full trading days of verification — avoids breaking callers that assume port 3000.
- **Avoid touching in the same PR:** auto-entry settings writes, trigger/open-trade paths, `monitor_manager` integration, trading Redis channels/payload shapes, and tenant resolution — or isolate them behind behavior-preserving refactors only.
- **Staged deploy:** production pattern = merge mechanical extractions first; measure; then traffic shifts. Prefer **no** simultaneous deploy of frontend path changes and backend deletion.
- **Rollback-ready:** each phase should be revertible with a single revert (no multi-repo coupling).
- **Verification gate before merge when changes could affect trading plane:** local/prod smoke that includes supervisor health, a dry read of monitor auto_trade state, and (where available) a checklist that AES/ATS paths were not modified — extend your existing `MASTER_RESTART` / verify flows rather than inventing ad hoc checks.

If a change might affect auto trading and cannot be proven safe by static analysis, **defer** it or ship behind a feature flag / leave main proxy in place permanently.

---

## Where you are now

- [`backend/main.py`](backend/main.py) is still the browser-edge “kitchen sink” (~5.4k lines): static/HTML, CORS/session edge, many `read_api` proxies, plus large inline handlers (`/core`, PostgreSQL strike table, unified TTC, portfolio/bankroll, auto-entry settings, `trigger_open_trade`, admin, legacy supervisor HTTP).
- [`backend/read_api.py`](backend/read_api.py) is the other FastAPI surface (~1.5k lines).
- Project spec [.cursor/rules/07-main-app-slim.mdc](.cursor/rules/07-main-app-slim.mdc): **no fat domain in main** — thin delegates to `read_api`, services, or small modules.

## Target shape (larger-scale intention)

- **Keep on main (narrowly):** same-origin reasons (session cookies), WebSocket upgrade for `/ws/preferences` and `/ws/db_changes`, static routing, health, thin proxies.
- **Move or delegate:** SQL, trading rules, heavy aggregates — one home in `read_api` or `backend/web/*` modules imported by main; main stays wiring.

## CPU / load

- File splits alone do not save CPU; savings come from deduplicating work, moving hot reads to a scalable read path, and removing dead legacy polishers.
- Measure top paths (trade monitor, dashboard) before/after each phase.

## Database migration impact

- **Expected for this plan:** none.
- This plan is architecture/refactor/surface-shaping (route slimming, proxy delegation, module extraction), not schema evolution.
- A DB migration is only in scope if we explicitly decide to add/alter tables, columns, constraints, indexes, or persisted payload formats. That would be a separate, explicit migration sub-plan with rollback steps.

## Phased roadmap

**Phase 0 — Inventory and guardrails**

- Route manifest: `static` | `proxy_read_api` | `inline_sql` | `websocket` | `admin` | `legacy_external_http`, with an explicit column **“touches trading plane?”** (Y/N/unknown — default unknown = treat as sacred until proven).
- Frontend/mobile fetch cross-check.

**Phase 1 — Mechanical thin delegates (low risk)**

- Shared `read_api` proxy helper module; optional `APIRouter` includes; **no behavior change**.

**Phase 2 — Hot reads to `read_api` (proxy from main)**

- Candidates: `/core`, strike table, unified TTC, watchlist, live symbol snapshots, momentum — **only after** manifest marks them read-only and non-trading-plane.

**Phase 3 — Writes policy**

- `trigger_open_trade`, bankroll, subaccounts, monitor toggles: thin forward vs read_api consolidation — **high scrutiny**; smallest diffs; proxy-first.

**Phase 4 — Admin + realtime module isolation**

- Blast-radius reduction; optional separate process later.

**Phase 5 — Ops / scale**

- Multiple read_api workers if read-bound; document cookie vs direct read_api rules.

## Success criteria

- `main.py` slim / wiring-only per 07.
- **Auto trading unchanged** — no regressions in AES/ATS/executor/manager behavior attributable to this effort.
- Measured improvement or justified tradeoff on hot paths.
- No duplicate strike/core/TTC implementations across services without deprecation path.

## Implementation todos

- Build route manifest + **trading-plane flags** + frontend fetch cross-check
- Extract shared read_api proxy helpers + optional APIRouter wiring
- Migrate hot reads to read_api with **main proxy preserved**
- Writes: explicit policy PRs with **trading verification gate**
- Isolate Redis WS fan-in + admin modules
- Metrics on top routes before/after phases
