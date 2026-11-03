# Orderbook latency v2 (crypto UT) — from scratch

**Goal:** Crypto monitors always see the freshest OB we can deliver; rail-cross → place → exchange with minimum controllable latency; cycle/day rollovers with no feed stalls.

**Baseline:** `db278cb9` (prod rollback). Branch: `ver4/ob-latency-v2`.

**Status:** in progress — Phase 1 code on branch (not deployed)

**Phase 1 landed (local):** UT stream fire (`e016ab22`), always-hot crypto + inline hints (`13451803`), stamp clamp (`ee6e927e`). Dual Kalshi OB socket **not** included.

**Deploy:** local + tests only until owner explicitly says deploy.

---

## Lessons (non-negotiable)

| Failed design | Outcome | Rule going forward |
|---------------|---------|-------------------|
| 2nd Kalshi OB socket on isolated OS thread + own asyncio loop | Cross-loop `asyncio.Lock` wedged ingest; fills collapsed | **Never** second event loop / OS thread for Kalshi OB |
| Same-loop dual OB socket + handoff | Still high CPU / feed instability under load | **No dual Kalshi OB socket** in v2 until single-socket path is exhausted and proven |
| Trusting raw Kalshi `sending_ts` | Fake multi-second ages | Clamp / prefer `t_ws_recv` for ages |
| Attribute lag to Kalshi | Idle probe ~7–10ms; shared path added ~250ms p50 | Measure with `(ticker, sending_ts_ms)` A/B |

---

## Controllable latency map (baseline)

```
Kalshi WS → apply (master.lock) → [50ms coalesce if not hot] → Redis SET+PUBLISH
  → UT hot subscriber GET → wake → full _tick (DB+REST+housekeeping)
  → Redis GET again → qualify → sign+POST
```

Biggest controllable gaps:
1. Crypto books often **not hot** → ~50ms coalesce
2. Shared-socket / event-loop queueing under full universe
3. Full `_tick` on every OB wake (DB/REST before place)
4. Double Redis read (subscriber + qualify)

---

## Phased plan

### Phase 1 — single socket, cut agent + flush waste (do first)

1. **Armed crypto → always-hot flush** via `orderbook_hot_publish_registry` (UT-armed / watch / allowlist). No second WS.
2. **UT stream fire path:** OB hint → cheap in-memory/cached touch → place once; timer loop owns DB/REST/fills/rollover housekeeping.
3. **Inline book on hint or reuse subscriber snapshot** so fire path skips a second Redis GET when safe.
4. **Stamp hygiene:** clamp stale venue/sending vs recv (log truth only).
5. **Rollover soak tests:** ±12s around quarter; no prolonged miss; no channel-wide resync storm from our changes.

### Phase 2 — ingest loop hygiene (only if Phase 1 measured gap remains)

1. Reduce lock hold time on apply path; keep Redis flush on `to_thread`.
2. Narrow channel resync to affected tickers where Kalshi semantics allow.
3. Shed non-essential sync work off OB apply (UI prebuild, etc.) carefully.

### Phase 3 — dual socket (explicit gate; default off)

Only if Phase 1–2 leave proven shared-socket queueing ≥ tens of ms p50 on A/B **and** owner approves. Design must include: same event loop only, ready-set handoff, hard-disable isolated thread, fill-rate soak, abort criteria.

---

## Completion criteria

- [ ] Armed crypto Redis levels update without ~50ms coalesce gap (unit + local probe)
- [ ] Rail cross → place does not wait on DB/REST tick (unit)
- [ ] No double-place; cancel/fill/rollover still correct (unit)
- [ ] Rollover soak: no feed stall window we introduced
- [ ] Latency stage logs: detect→send, source_age, redis age — documented before any prod ask
- [ ] **No prod deploy** without explicit owner instruction

## Blockers / decisions

- Dual Kalshi OB socket: deferred behind Phase 1–2 evidence.
- Commodity UT stays tape/`path=slow` in this plan.
