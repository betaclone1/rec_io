# Orderbook foundation (system-wide)

**Goal:** One shared Kalshi OB → Redis levels path with minimum controllable latency. Every strat reads the same book. No strategy-specific flush policy.

**Baseline regression:** Exp Scalp IOC fills collapsed after Tail-oriented OB experiments on prod (`747aae6a` / `34284cda`). Dual-socket attempts previously wedged ingest.

**Status:** Foundation rewrite in tree (immediate flush for all subscribed books; wake filters separate). Local unit tests required before any prod ask.

**Deploy:** local + tests only until owner explicitly says deploy / rollback.

---

## Non-negotiable rules

| Rule | Why |
|------|-----|
| Single Kalshi OB socket, one event loop | Dual socket / isolated thread collapsed fills |
| Immediate Redis publish for **every** subscribed OB ticker | Flush policy is not a strategy feature |
| Lean OB hints (no embedded levels) | Redis levels key is SoT; avoid double JSON fanout |
| UT / TM watch = wake / UI only | Must never gate whether Redis is fresh |
| Measure with fill rate (e.g. 10046) + apply→Redis ms | Probe ms alone is not success |

---

## Controllable path

```
Kalshi WS → apply (master.lock) → immediate Redis SET + lean hint
  → any consumer: AES / TM / UT / LT / probe (depth via Redis GET)
```

UI prebuild runs after hint. Cycle-hot PG enqueue runs off lock (current cycle only). Public trade Redis off WS loop. Non-lean 15m OB also pre-subscribes the **next** clock ticker.

---

## Done in this pass

- [x] `should_immediate_flush_orderbook` — default on for all tickers
- [x] `should_wake_tradeflow_on_orderbook` — live crypto current / allowlist / watches only
- [x] Lean OB hints (levels only in Redis key)
- [x] Pre-subscribe next 15m OB ticker for non-lean symbols
- [x] Periodic resync uses wake/crypto/stale — not “all immediate”
- [x] Unit tests: `tests/unit/test_orderbook_foundation_flush.py` + updated Phase2 / UT tests
- [x] Docs: `docs/ORDERBOOK_HOT_CACHE.md`

## Still open (prod)

- [ ] Owner decision: deploy foundation vs rollback to `db278cb9`
- [ ] After enact: soak Exp Scalp (10046) fill rate + `ob_latency_probe` apply→Redis
- [ ] No dual socket without explicit gate + abort criteria
