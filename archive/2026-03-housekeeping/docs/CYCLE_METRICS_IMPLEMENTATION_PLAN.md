# Cycle Metrics Implementation Plan

## Overview
Trade_manager will detect when ALL trades for a given cycle (monitor + contract + date) have been confirmed closed, then update cycle-level columns (`cycle_pnl`, `cycle_ret_pct`, `cycle_win_loss`) for ALL trades in that cycle.

## Cycle Definition
A cycle is uniquely identified by:
- `monitor` (e.g., "mon_0001_10025")
- `contract` (e.g., "BTC 6pm")
- `date` (e.g., "2025-12-12")

## Implementation Strategy

### 1. New Function: `check_and_update_cycle_metrics(trade_id: int)`

**Purpose**: Check if all trades for a cycle are closed, and if so, update cycle metrics for all trades in that cycle.

**Logic**:
1. Get `monitor`, `contract`, `date` for the newly closed trade
2. Query all trades for that `monitor + contract + date` combination
3. Check if ALL trades have `status = 'closed'` (exclude 'expired', 'pending', 'open', etc.)
4. If cycle is complete:
   - Calculate `cycle_pnl = SUM(pnl)` for all trades in cycle
   - Calculate `cycle_ret_pct = SUM(ret_pct)` for all trades in cycle
   - Calculate `cycle_win_loss = 'W' if cycle_pnl > 0 else 'L'`
   - Update ALL trades in the cycle with these values
5. If cycle is not complete, do nothing (wait for more trades to close)

**Edge Cases**:
- Trade has NULL monitor, contract, or date → Skip cycle check
- Cycle has no trades with pnl/ret_pct → Skip calculation (leave NULL)
- All trades are expired (not closed) → Don't update (wait for settlement)

### 2. Integration Points

Call `check_and_update_cycle_metrics(trade_id)` from:

1. **`update_trade_status_with_ret_pct()`** (line ~1804)
   - After updating trade to 'closed' status
   - Only when `status == 'closed'`

2. **`update_trade_status()`** (line ~1930)
   - After updating trade to 'closed' status
   - Only when `status == 'closed'`

3. **`poll_settlements_for_matches()`** (line ~3102)
   - After updating trade from 'expired' to 'closed'
   - After the UPDATE statement that sets status = 'closed'

### 3. Function Signature

```python
def check_and_update_cycle_metrics(trade_id: int) -> None:
    """
    Check if all trades for a cycle are closed, and if so, update cycle-level metrics.
    
    A cycle is defined by monitor + contract + date.
    Only updates when ALL trades in the cycle have status = 'closed'.
    """
```

### 4. SQL Logic

```sql
-- Step 1: Get cycle info for this trade
SELECT monitor, contract, date 
FROM users.trades_0001 
WHERE id = %s

-- Step 2: Check if all trades in cycle are closed
SELECT 
    COUNT(*) as total_trades,
    COUNT(CASE WHEN status = 'closed' THEN 1 END) as closed_trades
FROM users.trades_0001
WHERE monitor = %s 
  AND contract = %s 
  AND date = %s
  AND monitor IS NOT NULL
  AND contract IS NOT NULL
  AND date IS NOT NULL

-- Step 3: If total_trades == closed_trades, calculate and update
WITH cycle_stats AS (
    SELECT 
        SUM(pnl) as total_pnl,
        SUM(ret_pct) as total_ret_pct
    FROM users.trades_0001
    WHERE monitor = %s 
      AND contract = %s 
      AND date = %s
      AND status = 'closed'
      AND pnl IS NOT NULL
      AND ret_pct IS NOT NULL
)
UPDATE users.trades_0001 t
SET 
    cycle_pnl = cs.total_pnl,
    cycle_ret_pct = cs.total_ret_pct,
    cycle_win_loss = CASE WHEN cs.total_pnl > 0 THEN 'W' ELSE 'L' END
FROM cycle_stats cs
WHERE t.monitor = %s 
  AND t.contract = %s 
  AND t.date = %s
  AND t.status = 'closed';
```

### 5. Edge Case: Re-entry After Cycle Completion

**Scenario**: All trades for a cycle are closed and cycle metrics are updated. Then new trades are entered for the same monitor+contract+date cycle.

**Current Behavior**: 
- New trades will be added to the cycle
- When the last new trade closes, cycle metrics will be recalculated
- This will overwrite the previous cycle metrics with new totals that include the new trades

**Note**: This is acceptable for now. If it becomes an issue, we can add logic to detect this scenario and handle it differently (e.g., create a "cycle_v2" identifier or track cycle completion timestamps).

## Testing Considerations

1. Test with single trade in cycle
2. Test with multiple trades in cycle (all close at different times)
3. Test with trades that have NULL pnl/ret_pct
4. Test with expired trades (should not trigger until settled)
5. Test edge case: re-entry after cycle completion

## Implementation Order

1. Create `check_and_update_cycle_metrics()` function
2. Add call to `update_trade_status_with_ret_pct()` 
3. Add call to `update_trade_status()`
4. Add call to `poll_settlements_for_matches()`
5. Test with existing closed trades

