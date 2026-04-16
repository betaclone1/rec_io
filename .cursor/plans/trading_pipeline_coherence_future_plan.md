# Trading pipeline coherence — future plan

## Purpose

Capture a **risk-bounded** direction for aligning live trading (market ingest → strike table → AES → ATS) with what we actually want: **coherent snapshots, honest freshness, and debuggable behavior** — without assuming a large refactor is justified until measured gain appears.

## What we are not trying to solve in one shot

- **Full rewrite** of the trade data flow “because replay diverged.” Replay divergence taught us about **snapshot cadence and semantics**, not necessarily that live is wrong.
- **AES on every strike-table insert row** in strict chronological order. High cost, duplicate-entry and partial-ladder risk, and weak mapping to how Kalshi exposes a full book.
- **Perfect backtest parity** as the primary driver of live changes unless we quantify **economic or safety** impact.

## Principles

1. **Coherent unit of truth** = one **committed** strike refresh (full replace per symbol/market), not a stream of unrelated row writes.
2. **Timestamps** on historical strike rows = **ingest/generator time**, not contract open/close. Interpret and document accordingly.
3. **Fail closed** when pipeline freshness is bad; **prefer pause** over trading on stale ladders.
4. **Observe before enlarge**: add correlation and metrics first; only then widen coupling between services.

## Phase 0 — Decide if more than Phase 0 is worth it (recommended gate)

**Goal:** Know whether “cracking the workflow open” pays for itself.

- Define **2–3 concrete pain metrics**: e.g. frequency of stale `event_ticker` vs wall clock, AES poll lag vs strike commit, unexplained entries per week, 429/backoff minutes per month.
- Set a **bar**: e.g. “We only schedule Phase 1+ if metric X exceeds threshold Y over a month or after a known incident.”

**Outcome:** Either stop here with documentation only, or proceed with evidence.

## Phase 1 — Low-risk observability (high value, minimal behavior change)

**Goal:** Make the current system **legible** when something looks wrong.

- **Correlation**: optional monotonic **generation id** (or reuse existing health timestamps) carried from watchdog rollover → strike commit → (later) AES log line.
- **Metrics / logs**: time from market `db_change` → strike table commit; rollover phase; strike row count per refresh; time since last market row update per symbol.
- **Documentation**: one short internal note on what `strike_table_master.timestamp` means vs contract windows (already clarified in discussion).

**Risk:** Low. Mostly logging and metrics.

## Phase 2 — Freshness and atomicity hardening (moderate change, contained)

**Goal:** Reduce “impossible” ladder states without changing strategy logic.

- **Strike generator**: treat success only after **full batch commit**; optional sanity checks (row band, `event_ticker` alignment with `market_kalshi_*` header, critical asks present for tradeable tier).
- **Watchdog**: explicit **rollover phase** visibility; **fail closed** on partial seed (do not leave a half event as authoritative without marking degraded).
- **Unified health story**: one clear definition of healthy for **WS → market table → strike table** so AES can gate on it consistently.

**Risk:** Medium. Requires careful rollout and alerting so we do not silent-stop trading without visibility.

## Phase 3 — AES timing alignment (optional, only if Phase 0 warrants)

**Goal:** Shrink the gap between “data landed” and “we evaluated” **without** per-row scanning.

- **Wake AES** on successful strike refresh (keep ~1s loop as backup).
- Ensure AES reads only **post-commit** snapshots (same as Phase 2).

**Risk:** Medium-low if behind feature flag and metrics prove lag was material.

## Explicit non-goals (unless requirements change)

- Rewriting ATS around global strike-row streams.
- Increasing REST/WS traffic without quota analysis.
- Mandating replay row-for-row match to live trades as a release gate (use targeted diffs and incident-driven checks instead).

## How we know we are done (for each phase)

- **Phase 0:** Dashboard or log-derived report for agreed metrics; go/no-go recorded.
- **Phase 1:** On-call can answer “which generation failed?” within minutes from logs.
- **Phase 2:** Fewer incidents of stale-event trading; health state explains maintenance windows.
- **Phase 3:** Measured reduction in AES-strike lag p95 (if that was the problem).

## Recommendation on “nervous about cracking everything open”

**Default posture:** **Phase 0 + Phase 1** always pay rent. **Phase 2** is the main “real” hardening and can be done in **small PRs** behind flags. **Phase 3** only if metrics show poll lag or missed edges matter in production.

Defer any **cross-cutting rewrite** until Phase 0 shows the pain is frequent or costly enough to justify the operational risk.
