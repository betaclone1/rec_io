# Collateral exposure mechanism

**Goal:** Implement a collateral exposure mechanism that calculates net collateral at risk across all open positions (per-market YES/NO and legs cancel out), so we cap new exposure to bankroll_current and never dip into the Cash Transfer subaccount.

**Scope:** In: per-market net collateral exposure (positions on opposite sides of the money line cancel); aggregation across all markets with open positions; comparison to bankroll_current; gating proposed new trades against available collateral relative to bankroll only (not total portfolio). Out: changing Kalshi product behavior; siloed subaccounts (we are doing this ourselves).

**Status:** draft  
**Priority:** top

---

## Definition: collateral exposure

Collateral exposure is the **maximum NET loss** we could have in any single settlement outcome (losses on losing legs minus value from winning legs in that same outcome), **plus total fees already paid** (sunk cost; added to all scenarios). In each outcome, legs that settle in our favor offset the legs that lose — so we always work with net loss, not gross. Example: if in one outcome we lose $1000 on two NO legs but win $300 on two YES legs, net loss = $700; that is the exposure in that outcome. We run this from the **actual state** of the trades (strikes + sides); the codebase does not label bracket vs breakout. Total collateral exposure is compared to **bankroll_current**; any proposed new trade must keep total exposure within bankroll so we never use the Cash Transfer reserve.

---

## Design: where and when

- **Storage:** Add a `collateral_exposure` column to account balance (e.g. `users.account_balance_0001`). Trade_manager is the sole writer of this column (balance sync continues to write balance fields; trade_manager updates only `collateral_exposure` so writers don't overwrite each other — e.g. UPDATE by user_id for that column only). **No historical data:** the column is for real-time decisions only; no backfill or history needed.
- **Recalculation:** A dedicated **collateral exposure calculation function** in trade_manager runs whenever trade_manager creates or modifies a trade. It reads the trades log, computes total exposure, and writes the result to account_balance.

**When we recalculate**

| Event | Recalc? |
|-------|--------|
| New trade created (status PENDING) | Yes |
| Trade REJECTED (trade entry deleted) | Yes |
| Trade ACCEPTED / confirmed OPEN (actual buy_price and fees recorded) | Yes |
| Trade CLOSED (closed before expiration) | Yes |
| Trade marked EXPIRED (held to expiration) | **No** — EXPIRED still ties up capital; no change in exposure until settlement |
| Settlement confirms trade CLOSED (after expiration) | Yes |

**Which trades count toward exposure:** **Live trades only** (e.g. `trades_0001`). Paper trades (`trades_simulated_0001`) do not count; skip them in the calculation. Among live trades, include only those with status **PENDING**, **OPEN**, or **EXPIRED**. We treat PENDING the same as OPEN for exposure so that if multiple tickets arrive before any are confirmed, we don’t over-commit (avoids race with AES). CLOSED trades are excluded. **Not monitor-specific:** multiple monitors can trade the same tickers in the same cycle; we aggregate by contract (ticker), not by monitor. The calculation is **state-based**: from each position we use contract (ticker), strike, side, and cost; we determine worst-case loss from possible settlement outcomes (see Collateral calculation below), not a simple per-contract cancel-out. Use fees when present (e.g. for OPEN/EXPIRED); for PENDING we have only submitted position_size and buy_price (fees may be estimated or omitted until we have actuals).

---

## Collateral calculation: overall reasoning

**Collateral exposure = the maximum NET loss we could have in any single settlement outcome, plus fees already paid.**

- **NET loss per outcome:** For each possible settlement outcome, we do **not** just sum the cost of legs that lose. In that same outcome, some legs **win** — they pay out. Those wins offset the losses. So for each outcome: **net loss = (cost lost on losing legs) − (value from winning legs in that outcome)**. Collateral exposure = **max over all outcomes** of that net loss. Example: price > 80.25k → NO at 80k and NO at 80.25k lose ($1000 total), but YES at 70k and YES at 70.25k **win** ($300 total). We lose $1000, we win $300 → **net loss = $700**. That is the exposure in that scenario; the correct collateral number is $700 (the worst-case net), not the gross $1000.
- **Winning legs offset losing legs:** In any outcome, contracts that settle in our favor reduce our net loss. The calculation must account for which positions win and which lose in each outcome, then take the worst net.
- **Fees are sunk:** All fees have been paid regardless of eventual outcome; that money is already spent. So fees are **added to all scenarios** — they represent capital already committed. Collateral exposure = max_net_loss_over_outcomes **+ total fees paid** (or include fees in position cost and add them once, since they are gone in every outcome).

The codebase does **not** distinguish bracket vs breakout; we derive from the **actual state**: which strikes, which side (YES/NO), and cost per position. For each settlement level we determine which legs lose and which win, compute net loss, then take the max. Implementation needs: (1) strike and event/cycle per position, (2) logic that maps settlement outcome → which positions lose vs win, (3) net loss = losses − wins in that outcome, (4) exposure = max(net loss over outcomes) + total fees.

---

## Design: gating new trades

When trade_manager receives a **new trade ticket**:

1. **Hard cap (2% buffer):** If current `collateral_exposure` is already within 2% of `bankroll_current` (e.g. `collateral_exposure >= 0.98 * bankroll_current`), **reject the request entirely**: do not write a trade entry, do not send to trade_executor. Log that a trade request was submitted but not approved (e.g. "collateral near bankroll cap").
2. **Otherwise:** From the ticket we have position_size, buy_price, CONTRACT, SIDE. Compute the cost of this trade and run the collateral exposure calculation **as if this trade were already open** → `new_collateral_exposure`.
3. **If `new_collateral_exposure <= bankroll_current`:** Submit the trade as requested (create PENDING entry, send to trade_executor).
4. **If `new_collateral_exposure > bankroll_current`:** Do not submit at requested size. Compute the **difference** (how much headroom remains). Determine how much can be spent on this trade to stay within bankroll. Derive a **reduced position size** from buy_price (and **under-estimate by ~10%** to be safe). Create PENDING entry and send the **sized-down** trade through the chain. Log that the trade was sized down (requested vs submitted size).

Trade_manager reads `bankroll_current` and `collateral_exposure` from account_balance when handling a ticket; the sync (e.g. kalshi_account_sync_ws) keeps bankroll_current up to date.

---

## Clarifications (agreed)

- **EXPIRED in the sum:** Recalc logic sums over status in (PENDING, OPEN, EXPIRED). We only skip *recalculating* on the transition to EXPIRED because the exposure number doesn't change.
- **Concurrent writes:** When trade_manager updates `collateral_exposure`, use an UPDATE that touches only that column (and only the row for the user), so balance sync updates to other columns don't clash.
- **Paper excluded:** Paper trades do not count. Use live trades table only for the exposure calculation and gate; skip paper trades entirely.
- **Logging:** Log only when something notable happens: (1) request rejected because collateral is within 2% of bankroll; (2) trade sized down (requested vs submitted size). Do **not** log every successful collateral check or every recalc — keep volume low to avoid noise.

---

## Steps

1. **DB:** Add `collateral_exposure` column to account_balance table (migration): NOT NULL DEFAULT 0, same numeric type/units as bankroll_current. Update schema ref and database.py. No historical backfill.
2. **Calc function:** Implement the dedicated collateral exposure calculation in trade_manager: read **live** trades only (exclude paper); filter status in (PENDING, OPEN, EXPIRED). For each position: ticker (contract), strike, side, cost (incl. fees when present). For each settlement outcome: which positions lose vs win; **net loss = (cost of losing legs) − (value from winning legs in that outcome)**. Collateral exposure = **max over outcomes of net loss** + **total fees already paid** (fees are sunk; add to all scenarios). Return total in dollars (same unit as bankroll_current). Requires strike and event/cycle to group positions and enumerate outcomes.
3. **Write-through:** Whenever trade_manager creates or modifies a trade (create PENDING, delete on reject, confirm OPEN, set CLOSED, or settlement sets CLOSED), call the calc, then UPDATE account_balance SET collateral_exposure = ? for the user. Do **not** recalc on the transition to EXPIRED only. **Settlement path:** In `poll_settlements_for_matches` (trade_manager.py), after each UPDATE that sets a trade to status='closed' and commit, call the collateral recalc for that user.
4. **Gate on new ticket:** Serialize ticket handling per user (e.g. lock) so only one ticket is processed at a time — avoids race where two tickets read the same exposure and both pass. Then: (a) read bankroll_current and collateral_exposure from account_balance; (b) if collateral_exposure >= 0.98 * bankroll_current, reject and log; (c) else compute new_collateral_exposure with this trade at full size; (d) if new > bankroll, compute headroom, derive reduced position size (under-estimate ~10%), submit sized-down trade and log; (e) else submit as-is.
5. **Document and test:** Document which statuses are included, the state-based formula (strikes + sides → outcome loss → max over outcomes), and where the gate runs. Optional: sanity test or script to verify cap is enforced.

---

## Completion criteria

- [ ] `collateral_exposure` column exists on account_balance; trade_manager is the only writer.
- [ ] Collateral exposure is recomputed on create PENDING, delete (reject), confirm OPEN, set CLOSED, and settlement CLOSED; not on set EXPIRED. EXPIRED trades are included in the exposure sum until CLOSED.
- [ ] New tickets are gated with per-user serialization (lock); reject if within 2% of bankroll; else size down with 10% safety if needed, or submit as-is.
- [ ] Logging only when notable: "not approved" (at cap) and "sized down" (reduced size); no noisy per-check or per-recalc logs.
- [ ] Formula (state-based: strikes + sides → worst-case over settlement outcomes) and behavior documented; optional test or sanity check.

---

## Other suggestions (agreed)

- **No backfill:** Collateral exposure in account_balance is for real-time decisions only; no historical data needed. Column NOT NULL DEFAULT 0; value is maintained by write-through from trade events.
- **Settlement path (confirmed):** In trade_manager, `poll_settlements_for_matches` updates trades from 'expired' to 'closed' (UPDATE ... SET status = 'closed' ... WHERE status = 'expired'). After each such update and commit, call the collateral recalc for that user so exposure drops when the trade is marked CLOSED.
- **Concurrent tickets:** Serialize ticket handling per user (lock) so only one ticket is processed at a time. Prevents two tickets from reading the same exposure and both passing before either PENDING is written. Does not interfere with intended functionality.

## Blockers / decisions

- Confirm account_balance table name and that UPDATE collateral_exposure-only is safe with concurrent balance sync.
- **Strike and event/cycle for exposure:** Trades must expose strike (and event or cycle) so the calc can group positions by event and compute outcome-based loss. Confirm where strike lives (ticker encoding, trade row, or contract metadata) and how we identify "same event" for multi-leg outcome logic.

---

## Future / note

If Kalshi ever opens their subaccount program to all users, we could create a real subaccount and silo the cash reserve there. The cap logic remains useful either way (e.g. "only 10% of bankroll to spare" → size down).
