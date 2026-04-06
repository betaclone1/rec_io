---
name: Unified AES/ATS strike-driven refactor
overview: "Single user-level AES/ATS loops; strike tables hold literal yes/no probs; ATS reads OPEN trades + strike rows; deprecate active_trades. Telemetry: drop trades high/low; ATS refreshes ask min/max/range, unrealized pnl, ats_updated; trade_manager overwrites pnl on finalize; monitor_confirmed from freshness + optional lapse ledger."
todos:
  - id: doc-yes-no-prob-mapping
    content: "Document and test mapping lookup positive/negative → yes_prob/no_prob (settlement)"
    status: pending
  - id: migration-strike-prob-cols
    content: "Migration + schema ref + database.py + drift for yes/no prob columns on strike tables"
    status: pending
  - id: generator-literal-probs
    content: "strike_table_generator (+ ws) populate literal yes/no probs; keep active_side + diffs as needed"
    status: pending
  - id: migration-trades-ats-telemetry
    content: "Migration: add trades.ats_updated (timestamptz); optional lapse table or JSON; drop high_price/low_price after cutover + grep cleanup"
    status: pending
  - id: ats-trades-live-fields
    content: "Each successful ATS cycle per open trade: UPDATE ask min/max/range (15m only; hourly leave NULL), unrealized pnl, ats_updated; no high/low"
    status: pending
  - id: ats-strike-monitoring
    content: "Replace active_trades monitoring with strike row + trades; unit tests; relocate trailing-stop high watermark if needed"
    status: pending
  - id: monitor-confirmed-finalize-rule
    content: "trade_manager: replace high!=low + active_trades; monitor_confirmed from ats_updated (placeholder/permissive until staleness policy tuned)"
    status: pending
  - id: remove-active-trades-enrollment
    content: "Remove trade_manager ATS enrollment + pool tables after shadow period"
    status: pending
isProject: true
---

# Unified AES/ATS + strike-table–driven supervision

**Related:** [unified-kalshi-ws-master-aes-ats.md](unified-kalshi-ws-master-aes-ats.md), [unified-15m-aes-ats-reads.md](unified-15m-aes-ats-reads.md) (superseded for active_trades retention).

## Direction (recap)

- One **AES** and one **ATS** per user (or agreed scope): scan all relevant strike tables and bind **monitor context** per iteration so settings/symbol/market do not cross.
- **Strike rows:** store **literal** `yes_prob_*` / `no_prob_*` from lookup tables (both legs); keep **`active_side`** and existing diff entry logic where still needed.
- **ATS:** for each **OPEN** row in `users.trades_*`, resolve monitor → settings, find latest strike row for `ticker` (+ `exchange`, `symbol`, `market` cadence), derive **close-side price** and **probability** from that row (no duplicate Kalshi snapshot / prob lookup in ATS).
- **Deprecate `users.active_trades_*`:** after parity, remove enrollment and drop tables per migration hygiene.

---

## Telemetry: drop `high_price` / `low_price`, live ask columns, unrealized `pnl`, `ats_updated`, `monitor_confirmed`

### Target state (success criteria for this refactor)

- **Remove `high_price` and `low_price` from `users.trades_*`** (and simulated twin) once nothing depends on them. They were a proxy for “ATS moved the needle at least once”; replacement is **explicit freshness + optional lapse history**.
- **ATS, every pass** for each **open** trade it successfully evaluates: **`UPDATE`** the trade row with:
  - **`yes_ask_min_15m`, `yes_ask_max_15m`, `no_ask_min_15m`, `no_ask_max_15m`, `yes_ask_range_15m`, `no_ask_range_15m`** copied from the **current** matching strike row for **15m** trades. For **`market = hourly`** trades, leave these **NULL / blank** on the trade row (strike table often has NULLs outside the final-quarter window); **product assumption:** we do not hold hourly positions that need those fields before that window, so this is acceptable.
  - **`pnl`** — **unrealized** mark-to-market each tick: use the same **real-time close/sellable price** already derived from the strike row for monitoring (e.g. opposite-side ask → position value, consistent with how [`update_active_trade_monitoring_data`](backend/active_trade_supervisor.py) thinks about PnL), scaled by **`position`**, then **subtract the trade row’s current recorded `fees`** (whatever is already stored on the row—typically entry/fees-so-far; **do not** double-count at finalize when `trade_manager` recomputes total fees for realized PnL). Round consistently with [`trade_manager`](backend/trade_manager.py) close math where practical.
  - **`ats_updated`** (`TIMESTAMPTZ`): set **on every successful monitoring cycle** for that trade (successful strike join + row written for that open trade). Do **not** bump on skipped/failed ticks.
- **`trade_manager` on finalize:** **`UPDATE`** with **verified** `sell_price`, fees, and **realized `pnl`** — **overwrites** ATS’s unrealized value. No separate column required if product accepts **semantic overload:** while `status = 'open'`, `pnl` is **indicative**; after close it is **authoritative**.
- **Optional (later):** refresh **`roi_pct` / `ret_pct`** from unrealized `pnl` while open for dashboards; otherwise leave those **NULL or last-known** until close to avoid implying bankroll-based returns are finalized.
- **`trade_manager` on close/finalization:** compute **`monitor_confirmed`** from **monitoring thresholds**, not from high/low. **Staleness policy** (e.g. max `now - ats_updated` at finalize): **defer**—tune later; if the new stack behaves, strict thresholds are mostly a **moot edge case**. Until then, implement a **simple placeholder** (e.g. non-NULL `ats_updated` and/or permissive window) or keep legacy behavior only as long as needed for cutover.
  - **Optional secondary:** if a **lapse ledger** exists (below), require **no disqualifying lapses**—also deferrable.
- **Optional lapse record-keeping:** second table (e.g. `users.ats_trade_lapses_0001` with `trade_id`, `gap_start`, `gap_end`, `reason`) or append-only events; ATS (or a tiny helper) records when an open trade **misses** an expected tick (detected by monotonic clock / expected interval). Use this for ops dashboards and stricter `monitor_confirmed` policy later.

### What exists today (for contrast)

| Concern | Where it lives | Notes |
|--------|----------------|--------|
| **Running high/low** | **`users.active_trades_*`** | Position-value min/max; copied to trades on close. |
| **`monitor_confirmed`** | **`trade_manager`** | `high_price != low_price` after copy from `active_trades`. See [docs/DIAGNOSIS_MONITOR_CONFIRMED_FALSE.md](../../docs/DIAGNOSIS_MONITOR_CONFIRMED_FALSE.md). |
| **Ask min/max/range** | **`trade_manager` at INSERT** | Snapshot from strike at entry only; **not** refreshed by ATS today. |

### Dependency: strategies that used `high_price` on the row

**[`active_trade_supervisor`](backend/active_trade_supervisor.py)** auto-stop paths (e.g. Momentum Scalp / Reversal **trailing** logic) read **`high_price`** from the in-memory trade dict populated from **`active_trades`**. If those columns disappear from **`trades`**, we need a **replacement source of trailing watermark**:

- **Preferred:** keep **in-process** state keyed by `trade_id` inside the unified ATS process (survives as long as the process runs; restored on restart from “first tick after open” behavior), or  
- **Alternate:** a small dedicated column (e.g. `ats_trailing_peak`) **only if** you want DB durability across ATS restarts for trailing—scope deliberately.

Plan the grep/refactor for all **`high_price` / `low_price`** uses (~60 hits in `trade_manager`, ~40 in ATS, plus UI/analytics).

### `trade_manager` changes (telemetry)

- On **finalize**, always write **realized** **`pnl`** (and fees / `sell_price` as today); **replaces** any ATS unrealized value—no merge with “previous pnl” unless closing path explicitly preserves (it should not).
- Delete **`get_high_low_prices_from_active_trades`** and all close/expiration branches that merge high/low from `active_trades`.
- **Entry path:** either **stop** copying the six ask columns at insert (ATS becomes sole writer) **or** keep insert-time copy as bootstrap until first ATS tick—team choice; document to avoid double-source confusion.
- **Failsafe** that compared `high_price == low_price` must switch to an **`ats_updated`-based or process-health signal**; exact threshold **deferred** (see above).

### Implementation checklist (telemetry)

- [ ] Migration: add **`ats_updated`**; optional lapse table; **drop `high_price`, `low_price`** after code paths removed; sync **`trades_simulated_*`** per [AGENTS.md](../../AGENTS.md).  
- [ ] ATS: per-tick **`UPDATE`** open trades with six ask fields + **`pnl` (unrealized)** + `ats_updated`; implement lapse detection if in scope.  
- [ ] Document for API/UI: **`pnl` while open = mark-to-market**; **on close = realized** from `trade_manager`.  
- [ ] `trade_manager`: ensure finalize path **always** sets final `pnl` (and does not preserve stale ATS value by mistake).  
- [ ] ATS: migrate trailing-stop logic off DB `high_price` to in-process (or new minimal column).  
- [ ] `trade_manager`: new **`monitor_confirmed`** rule; remove active_trades high/low plumbing.  
- [ ] Grep: UI, APIs, backtests, reports using `high_price` / `low_price` on trades.  
- [ ] Update [docs/DIAGNOSIS_MONITOR_CONFIRMED_FALSE.md](../../docs/DIAGNOSIS_MONITOR_CONFIRMED_FALSE.md) to describe the new semantics once live.

---

## Rollout (unchanged summary)

1. Strike columns + generator (backward compatible).  
2. Shadow-compare ATS decisions old vs new.  
3. Flip telemetry to trades row + strike-only monitoring; retire `active_trades` writes.  
4. Remove enrollment; drop `active_trades` tables when prod-safe.

## Process shape (**locked**)

- **Two supervisor programs** (`auto_entry_supervisor` + `active_trade_supervisor`), each on its own **~1s persistent loop**, independent processes (blast-radius isolation). Ordering between AES and ATS is **not** guaranteed in the same tick; design strike writes and trade reads so **no cross-process lock** is required (strike table + trades row are the shared handoff).
