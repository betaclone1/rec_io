# ATS Failsafe and Expiration Processing Audit

## Date: 2025-12-11

## Critical Issue Discovered

**Problem**: Trades that are STOPPED OUT (auto-stop triggered) before expiration are having their `high_price` and `low_price` values OVERWRITTEN with NULL by expiration processing.

## Root Cause Analysis

### Expected Flow (How It Should Work)

1. **Trade is Stopped Out (Auto-Stop)**:
   - ATS detects auto-stop condition and triggers close
   - Trade_manager receives close request
   - Trade_manager updates status to 'closing'
   - Trade_manager retrieves `high_price`/`low_price` from `active_trades` table
   - Trade_manager updates trade to 'closed' with `high_price`/`low_price` preserved
   - Trade_manager notifies ATS that trade is 'closed'
   - ATS removes trade from `active_trades` table
   - **Result**: Trade has status='closed' and valid `high_price`/`low_price` in trades table

2. **Expiration Processing**:
   - Runs at expiration time (e.g., 10:00:00, 12:00:00)
   - Queries trades with status IN ('open', 'closing', 'close_failed')
   - **Should NOT touch trades with status='closed'**
   - For trades that are still open/closing, marks them as 'expired'

### Actual Flow (What's Broken)

1. **Trade is Stopped Out**:
   - ✅ ATS triggers close correctly
   - ✅ Trade_manager closes trade with `high_price`/`low_price` from `active_trades`
   - ✅ Trade is marked 'closed' with valid `high_price`/`low_price`
   - ✅ ATS removes trade from `active_trades`

2. **Expiration Processing Runs**:
   - ❌ **BUG**: Even though trade is 'closed', expiration processing may run on it
   - ❌ **BUG**: `get_high_low_prices_from_active_trades()` is called, but trade is no longer in `active_trades`
   - ❌ **BUG**: Returns `(None, None)`
   - ❌ **BUG**: UPDATE statement writes `high_price = None, low_price = None`
   - ❌ **BUG**: This OVERWRITES the valid values that were set when trade was closed

### The Critical Bug Location

**File**: `backend/trade_manager.py`
**Lines**: 2750-2762

```python
# Get high_price and low_price from active_trades before it's removed
high_price, low_price = get_high_low_prices_from_active_trades(trade_id)

cursor.execute("""
    UPDATE users.trades_0001 
    SET status = 'expired', 
        closed_at = %s, 
        symbol_close = %s,
        close_method = 'expired',
        high_price = %s,  # ❌ OVERWRITES existing values with None if trade was already removed
        low_price = %s   # ❌ OVERWRITES existing values with None if trade was already removed
    WHERE id = %s AND status IN ('open', 'closing', 'close_failed')
""", (closed_at, symbol_close, high_price, low_price, trade_id))
```

**The Problem**:
- If a trade was already closed and removed from `active_trades`, `get_high_low_prices_from_active_trades()` returns `(None, None)`
- The UPDATE statement then writes NULL values, OVERWRITING any existing `high_price`/`low_price` that were set when the trade was closed
- The WHERE clause `status IN ('open', 'closing', 'close_failed')` should prevent this, BUT:
  - If there's a race condition where expiration runs while trade is still 'closing'
  - Or if the status check happens before the UPDATE but the trade was closed between the query and the UPDATE

## Evidence from Database

**Affected Trades**: 6257, 6258, 6261, 6268, 6272, 6294

All show:
- `status = 'closed'`
- `close_method = 'expired'` (❌ Should be 'auto_stop' or similar)
- `high_price = NULL` (❌ Should have valid value)
- `low_price = NULL` (❌ Should have valid value)

But trade_manager logs show these trades were STOPPED OUT with valid high/low prices:
- Trade 6261: Closed at 09:50:27, retrieved `high_price=0.9400, low_price=0.3800`
- Trade 6268: Closed at 09:50:37, retrieved `high_price=0.9800, low_price=0.8800`
- Trade 6258: Closed at 09:50:48, retrieved `high_price=0.9700, low_price=0.6100`

## The ATS Failsafe System Design

**Two-Layer Failsafe Architecture**:

### First Check: ATS Self-Monitoring (Real-Time)
- **Location**: `active_trade_supervisor.py`
- **Purpose**: ATS monitors itself in real-time to ensure it's tracking all live active trades
- **Mechanism**: 
  - Checks if monitoring thread is alive
  - Verifies active trades are being updated
  - Detects if monitoring has stopped
- **Action on Failure**: Restarts monitoring thread, or escalates to full process restart

### Second Check: Trade_Manager Validation (On Trade Close)
- **Location**: `trade_manager.py` (in `confirm_close_trade()` and paper trade finalization)
- **Purpose**: Validates that ATS was monitoring correctly by checking trade history
- **Mechanism**:
  - When a trade closes, checks if `high_price == low_price`
  - If they're the same, it means ATS was NOT monitoring (values never changed from initial buy_price)
  - This is a "SURE sign that ATS has stopped monitoring"
- **Action on Failure**: Alerts the specific ATS instance to restart via `notify_active_trade_supervisor_direct_with_monitor()` with status `"monitoring_failure"`

### Either Check Triggers Full Restart
- If EITHER check fails, it prompts a full restart of the active_trade_supervisor script for that monitor
- This ensures maximum reliability and quick recovery from monitoring failures

## What Needs to Be Fixed

### Critical Bug: Violation of Immutability Rule

**The expiration processing is VIOLATING the fundamental rule that closed trades are immutable historical records.**

1. **Expiration Processing Must NEVER Touch Already-Closed Trades**:
   - The WHERE clause `status IN ('open', 'closing', 'close_failed')` should prevent this
   - BUT: There may be a race condition or the query may be selecting trades that get closed between the SELECT and UPDATE
   - **Fix**: Add explicit check before UPDATE: if trade status is already 'closed', skip it entirely
   - **Fix**: Use a more defensive query that re-checks status before UPDATE

2. **Expiration Processing Must NOT Overwrite Existing Values**:
   - If `get_high_low_prices_from_active_trades()` returns `(None, None)`, it means trade was already removed from `active_trades`
   - This could mean:
     - Trade was already closed (should skip it - see #1)
     - Trade was never monitored (should leave NULL for failsafe detection)
   - **Fix**: Before writing NULL, check if trade already has `high_price`/`low_price` set
   - **Fix**: If values exist, preserve them (don't overwrite)
   - **Fix**: Only set NULL if values are currently NULL AND trade was never closed

3. **Close Method Should Reflect Actual Close Reason**:
   - Trades stopped out should have `close_method = 'auto_stop'` or similar
   - Not `close_method = 'expired'` if they were stopped out before expiration
   - This is a data integrity issue but less critical than the NULL overwrite

### Root Cause Analysis Needed:
- Why are already-closed trades being selected by the expiration query?
- Is there a race condition between trade closing and expiration processing?
- Is the WHERE clause not working as expected?

## System State Requirements

### Critical Immutability Rule
**Once any trade is confirmed CLOSED and its trade history columns properly filled in, NO OTHER PROCESS touches that trade again. It is set in the historical record.**

This means:
- ✅ Closed trades are IMMUTABLE historical records
- ✅ No process should UPDATE a closed trade
- ✅ Expiration processing must NEVER touch already-closed trades
- ✅ All history columns (including `high_price`/`low_price`) are final once set

### For a trade that is STOPPED OUT:
- ✅ Status should be 'closed'
- ✅ `close_method` should reflect the stop reason (e.g., 'auto_stop', 'momentum_spike', etc.)
- ✅ `high_price` and `low_price` MUST be preserved from when trade was closed
- ✅ Expiration processing should NEVER touch it (violates immutability rule)

### For a trade that EXPIRES:
- ✅ Status should be 'expired' (or 'closed' with `close_method='expired'`)
- ✅ `high_price` and `low_price` should be retrieved from `active_trades` before removal
- ✅ If trade was never monitored (not in `active_trades`), `high_price`/`low_price` should remain NULL
- ✅ This NULL case is the failsafe detection: indicates ATS was not monitoring

### Universal Requirement:
- ✅ **EVERY SINGLE TRADE** regardless of strategy or monitor will be reported with `high_price` and `low_price` for trade history recording
- ✅ These values are ALWAYS recorded when trade is closed (either from `active_trades` or NULL if unmonitored)

## Code Flow Analysis

### Expiration Processing Flow (Lines 2700-2769)

1. **Line 2704**: SELECT trades with `status IN ('open', 'closing', 'close_failed')`
   - This captures trades that should be expired
   - **Potential Issue**: If a trade is closed between this SELECT and the UPDATE, it may still be in the list

2. **Lines 2715-2740**: Get symbol closing prices (takes time)

3. **Line 2747**: Loop through selected trades

4. **Line 2751**: Get `high_price`/`low_price` from `active_trades`
   - **BUG**: If trade was already closed and removed from `active_trades`, returns `(None, None)`

5. **Lines 2753-2762**: UPDATE trade to 'expired'
   - **WHERE clause**: `status IN ('open', 'closing', 'close_failed')`
   - **Should prevent**: Updating already-closed trades
   - **BUT**: If trade status is still 'closing' when UPDATE runs, it will execute

### Race Condition Scenario

**Timeline**:
- T=0: Expiration SELECT runs, finds trade with status='closing'
- T=1: Trade closing process completes, sets status='closed', removes from `active_trades`
- T=2: Expiration UPDATE runs with `high_price=None, low_price=None`
- T=3: WHERE clause checks status, but if there's a transaction isolation issue, UPDATE might still execute

**OR**:
- Trade is in 'closing' status when expiration runs
- Expiration UPDATE executes (status is still 'closing')
- Overwrites `high_price`/`low_price` with None
- Trade then gets fully closed, but values are already NULL

## Required Fix

### Fix 1: Add Status Re-Check Before UPDATE
Before executing the UPDATE, re-check the trade status. If it's already 'closed', skip it entirely.

### Fix 2: Preserve Existing Values
If `get_high_low_prices_from_active_trades()` returns `(None, None)`, check if the trade already has `high_price`/`low_price` set. If so, preserve them instead of overwriting with NULL.

### Fix 3: Use Conditional UPDATE
Only update `high_price`/`low_price` if they're currently NULL. Use SQL conditional logic to preserve existing values.

## Next Steps

1. **DO NOT PATCH** - User requested full audit first
2. Verify the exact scenario causing the bug:
   - Are trades in 'closing' status when expiration runs?
   - Is the WHERE clause not working?
   - Is there a transaction isolation issue?
3. Design fix that:
   - Preserves `high_price`/`low_price` for stopped-out trades (immutability rule)
   - Still allows failsafe detection for unmonitored trades (NULL values)
   - Doesn't break existing functionality
   - Ensures closed trades are NEVER touched by expiration processing

