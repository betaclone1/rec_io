# Lower Tail — development handoff

## Canonical doc
[docs/LOWER_TAIL_STRATEGY.md](../../docs/LOWER_TAIL_STRATEGY.md)

## Implementation plan
`~/.cursor/plans/lower_tail_2fbf435e.plan.md`

## Behavior
1. User sets **limit price `L`** (+ size / subaccount / **min_time**). Placement is **not** TTC-gated.
2. On each new cycle, arm from Kalshi ``open_time`` and place dual BID/ASK post-only GTC at that exact `L` **at open_time** (sleep + short busy-spin; miss → skip, no late place).
3. **min_time:** if `> 0` and still unfilled when TTC ≤ min_time → cancel all rests. if `0` → never cancel for TTC; rests may expire unfilled.
4. First fill → **cancel** the other rest (before ladder snapshot / TM book).
5. Filled trade → **trade_manager** (`intent=lower_tail_fill`) with fill-time ladder `prob`/`diff`.


**Status:** done

## Local / prod status
- Migration `20261017_1500_maker_edge_strategy` (+ drawdown halt `20261018_1200`) shipped with release v3.12.13
- `lower_tail_agent` + AES/ATS exclude + TM booking + UI detectors
- Regenerating supervisord + restarting `lower_tail_agent_*` required to run the worker

## Do not
- Wire real money without explicit owner approval
- Add data fallbacks for fills or `market_result`
