# Stuck CLOSING Trade - Diagnostic Report

**Date**: December 2, 2025  
**Issue**: Trade 5296 stuck in CLOSING status, not confirming as closed  
**Severity**: HIGH - Trade appears closed on exchange but system hasn't confirmed

---

## Summary

Trade 5296 was manually closed and is stuck in "CLOSING" status. The trade appears to have closed successfully on the Kalshi exchange (no open position), but the system has not confirmed the close and transitioned it to "closed" status.

---

## Timeline

### December 2, 2025 - 13:26:04
- Trade 5296 manually closed
- Status changed to "closing" in both `trades_0001` and `active_trades_0001_10002` tables
- Active trade supervisor updated: `🔄 TRADE STATUS UPDATED TO CLOSING IN ACTIVE_TRADES.DB`
- Monitoring loop stopped (expected - no active trades)

### December 2, 2025 - 13:26:07
- Kalshi account sync triggered orders sync
- Orders sync completed: "0 new, 0 updated in PostgreSQL users.orders_0001"
- **CRITICAL**: No new orders found, suggesting close order may not be in sync yet

### Current Status
- Trade 5296 remains in "CLOSING" status
- No confirmation logs found
- Position appears closed on exchange (user verified)

---

## Root Cause Analysis

### Close Confirmation Flow

The system uses this flow to confirm a closed trade:

1. **Manual Close Triggered** (`trade_manager.py` line 2090-2163)
   - Frontend sends close request
   - `trade_manager` sends close order to `trade_executor`
   - Sets status to "closing" in database
   - **Does NOT store order_id_close at this point**

2. **Trade Executor Processes Close** (`trade_executor.py` line 133-266)
   - Sends order to Kalshi API
   - Receives order_id from Kalshi response
   - Notifies `trade_manager` with status "accepted" and order_id

3. **Trade Manager Stores order_id_close** (`trade_manager.py` line 2240-2276)
   - Receives "accepted" status from executor
   - Stores order_id_close in trades table (line 2263)
   - **CRITICAL POINT**: If this fails, order_id_close is never stored

4. **Kalshi Account Sync** (`kalshi_account_sync`)
   - Syncs orders from Kalshi API
   - Updates `orders_0001` table
   - Notifies `trade_manager` that orders table was updated

5. **Trade Manager Confirms Close** (`trade_manager.py` line 2390-2415)
   - Receives notification that orders table was updated
   - Finds all trades with status "closing"
   - Calls `confirm_close_trade()` for each

6. **Confirm Close Trade** (`trade_manager.py` line 604-800)
   - Retrieves order_id_close from trades table
   - **CRITICAL**: If order_id_close is NULL, function returns early (line 628-631)
   - Looks up order in orders_0001 table
   - Checks if order status is "executed" and remaining_count = 0
   - If confirmed, updates trade status to "closed"

### Potential Failure Points

#### 1. **order_id_close Not Stored**
**Location**: `trade_manager.py` line 2240-2276

**Problem**: If the trade_executor's notification to trade_manager fails or is delayed, the order_id_close may never be stored in the database.

**Evidence Needed**:
- Check if order_id_close is NULL in trades_0001 for trade 5296
- Check trade_manager logs for "STORING CLOSING ORDER_ID" message
- Check trade_executor logs for order_id extraction

**Code Reference**:
```python:2240:2276:backend/trade_manager.py
if new_status == "accepted":
    if order_id:
        if intent == "close":
            order_id_field = "order_id_close"
            # ... stores order_id_close ...
```

#### 2. **Order Not in ORDERS Table**
**Location**: `kalshi_account_sync` and `confirm_close_trade` line 642-647

**Problem**: The close order may not have been synced from Kalshi API yet, or the sync may have missed it.

**Evidence**:
- Kalshi account sync log shows "0 new, 0 updated" at 13:26:07
- This suggests either:
  - The order was already in the table (unlikely for a new close)
  - The order hasn't been created by Kalshi yet (unlikely - user says position is closed)
  - The sync is not finding the order (possible - timing or API issue)

**Code Reference**:
```python:642:647:backend/trade_manager.py
cursor.execute("""
    SELECT remaining_count, fill_count, status, taker_fees, maker_fees
    FROM users.orders_0001 
    WHERE order_id = %s
""", (stored_order_id_close,))
```

#### 3. **confirm_close_trade Not Being Called**
**Location**: `trade_manager.py` line 2390-2415

**Problem**: The orders update notification may not be triggering the confirmation check, or there may be an exception preventing it.

**Evidence Needed**:
- Check for "[🔔 ORDERS UPDATED] Found X closing trades to confirm" in logs
- Check for "CONFIRMING CLOSE TRADE: 5296" in logs
- Check for exceptions in the orders update handler

**Code Reference**:
```python:2390:2415:backend/trade_manager.py
if db_name == "orders":
    # ... finds closing trades ...
    if closing_trades:
        log(f"[🔔 ORDERS UPDATED] Found {len(closing_trades)} closing trades to confirm")
        for id, ticket_id in closing_trades:
            # ... calls confirm_close_trade ...
```

#### 4. **Order Status Not "executed"**
**Location**: `trade_manager.py` line 654

**Problem**: The order may be in the ORDERS table but not yet marked as "executed", or remaining_count may not be 0.

**Code Reference**:
```python:654:655:backend/trade_manager.py
if order_status == "executed" and remaining_count == 0 and fill_count > 0:
    # ... confirms close ...
```

---

## Diagnostic Steps Required

### Step 1: Check Database State
```sql
-- Check trade status and order_id_close
SELECT id, status, order_id_close, ticket_id, ticker 
FROM users.trades_0001 
WHERE id = 5296;

-- Check active_trades status
SELECT trade_id, status 
FROM users.active_trades_0001_10002 
WHERE trade_id = 5296;

-- If order_id_close exists, check if order is in orders table
SELECT order_id, status, remaining_count, fill_count
FROM users.orders_0001
WHERE order_id = '<order_id_close_from_trade>';
```

### Step 2: Check Logs for order_id Storage
```bash
# Check trade_manager logs for order_id storage
grep -i "5296\|STORING.*ORDER_ID\|CLOSING.*ORDER_ID" logs/main_app.out.log

# Check trade_executor logs for order_id extraction
grep -i "5296\|EXTRACTED ORDER_ID\|TRADE SUCCESS" logs/trade_executor*.log
```

### Step 3: Check for Confirmation Attempts
```bash
# Check for confirmation attempts
grep -i "5296\|CONFIRMING CLOSE\|ORDERS UPDATED.*closing" logs/main_app.out.log

# Check for errors in confirm_close_trade
grep -i "5296\|ERROR.*CLOSE\|NO CLOSE ORDER_ID" logs/main_app.out.log
```

### Step 4: Check Kalshi Account Sync
```bash
# Check recent orders sync activity
tail -100 logs/kalshi_account_sync.out.log | grep -i "orders\|5296"
```

---

## Immediate Actions Needed

### If order_id_close is NULL:
1. **Manual Fix**: Find the close order_id from Kalshi API or orders table
2. **Update Database**: 
   ```sql
   UPDATE users.trades_0001 
   SET order_id_close = '<actual_order_id>' 
   WHERE id = 5296;
   ```
3. **Trigger Confirmation**: Manually trigger orders update notification or wait for next sync

### If order_id_close exists but order not in ORDERS table:
1. **Force Orders Sync**: Trigger kalshi_account_sync to fetch latest orders
2. **Check API**: Verify order exists in Kalshi API
3. **Manual Fix**: If order exists in API but not in DB, manually insert it

### If order exists but status is wrong:
1. **Check Order Status**: Verify order status in orders_0001 table
2. **Wait for Sync**: Order may still be processing
3. **Manual Override**: If order is clearly executed but status is wrong, may need manual fix

### If confirm_close_trade is not being called:
1. **Check Notification System**: Verify orders update notifications are working
2. **Manual Trigger**: Manually call confirm_close_trade function
3. **Check for Exceptions**: Look for errors preventing the confirmation check

---

## Code Issues Identified

### 1. **No Retry Logic for order_id Storage**
If the trade_executor notification fails, order_id_close is never stored and the trade can never be confirmed.

**Recommendation**: Add retry logic or periodic check for trades in "closing" status without order_id_close.

### 2. **Silent Failure in confirm_close_trade**
If order_id_close is NULL, the function returns early with only a log message. There's no fallback mechanism.

**Recommendation**: Add alternative confirmation method (e.g., check positions table for zero position).

### 3. **No Verification After Status Change**
When status is set to "closing", there's no verification that order_id_close will be stored.

**Recommendation**: Add verification step or timeout mechanism.

### 4. **Orders Sync May Miss Orders**
The sync shows "0 new, 0 updated" which may indicate orders are not being found or are already present.

**Recommendation**: Add logging to show which orders were checked and why they weren't updated.

---

## Recommended Fixes (For Reference Only)

### 1. Add Fallback Confirmation Method
If order_id_close is missing, check positions table to see if position is zero for the ticker.

### 2. Add Periodic Check for Stuck Closing Trades
Add a background job that periodically checks for trades in "closing" status and attempts to confirm them.

### 3. Improve Error Logging
Add more detailed logging at each step of the close confirmation process.

### 4. Add Manual Override
Add an endpoint to manually confirm a closed trade if automatic confirmation fails.

---

## Conclusion

The trade is stuck in CLOSING status because one of these conditions is not met:
1. order_id_close is not stored in the database
2. The close order is not in the orders_0001 table
3. The order exists but status is not "executed" with remaining_count = 0
4. confirm_close_trade is not being called when orders table updates

**Immediate Action**: Check the database to determine which condition is failing, then apply the appropriate fix.



