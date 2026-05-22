# Checkpoint: sandbox WS rollover + market resolution (verified)

**Status:** Working as designed (operator confirmed **2026-05-20**). Treat this as the baseline to return to before extending the feed toward production wiring.

**Parent repo commit at documentation time:** `51c69da` (sandbox tree was still uncommitted under `scripts/sandbox/kalshi_market_feed/` — **tag or commit this checkpoint** before larger refactors).

---

## What is proven

| Behavior | Mechanism |
|----------|-----------|
| **Instant 15m rollover** | Wall-clock live ticker authoritative; new OB subscribed before old removed; no REST at `:00/:15/:30/:45` |
| **One outgoing contract** | Single prior 15m window on ticker WS until `market_result` (~`SANDBOX_KALSHI_OUTGOING_TRACK_SEC`, default 960s) |
| **Market resolution** | **`market_lifecycle_v2`** `determined` / `settled` with `result` → `source=lifecycle_ws` (production path) |
| **Pre-discovery** | REST `GET /markets` only on startup + `SANDBOX_KALSHI_SCHEDULE_REFRESH_SEC` (default 15m); **4h** ahead (+ buffer) of 15m BTC markets |
| **Observability** | JSONL events + monitor schedule (last **3** settled with yes/no, live, outgoing, full upcoming) |

---

## Verification (ground truth — not the monitor UI)

```bash
# Terminal 1
.venv/bin/python scripts/sandbox/kalshi_market_feed/kalshi_market_ws_master.py

# Terminal 2
.venv/bin/python scripts/sandbox/kalshi_market_feed/kalshi_market_feed_monitor.py
# → http://localhost:8791

# At each quarter hour:
tail -f scripts/sandbox/kalshi_market_feed/kalshi_market_events.jsonl \
  | grep -E 'rollover_15m|market_result'
```

**Pass criteria:**

1. One `rollover_15m` per boundary (`live_ticker`, `outgoing_ticker`, `lifecycle_sid` set).
2. Soon after, `market_result` for **`outgoing_ticker`** with `"source": "lifecycle_ws"`.
3. Ws master log: `WS_ROLLOVER_OK market_result <ticker> yes|no (lifecycle_ws)`.

---

## Architecture (do not regress)

```
REST GET /markets  →  schedule pre-discovery only (not on rollover)
        │
        ▼
Single WSS:  ticker + orderbook_delta + market_lifecycle_v2
        │
        ├─ orderbook_delta  →  one live 15m OB in Redis
        ├─ ticker           →  quotes only (NOT settlement)
        └─ market_lifecycle_v2  →  market_result (15m series only when ONLY_15M=1)
        │
        ▼
sandbox:kalshi:* Redis + kalshi_market_events.jsonl
```

---

## Hard rules learned (why earlier attempts failed)

1. **`market_result` does not arrive on the ticker channel** for these 15m markets — JSONL showed continuous `ticker` events with zero `market_result`. Do not expect settlement from ticker WS alone.
2. **Subscribe `market_lifecycle_v2`** on the same authenticated socket (global feed; filter client-side to `KXBTC15M-…` when `SANDBOX_KALSHI_15M_ONLY=1`).
3. **Ignore hourly lifecycle for 15m sandbox** — `KXBTCD-…` determined events filled `settled_tickers` and hid 15m results until filtered to 15m-only.
4. **No REST backfill / settlement polling** — operator requirement; breaks the purpose of validating WS rollover.
5. **No REST on rollover boundary** — schedule lag was the original ~20s delay; wall-clock ticker fixed it.
6. **Persist 15m `market_result` through schedule refresh** — `_enrich_schedule_with_settled_results` + 15m-only settled registry; REST refresh alone wipes in-memory results.

---

## Key files (this checkpoint)

| File | Role |
|------|------|
| `kalshi_market_ws_master.py` | Single ingest: schedule, WSS, seq OB, lifecycle, Redis meta, JSONL |
| `kalshi_market_feed_monitor.py` | Read-only UI at :8791 (`/api/feed`) |
| `frontend/styles/sandbox-kalshi-monitor.css` | Monitor layout |
| `frontend/js/orderbook-redis-ui.js` | Orderbook render (scroll anchor tweaks shared with trade monitor) |

**Isolation:** No imports from `backend/` or `scripts/` (sandbox clean room). Phase 2 = map Redis shapes to prod / `apply_lifecycle_market_result_for_ticker` fanout.

---

## Env defaults that define this baseline

| Variable | Default | Meaning |
|----------|---------|---------|
| `SANDBOX_KALSHI_15M_ONLY` | `0` | Multi-strike: 15m per symbol + hourly ATM window; set `1` for BTC 15m-only |
| `SANDBOX_KALSHI_PREDISCOVER_HOURS` | `4` | REST window for upcoming markets |
| `SANDBOX_KALSHI_SCHEDULE_REFRESH_SEC` | `900` | REST schedule refresh (not rollover) |
| `SANDBOX_KALSHI_OUTGOING_TRACK_SEC` | `960` | Track one outgoing 15m for result |
| `SANDBOX_KALSHI_ORDERBOOK_CUTOVER_SEC` | `2` | Live → outgoing phase cut |
| `SANDBOX_KALSHI_REDIS_PREFIX` | `sandbox:kalshi:` | Redis key prefix |

---

## Safe extensions from here

- Wire sandbox Redis / JSONL outcomes toward prod `market_lifecycle_v2` → tenant trade finalization (see `backend/core/kalshi_lifecycle_trade_outcome.py`).
- Add symbols (`ETH`, …) via `SANDBOX_KALSHI_SYMBOLS` and `SERIES_15M_BY_SYMBOL`.
- Hourly book mode only if `SANDBOX_KALSHI_15M_ONLY=0` and separate settlement policy.

## Unsafe without re-validation

- Removing `market_lifecycle_v2` subscription.
- Re-adding REST settlement polls or rollover-time `GET /markets`.
- Tracking many outgoing tickers in UI/subs without a retention policy.
- Using monitor “pending” alone as proof of WS failure (check JSONL `source=lifecycle_ws` first).

---

## Restore checklist

When returning after experimental changes:

1. `grep -E 'market_lifecycle_v2|ONLY_15M|_enrich_schedule' scripts/sandbox/kalshi_market_feed/kalshi_market_ws_master.py` — all present.
2. `grep rest_backfill kalshi_market_ws_master.py` — **no matches**.
3. Run one live quarter-hour; confirm JSONL pass criteria above.
4. Compare behavior to this doc, not to an older chat summary.
