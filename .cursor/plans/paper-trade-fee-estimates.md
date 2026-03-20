# Paper trade fee calculation estimates

**Goal:** Add estimated fee amounts for paper trades using Kalshi’s trading-fee formula (from [fee schedule](https://kalshi.com/docs/kalshi-fee-schedule.pdf)) so PnL and UI reflect realistic open + close costs.

**Scope:** In scope: trade_manager paper open/close/settlement paths (compute and store estimated fees); trade history and trade monitor UI; desktop and mobile parity. Out of scope: changing live-trade fee logic; Kalshi API fee fetches.

**Status:** done (completed 2026-03-13)

## Context

- Live trades get fees from Kalshi ORDERS (we only ever pay taker; `taker_fees_dollars` is what we use). Paper trades currently use `fees = 0.00` everywhere.
- `trades_0001.fees` and PnL formula `pnl = sell_value - buy_value - fees` already exist; paper path just passes 0.
- Trade history and trade monitor (desktop + mobile) already show a Fees column; paper trades show blank/zero.

## Kalshi fee formula (trading fees)

From Kalshi fee schedule (trading fees, top of doc): fee is based on **contract price** and **number of contracts**.

- **Taker fee (per leg):** `fee = round_up(0.07 × C × P × (1 - P))` in dollars  
  - **C** = number of contracts (position)  
  - **P** = contract price in dollars (e.g. 0.50 for 50¢)  
  - **round_up** = round up to the next cent (Kalshi convention)

So we estimate:
- **Open leg:** `open_fee = round_up(0.07 * position * buy_price * (1 - buy_price))` (price we paid to open).
- **Close leg (only when closed before expiration):** The closing transaction is a **buy** to close. We record `sell_price` as what we effectively got (e.g. 0.29); the order we sent was a buy at **1 − sell_price** (e.g. 0.71). Fee on that closing order uses that execution price: `close_fee = round_up(0.07 * position * (1 - sell_price) * sell_price)`.
- **At expiration:** no closing order; only open fee applies (already stored at open).

---

## Paper trade fee calculation (definitive)

**Taker fees only.** We only ever pay taker fees. The estimate uses Kalshi’s taker rate (0.07) for both open and close legs when applicable.

**Two cases:**

1. **Trade held until expiration** — The only fees are on the order open. There is no closing order, so no close fee. The final trade record has `fees` = open fee only.
2. **Trade closed out (manual or auto-close before expiration)** — There are fees on open and on the closing transaction. The two are totaled and stored on the final closed trade record: `fees` = open fee + close fee.

**When to apply:** Only for paper trades (`paper_trade = true`). Live trades keep using actual fees from `users.orders_0001` (open + close order rows).

**Helper (one place):**
```text
estimate_kalshi_taker_fee(position: int, price: float) -> float
  raw = 0.07 * position * price * (1 - price)
  return ceil(raw * 100) / 100   # round up to next cent
```

**At paper open:**  
- `open_fee = estimate_kalshi_taker_fee(position, buy_price)`  
- Store `fees = open_fee` on the trade row.

**At paper close (manual or auto-close before expiration):**  
- Read existing `fees` from DB (open fee).  
- Stored `sell_price` is what we effectively got per contract (e.g. 0.29). The closing transaction is a **buy** at price `1 - sell_price` (e.g. 0.71). Fee for that leg uses the execution price: `close_fee = estimate_kalshi_taker_fee(position, 1 - sell_price)`.  
- `total_fees = open_fee + close_fee`.  
- PnL: `pnl = sell_value - buy_value - total_fees`.  
- Persist `fees = total_fees` and `pnl` on the closed trade record.

**At paper expiration (settlement):**  
- Only open fee applies; no closing transaction.  
- Total fees = open fee already in `fees`.  
- PnL: `pnl = sell_value - buy_value - fees`.  
- Do not add a close fee; do not overwrite `fees`.

**Validation:** Run `scripts/diagnostics/sample_live_trades_fees_for_validation.py` (position ≥ 100). Expired live trades (open fee only) match this formula closely.

## Steps

1. [x] **Implement fee helper** — In backend (e.g. `trade_manager` or shared util), add `estimate_kalshi_taker_fee(position: int, price: float) -> float`. Compute `0.07 * position * price * (1 - price)` and round up to nearest cent (e.g. `math.ceil(x * 100) / 100`). Use for both open and close legs.
2. [x] **Trade manager: paper open** — When opening a paper trade, compute `open_fee = estimate_kalshi_taker_fee(position, buy_price)`. Store in `fees` (open fee only at this point).
3. [x] **Trade manager: paper close (before expiration)** — When closing a paper trade manually or via auto-close (not expiration): read existing `fees` from DB (open fee). Closing transaction is a buy at `1 - sell_price`; compute `close_fee = estimate_kalshi_taker_fee(position, 1 - sell_price)`. Total fee = open_fee + close_fee. PnL = sell_value - buy_value - total_fee. Persist `fees` = total_fee and PnL.
4. [x] **Trade manager: paper expiration settlement** — No close order; total fee = open fee only (already in `fees`). PnL = sell_value - buy_value - fees. No change to fee total at settlement.
5. [x] **UI: trade history** — Ensure trade history (desktop + mobile) shows stored `fees` for paper trades; optional “(est.)” or tooltip.
6. [x] **UI: trade monitor** — Ensure trade monitor (desktop + mobile) shows fees for paper trades consistently.
7. [x] **Tests** — Add or extend tests: paper open stores open fee; paper close before expiration uses open + close fee in PnL; expiration uses open fee only; helper rounds up to cent correctly.

## Completion criteria

- [x] Paper open: estimated open fee (Kalshi formula, round up to cent) computed and stored in `fees`.
- [x] Paper close before expiration: close fee added to open fee; total in PnL and persisted in `fees`.
- [x] Paper expiration: PnL uses open fee only (no close fee).
- [x] Trade history and trade monitor show fee values for paper trades on desktop and mobile.
- [x] No regression to live-trade fee logic or display.
- [x] Tests cover fee helper, open fee, close-before-expiration total fee, and expiration.

## Validation (before implementing)

Run against production (or any DB with live trades that have fees recorded):

```bash
PYTHONPATH=$(pwd) python3 scripts/diagnostics/sample_live_trades_fees_for_validation.py --limit 30
```

This samples live closed trades where `fees` > 0 and compares actual fees to the taker formula per leg. We only pay taker fees; use results to confirm rounding (round up to cent) and that open+close legs match recorded totals.

## Blockers / decisions

- **Column semantics:** Store estimate in existing `fees` column for paper so existing UI works; no new column.
- **Taker only:** We only ever pay taker fees. Both open and close legs use the taker rate (0.07).
