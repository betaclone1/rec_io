# Diagnosis: 15m strike tables not rolling over / staying empty

**Date:** 2026-03-04  
**Scope:** Why `live_data.strike_table_15m_btc` (and potentially other 15m strike tables) end up empty despite the generator running and `market_kalshi_15m_*` having rows. No code changes in this doc — diagnosis only.

---

## Observed behavior

- **strike_table_generator_15m_btc** runs and logs e.g. "Processing 1 strike (15m): 73708", "Missing ask prices for strike 73708, skipping", "Generated 0 strike table records for BTC".
- **live_data.strike_table_15m_btc** has 0 rows after each run.
- **live_data.market_kalshi_15m_btc** has rows with valid yes_ask/no_ask and strike strings like `$73,325.99` or `$73,494.50`.

So the generator runs, clears the strike table, then inserts nothing because it skips the only strike it considers.

---

## Root cause: strike list vs match use different rounding

The generator does two different things with the same `floor_strike` value (parsed from the market table’s `strike` column, e.g. 73325.99 or 73494.5):

1. **Building the strike list (15m)**  
   - `strike_table_generator.py` ~759–762: from each market, `market_strike = int(float(floor_strike) + 0.01)` and that value is used as the strike to process.  
   - Example: `floor_strike = 73325.99` → `73326`; or `73494.5` → `73495`.

2. **Matching that strike back to a market to get ask prices**  
   - ~851–854: for each `strike` in that list, it looks for a market where `int(float(floor_strike)) == strike`.  
   - Example: same market has `floor_strike = 73325.99` → `int(73325.99) = 73325`. So it looks for `strike == 73325`, but the list has `73326`. No match.  
   - Example: `floor_strike = 73494.5` → list has `73495`, match uses `73494`. Again no match.

So whenever the market row’s strike has a fractional part (e.g. `$73,325.99` or `$73,494.50`):

- The **strike list** gets the **rounded-up integer** (e.g. 73326 or 73495).
- The **match** uses the **truncated integer** (e.g. 73325 or 73494).
- The only market row never matches the only strike → `yes_ask`/`no_ask` stay `None` → "Missing ask prices for strike …" → that strike is skipped → 0 rows inserted → table stays empty.

So the 15m strike table doesn’t “roll over” because every run clears the table and then inserts zero rows due to this one-strike, no-match behavior.

---

## Code references

| Location | Behavior |
|----------|----------|
| **Build strike list (15m)** — ~759–762 | `market_strike = int(float(floor_strike) + 0.01)` → e.g. 73494.5 → 73495. |
| **Match strike to market** — ~851–854 | `if int(float(floor_strike)) == strike` → e.g. 73494.5 → 73494. |
| **Effect** | Strike 73495 is in the list; only market has floor_strike 73494.5 → int 73494; 73494 ≠ 73495 → no match, skip, 0 inserts. |

Same logic applies for any fractional strike (e.g. 73325.99 → list 73326, match 73325).

---

## Secondary path: synthetic strike

If `available_strikes` is empty (no markets or no valid `floor_strike`), the 15m path uses a synthetic strike:

- ~772–773: `single = int(round(current_price))` (e.g. 73708 if price is ~73708).
- That strike is then matched the same way: `int(float(floor_strike)) == strike`.
- If the market table has only rows with fractional strikes (e.g. 73494.5), no row has `int(floor_strike) == 73708`, so again no match → "Missing ask prices for strike 73708" → 0 rows.

So you can also see the “Missing ask prices” for a round number like 73708 when the generator fell back to the synthetic strike and the market table had no matching integer strike.

---

## Why it might appear to work on dev

- **Different strike format in DB:** If on dev the 15m market table has strikes stored as whole numbers (e.g. `73708` or `$73,708`) then `floor_strike` is 73708.0, and both `int(73708.0 + 0.01) = 73708` and `int(73708.0) = 73708` agree → match succeeds → rows written.
- **Timing/rollover:** If dev’s 15m markets roll to a new contract whose strike is written as a whole number, the generator can start writing again until the next fractional strike appears.
- So the same code can leave the table empty on production (where strikes are fractional) and appear to “roll over” on dev when strikes are whole numbers.

---

## Summary

| Item | Conclusion |
|------|------------|
| **Why 15m BTC strike table is empty** | The strike list is built with `int(float(floor_strike) + 0.01)` but the market match uses `int(float(floor_strike))`. For fractional strikes (e.g. $73,325.99 or $73,494.50) the two integers differ, so the only strike never matches the only market row → ask prices never found → row skipped → 0 inserts every run. |
| **Why “roll over” fails** | Each run clears the table and then inserts 0 rows because of the above; the table never gets new data. |
| **Why dev can look fine** | If dev’s 15m market data has whole-number strikes, both sides use the same integer and the match succeeds. |

No patch applied in this document; this is diagnosis only for use when implementing a fix (e.g. consistent rounding or matching rule for strike list vs market lookup).
