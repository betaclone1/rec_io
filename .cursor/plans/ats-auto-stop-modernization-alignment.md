# ATS / auto-stop modernization — design alignment (no implementation)

**Goal:** Align GPT product architecture with the as-built repo before any build.  
**Status:** Stage 0 alignment **complete**. Design only. Do **not** open or execute a Stage 1 implementation plan from this chat/task.  
**Authority inputs:** `docs/TRADE_LIFECYCLE_AND_AUTO_STOP_CURRENT.md`, `docs/ORDERBOOK_HOT_CACHE.md`, `docs/KALSHI_MARKET_INGEST.md`, `docs/TRADING_REDIS_COMMS.md`, `backend/core/market_watchdog/venues/kalshi/ws_ingest.py`, `backend/active_trade_supervisor.py`, `backend/trade_manager.py`, `backend/trade_executor.py`.  
**Non-goals for this document:** code changes, schema migrations, deploy, Stage 1 planning or build.

---

## 0. Verdict (short)

**Yes — a single Kalshi market-data owner fanning normalized L2 (+ public trades, once added) is the right primary *market* decision driver for liquidation risk.** Repo already matches: `market_watchdog_ws` owns the WS; ATS has no Kalshi subscriber.

**Locked product focus:** **High Water Scalp (HWS) stop protection** is the first authority target. New work lands in a system-scoped **`position_risk_engine`** sidecar. Legacy **`active_trade_supervisor`** retains money authority through dual-run. Hourly is out of Stages 1–5. Flip-sell is deferred. Probability stops stay on legacy ATS; in the new plane they are secondary/shadow only until empirical promotion.

**Repo caveats (still true):**

1. Public trades are **not** on the WS yet — Stage 2 adds them.
2. Today’s ATS marks are strike-ladder **touch** + model probability, not actual-size LVWAP — new risk metrics plane required.
3. Legacy ATS still uses ~1s failsafe poll and couples `auto_trade` / pipeline gate to exits — new plane must not inherit those couplings for protection authority.
4. TM / TE / account-sync / lifecycle settlement ownership preserved; new path never bypasses them.

---

## 1. Locked decisions (GPT §7 — incorporated)

| # | Decision |
|---|----------|
| 1 | **Probability stops:** preserve legacy routes during migration. New 15m protection plane: **secondary/shadow only** initially — not v1 book/tape authority; promote only after empirical comparison. |
| 2 | **Three-way semantics confirmed.** Trigger → intent. Desired execution threshold → orderly IOC/limit liquidation (HWS **profit GTC remains separate**). Disaster floor → abandon patience; most aggressive **venue-supported IOC limit/sweep within explicit bounds**. **No synthetic market order. No promise of 90c fill.** Coordinator may reprice only under **bounded, versioned policy**. Exact numeric values = **calibration outputs**, not architecture constants. |
| 3 | Trades **UNKNOWN** + healthy-sequenced L2: both **LVWAP and L2-cliff** may fire **only** under separately validated, **explicitly enabled** book-only policy. Trade-derived clauses stay UNKNOWN. |
| 4 | **Flip-sell deferred** — not coupled to first protection cutover. |
| 5 | Require **both** full-fidelity **paper** simulation **and** **live shadow**. Paper models actual depth, partial fills, cancel/late-fill races, latency. Live shadow measures real triggers without money authority. |
| 6 | **Durable ordered Redis Stream/log required by Stage 2** for audit/replay/gaps/dual-run. Latest key + pubsub may **bootstrap Stage 1 observation only** — never final sole event contract. |
| 7 | **New path:** TM owns cancel/exit coordination state; risk plane sends **idempotent intent**; **TE alone** submits/cancels. ATS→TE HTTP remains **only** on untouched **legacy** authority during dual-run; **removed from new path**. |
| 8 | Lifecycle publish wiring = **separate corrective track**. Does **not** block Stage 1–3 observation. Unresolved close/fill/finalization correctness **blocks money-authority cutover**. |
| 9 | Prefer system-scoped sidecar **`position_risk_engine`** (or similarly explicit) with per-tenant/per-position actors and policies. **Do not** duplicate market reconstruction in each tenant ATS. Keep legacy ATS during migration; revisit final naming only after authority moves. |
| 10 | **Do not lock persistence X.** Stage 1 replays candidate grid **0 / 50 / 100 / 250 / 500 / 1000 ms** plus **minimum distinct valid book generations** against winners and losses. Slow breach = **wall time + distinct valid book generations** — never raw loop/tick count. Depth-deficit integral = analysis feature candidate. |
| 11 | **Flash success = detection + intent latency, not fill price.** Targets: applied-book→decision **p95 ≤15ms / p99 ≤30ms**; decision→intent enqueue **p95 ≤10ms**; plus accurate executable-coverage and realized-slippage report. Exchange/network cannot guarantee 90c. |
| 12 | Persistence basis: **wall-clock ms + distinct valid book generations**. Depth-weighted time/integral = analysis candidate, not initial hard dependency. |
| 13 | **Hourly explicitly out** of Stages 1–5. Scope = handful of **15m** markets/tickers with open positions. |
| 14 | **HWS = first product focus.** Keep profit-taking GTC behavior; migrate HWS **stop** protection / cancel-liquidate in **Stage 4**. Expiration Scalp may share shadow metrics/fixtures. Momentum and other routers remain **legacy** until separate validation. |
| 15 | New process/module name **`position_risk_engine`**; retain **`active_trade_supervisor`** for legacy responsibilities during dual-run. |

### Stage 1 fixture correction (locked)

Because HWS is the first product focus, Stage 1 fixtures and feature timelines **must** include today’s **HWS gradual and flash losses**. Coverage/lease accounting must cover **every open HWS position** across **all** trading tenants (system-scoped observe; a single tenant may be a **review filter** only — never a coverage blind spot). Expiration Scalp remains a **secondary** shared-metrics fixture, not the initial authority target.

**Canonical loss trade IDs (locked) — provenance via monitor 10058 CSV, not local DB id equality:**

| Role | Trade ID | Notes |
|------|----------|-------|
| Gradual loss | **59597** | CSV ticker `KXBTC15M-26SEP070230-30`; Stage 1 L2 **RESOLVED** (package sha in manifest); public tape **UNKNOWN** |
| Flash loss | **59721** | CSV ticker `KXBTC15M-26SEP070800-00`; L2 **RESOLVED**; tape **UNKNOWN** |
| Supplemental | **59863** | CSV ticker `KXBTC15M-26SEP071330-30`; supplemental L2; tape UNKNOWN |
| Winning controls | **59860, 59847, 59838, 59835** | Same CSV + hashed local packages |
| Synthetic (not trade IDs) | `gradual_collapse_reference_v1`, `flash_collapse_reference_v1` | Documented shapes only |

See `tests/fixtures/position_risk/manifest.json` and `docs/POSITION_RISK_ENGINE_STAGE1.md`. Stage 1 local observe implemented; still no money authority.

---

## 2. Repo reality vs locked direction

### 2.1 What already matches

| Locked direction | Repo today |
|------------------|------------|
| One Kalshi market-data owner | `market_watchdog_ws` (15m + hourly processes); OB seq/gap/resync exist |
| No parallel risk Kalshi WS | ATS has no Kalshi WS; wakes on `live_state:updated`, then pulls marks |
| Hot L2 in Redis | `trade_monitor:orderbook_levels:v1:{ticker}` + pubsub hints |
| TM canonical / TE executor / account-sync fills | As in lifecycle doc |
| Handful of 15m markets | Fits hot-ticker / open-position enrollment |

### 2.2 Gaps to close (by stage)

| Gap | When |
|-----|------|
| No public trade channel on WS | Stage 2 |
| No durable ordered risk event stream | Stage 2 (Stage 1 may bootstrap key+pubsub) |
| No exact LVWAP / cliff / coverage features | Stage 1 shadow |
| No `position_risk_engine` / PROTECTED lease | Stage 1 |
| No three-way stop policy machine | Stage 3–4 (shadow compare in 1) |
| Legacy `auto_trade` gates ATS exits; pipeline gate can block closes | Stage 3+ for new plane; legacy unchanged until cutover |
| ATS→TE HTTP cancel on HWS flatten | Legacy only; new path TM-coordinated (Stage 4) |
| Lifecycle publish wiring incomplete vs docs | Parallel track; blocks money cutover only |

### 2.3 Mark path today (≠ LVWAP)

```
Kalshi WS (watchdog)
  → Redis OB levels + live_state market
  → strike_table_generator (OB touch → yes/no ask)
  → live_state strike_ladder + pubsub
  → ATS wake → touch/probability marks → legacy auto-stop
```

**New plane:** `position_risk_engine` consumes **hot OB (+ later public trades / durable stream)** for liquidation metrics. STG remains for AES entry / UI / legacy probability. Market reconstruction is **not** duplicated per tenant.

---

## 3. Target architecture (locked shape)

### 3.1 Planes

| Plane | Owner | Must not |
|-------|-------|----------|
| **Market data** | `market_watchdog_ws` | Second Kalshi WS in PRE or ATS |
| **Derived ladder / AES** | STG + AES | Own liquidation authority |
| **Risk metrics + actors** | **`position_risk_engine`** (system-scoped sidecar; per-tenant/per-position actors) | Place/cancel Kalshi orders; write fills |
| **Exit coordination state** | **TM** | Ignore idempotent intents / working-order truth |
| **Execution** | **TE only** | Accept cancel/submit from PRE directly |
| **Fill authority** | account-sync → TM | Invent fill qty/price |
| **Settlement** | lifecycle consumer + TM finalize | Confirm W/L from spot |
| **Legacy protection** | `active_trade_supervisor` | Be removed before dual-run complete |
| **Health/audit** | Independent watchdog + metrics | Share fate with risk eval only |

### 3.2 Candidate lifecycle (overlay; TM remains SoR)

```
ENROLLING → PROTECTED → EXIT_INTENT → CANCEL_PENDING → LIQUIDATING
    → PARTIALLY_LIQUIDATED ⇄ LIQUIDATING
    → CLOSED
Recovery: UNKNOWN_DATA | RESYNCING | DEGRADED | ORPHAN_RECONCILE
         | DEGRADED_BOOK_ONLY (explicit policy only)
```

HWS: CANCEL_PENDING waits cancel ack / known working qty; late GTC fills adjust remaining via account-sync / `close_filled_count`; duplicate intents suppressed by `(trade_id, intent_gen)` (or equivalent).

### 3.3 Three-way stop semantics

| Concept | Meaning | Action class |
|---------|---------|--------------|
| **Trigger** | LVWAP persistence breach or L2 cliff (policy) | Create EXIT_INTENT |
| **Desired execution threshold** | Orderly liquidation guide | IOC/limit attempt; **HWS profit GTC stays separate** |
| **Disaster floor** | Abandon patience | Aggressive venue IOC limit/sweep within **explicit bounds** |

Exact levels and aggression = **versioned calibration**, not hardcoded architecture. No synthetic market orders. No 90c fill guarantee.

### 3.4 Signal classes in the new plane

| Signal | v1 role |
|--------|---------|
| L2 LVWAP / coverage / cliff | Primary protection candidates (HWS focus) |
| Public tape features | Primary when present; else UNKNOWN |
| Probability / model | **Shadow/secondary only** until promotion |
| Flip-sell | **Out of scope** for first cutover |
| Momentum routers | Legacy ATS only |
| Expiration Scalp | Shared shadow metrics/fixtures; not first authority |

### 3.5 Data quality and degraded modes (locked)

| Condition | Behavior |
|-----------|----------|
| Invalid / gapped L2 | **Do not invent a stop.** Mark DEGRADED/RESYNCING; alarm; preserve existing HWS resting **profit** GTC; dual-run keeps **legacy authority** if its inputs independently healthy. |
| Quiet but healthy market | Validity from **WS heartbeat / sequence health**, not “no book changes.” |
| Public trades UNKNOWN | Trade clauses UNKNOWN. Book-only LVWAP+cliff only if **validated + explicitly enabled**. |
| Redis/stream lag / loss | Watchdog detects; no invented marks; durable intent/retry when applicable. |
| PRE restart | Re-enroll from TM open/closing + working orders; leases recreate. |
| TM/TE unavailable | **Durable intent / retry / reconcile + critical alarm.** Never bypass ownership. Never PRE→TE submit/cancel on new path. |
| Final authority + missing data | **No silent market-exit.** Operator-approved emergency policy defined **after Stage 1 evidence** — not assumed now. |

---

## 4. Staged delivery (updated)

### Stage 0 — Decision lock

**Status:** **complete.** All product/architecture follow-ups closed. Stop here — do not open Stage 1 from this alignment task.

### Stage 1 — Observe-only (smallest safe first slice; **HWS-first**) — *not started*

**Scope:** 15m tickers with open **HWS** positions on **every trading tenant**; system-scoped `position_risk_engine` shadow process/module (or precursor). Per-tenant views are filters for review only.

**Work (later — when a separate Stage 1 plan is explicitly opened):**

- First planning discovery: freeze cycle-package / L2 / public-tape paths + hashes for trades **59597** (gradual), **59721** (flash), **winning controls**, and supplemental **59863** if usable.
- Enroll every open HWS position (all tenants); PROTECTED lease + heartbeat vs TM open set.
- Shadow LVWAP / coverage / cliff / (optional) depth-deficit integral on hot OB.
- Instrument full chain timestamps (receive→apply→evaluate→intent *shadow*→… baselines).
- Replay **HWS gradual + flash loss** fixtures; ES as secondary shared fixture.
- Persistence **grid** replay: 0/50/100/250/500/1000ms + min distinct valid book generations; winners and losses.
- Probability signals recorded as **shadow comparison only**, not authority.
- Bootstrap transport: key + pubsub OK; design for Stage 2 stream cutover.
- Full-fidelity **paper** sim harness for depth/partials/cancel races/latency (fixture + ongoing paper positions as available).
- Live shadow on real opens (no money authority).

**Exit criteria (when Stage 1 later runs):**

- [ ] Lease/coverage for **every** open HWS position on **every** trading tenant; TM open→PROTECTED measured vs draft SLOs.
- [ ] Quiet-healthy vs broken-transport distinguished via WS/seq health.
- [ ] Fixture paths/hashes frozen; HWS gradual **59597** + flash **59721** + winning controls reproduce; **59863** documented as supplemental.
- [ ] Persistence grid results recorded (no X locked).
- [ ] Flash latency targets measured (applied-book→decision; decision→intent enqueue).
- [ ] Zero change to live `close_method` distribution / legacy authority.

### Stage 2 — Public trades + durable ordered risk stream

Add public `trade` on same watchdog connection; durable Redis Stream/log as sole event contract for risk consumers; quality bits; REST = gap repair/history only.

**Exit:** Trades with UNKNOWN-on-gap; stream is audit/replay source; Stage 1 bootstrap not sole path.

### Stage 3 — Protection independence + dual-run (still legacy money authority)

New-plane protection independent of AES `auto_trade` / STG pipeline gate when OB valid. Dual-run: PRE EXIT_INTENT logs (+ paper full path); **legacy ATS authoritative** on live. Probability remains shadow. Flip-sell still off.

**Exit:** Would-have vs legacy comparison on HWS live + fixtures; false-positive budget agreed from data.

### Stage 4 — HWS exit coordinator (TM-owned; TE-only I/O)

Idempotent intents; cancel-ack before remainder liquidate; late GTC / partial recompute; desired-threshold vs disaster-floor tactics under versioned policy; HWS profit GTC preserved as separate behavior.

**Exit:** HWS cancel/late-fill/duplicate tests green; no PRE→TE direct path; TM external statuses still `closing`/`closed`.

### Stage 5 — Money-authority cutover + rollback

Flag per tenant/monitor (or equivalent); legacy standby. Lifecycle close/fill/finalization correctness must be **resolved** before this stage. Rollback = flag off → legacy ATS; PRE shadow/leases may remain.

**Exit:** Cutover SLOs held; flash policy documented as coverage/slippage not fill guarantee; emergency missing-data policy operator-approved.

---

## 5. Smallest safe first slice

**Stage 1 HWS observe (later):** all-tenant leases + shadow book features + fixture grid (59597 / 59721 / winners; 59863 supplemental) + paper fidelity harness + live shadow — **no new closes, no flip-sell, no PRE→TE, no persistence X lock.**

---

## 6. SLOs (cutover objectives — measure in Stage 1; not current-performance claims)

### 6.1 Continuous protection / health

| Signal | Objective |
|--------|-----------|
| TM open → actor PROTECTED | p95 ≤250ms; p99 ≤500ms; **critical alarm at 1s** |
| Actor heartbeat | ~250ms |
| Independent watchdog detection | ≤750ms; **page/critical by 2s** |
| Redis consumer lag (when stream exists) | p95 ≤25ms; p99 ≤100ms; critical >500ms |
| Book / transport validity | WS connection heartbeat + sequence health — **not** “no deltas” |

### 6.2 Flash / decision path (HWS cliff)

| Span | Objective |
|------|-----------|
| Applied-book → decision | p95 ≤15ms; p99 ≤30ms |
| Decision → intent enqueue | p95 ≤10ms |
| Executable coverage + realized slippage | Report required; **not** a 90c fill SLO |

### 6.3 Full chain (record always; set final authority bars from baselines)

`receive → book apply → risk eval → exit intent → TM → TE → ack/fill`

Also retain OB apply→Redis (`ts_ms`→`redis_written_ms`) from existing probes. Cancel-ack latency critical for HWS Stage 4; set bars from Stage 1–4 evidence.

### 6.4 Degraded (summary)

Invalid/gapped L2 → DEGRADED/RESYNCING, alarm, preserve HWS profit GTC, no invented stop; dual-run defers to healthy legacy. TM/TE down → durable intent/retry/reconcile + critical alarm, never bypass. Final missing-data emergency policy **after** Stage 1 evidence.

---

## 7. Resolved questions archive (former §7)

Answers recorded in §1. Open items only in §8.

**Non-blocking notes (do not stall Stage 1):**

- Exact disaster-floor IOC bound table = calibration artifact for Stage 4.
- Probability promotion criteria = post Stage 3 empirics.
- Final process naming after authority moves.
- Depth-deficit integral = analysis-only in Stage 1.
- Operator emergency policy for final-authority missing data = post Stage 1.

---

## 8. Follow-ups — closed

### 8.1 Disagreement with GPT

**None material.**

**Design tension to track (not a disagreement):** system-scoped PRE vs today’s **per-tenant** TM/TE/ATS supervisord model — enrollment and credentials must fan in across `users_*` without reconstructing books per tenant. Resolve only when a Stage 1 implementation plan is explicitly opened.

### 8.2 Former blocking follow-ups — answered

| # | Answer |
|---|--------|
| Tenant scope | Stage 1 is observe-only / system-scoped: **instrument every tenant’s open HWS positions from day one**. One tenant may be a **review filter** only — **never** a coverage blind spot. |
| Canonical fixtures | Gradual **59597**; flash **59721**; supplemental **59863** (incomplete data). **Include winning controls.** Freeze exact reproducible cycle-package / L2 / public-tape **paths and hashes** as the **first Stage 1 planning discovery task** (when Stage 1 is later opened — not part of this Stage 0 close). |

**No remaining blocking product questions for Stage 0.**

---

## 9. Dual-run and rollback

| Mode | Legacy ATS | `position_risk_engine` | Live money |
|------|------------|------------------------|------------|
| Stage 1 Observe | Authority | Shadow features + leases + paper harness | Legacy only |
| Stage 3 Dual | Authority | Intent logs + full paper path | Legacy only |
| Stage 5 Primary | Standby | Authority when flag on | New (HWS protection) |
| Rollback | Instant re-enable | Shadow/leases may remain | Legacy |

New path never uses ATS→TE HTTP. Flag-scoped rollback should not require market_watchdog redeploy.

---

## 10. Completion criteria for this alignment task

- [x] As-built + market-data path inspected  
- [x] Direction evaluated against repo  
- [x] Assumptions challenged  
- [x] Staged architecture + smallest slice proposed  
- [x] GPT §7 answers incorporated  
- [x] HWS-first Stage 1 correction applied  
- [x] SLO + degraded-mode refinements applied  
- [x] Blocking follow-ups (§8.2) answered  
- [x] Stage 0 alignment marked **complete**  
- [x] Explicit stop: **do not** open or execute Stage 1 from this task  

---

## 11. Hand-off

**Stage 0 closed.** Next work requires a **separate, explicit** request to open a Stage 1 implementation plan (fixture path/hash freeze → HWS observe/lease/shadow/paper harness). Until then: no Stage 1 plan file, no code, no discovery execution.

**Related:** `docs/TRADE_LIFECYCLE_AND_AUTO_STOP_CURRENT.md`, `docs/ORDERBOOK_HOT_CACHE.md`, this file.
