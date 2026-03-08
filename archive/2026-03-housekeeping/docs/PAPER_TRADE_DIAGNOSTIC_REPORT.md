# Paper Trading Diagnostic Report

**Date:** 2025-11-30
**Issue:** Auto entry works in PAPER TRADING mode but not in LIVE trading mode. When switching back to paper_trade=TRUE, nothing works.

---

## Issue Summary

1. **Paper Trading (paper_trade=TRUE):** ✅ Works correctly
2. **Live Trading (paper_trade=FALSE):** ❌ Does not work
3. **Switching back to Paper Trading:** ❌ Nothing works after switch

---

## Code Flow Analysis

### 1. Auto Entry Supervisor - Paper Trade Fetching

**File:** `backend/auto_entry_supervisor.py`
**Location:** Lines 1947-1964

**Code:**
```python
# Get paper_trade setting from monitor config
paper_trade = False
try:
    import psycopg2
    conn = psycopg2.connect(...)
    with conn.cursor() as cursor:
        cursor.execute(f"SELECT paper_trade FROM users.monitor_list_{USER_NUMBER} WHERE id = %s", (MONITOR_ID,))
        result = cursor.fetchone()
        if result and result[0] is not None:
            paper_trade = bool(result[0])
    conn.close()
except Exception as e:
    log(f"[AUTO ENTRY] ⚠️ Could not get paper_trade setting: {e}, defaulting to False")
```

**Analysis:**
- ✅ Paper_trade is fetched FRESH from database every time `trigger_auto_entry_trade()` is called
- ✅ No caching at function level
- ✅ Defaults to False if query fails
- ⚠️ **POTENTIAL ISSUE:** If database query fails silently, paper_trade will default to False even if it's True in DB

**Trade Payload:**
```python
trade_payload = {
    ...
    "paper_trade": paper_trade  # Line 1988
}
```

---

### 2. Trade Manager - Paper Trade Handling

**File:** `backend/trade_manager.py`
**Location:** Lines 2322-2399

**Code Structure:**
```python
# Line 2323-2327: Extract paper_trade from payload
paper_trade = data.get('paper_trade', False)
if isinstance(paper_trade, str):
    paper_trade = paper_trade.lower() in ('true', '1', 'yes')
elif paper_trade is None:
    paper_trade = False

# Line 2329-2368: Paper trade handling (returns early)
if paper_trade:
    # PAPER TRADE: Skip executor, create pending trade, then immediately mark as open
    log(f"📝 PAPER TRADE: Skipping executor, processing immediately")
    
    # Insert trade with 'pending' status first
    data['status'] = 'pending'
    trade_id = insert_trade(data)
    
    if trade_id is None:
        return {"error": "Failed to insert paper trade to database", "id": None}
    
    # Notify active trade supervisor about the new pending trade
    notify_active_trade_supervisor_direct(trade_id, data.get("ticket_id", "PAPER"), "pending")
    
    # Immediately mark as open with fees = 0.00
    # ... update to open status ...
    
    # Notify active trade supervisor that trade is now open
    notify_active_trade_supervisor_direct(trade_id, data.get("ticket_id", "PAPER"), "open")
    
    return {"id": trade_id}  # LINE 2368: EARLY RETURN

# Line 2369-2380: Live trade handling
else:
    # LIVE TRADE: Send to executor as normal
    try:
        import requests
        executor_port = get_executor_port()
        log(f"SENDING TO EXECUTOR")
        response = requests.post(f"http://localhost:{executor_port}/trigger_trade", json=data, timeout=5)
        log(f"EXECUTOR RESPONSE: {response.status_code}")
    except Exception as e:
        log(f"EXECUTOR ERROR: {e}")
        log_event(data.get("ticket_id", "UNKNOWN"), f"EXECUTOR ERROR: {e}")

# Line 2382-2399: Database insertion (OUTSIDE else block)
# Log immediately after executor call, before heavy database operations
log(f"TRADE SENT TO EXECUTOR - PROCESSING DATABASE")

# Ensure the trade is inserted with 'pending' status
data['status'] = 'pending'
trade_id = insert_trade(data)

if trade_id is None:
    log(f"❌ Failed to insert trade to database - cannot notify active trade supervisor")
    log_event(data["ticket_id"], "MANAGER: SENT TO EXECUTOR — DATABASE INSERT FAILED")
    return {"error": "Failed to insert trade to database", "id": None}

log_event(data["ticket_id"], "MANAGER: SENT TO EXECUTOR — CONFIRMED")

# Notify active trade supervisor about the new pending trade
notify_active_trade_supervisor_direct(trade_id, data["ticket_id"], "pending")

return {"id": trade_id}
```

**Analysis:**
- ✅ Paper trades return early at line 2368, so lines 2382-2399 never execute (correct)
- ✅ Live trades send to executor, then continue to lines 2382-2399 for database insertion (correct)
- ⚠️ **POTENTIAL ISSUE:** If executor call fails, code still continues to insert into database
- ⚠️ **POTENTIAL ISSUE:** If executor times out (5 seconds), code continues but executor might still be processing

---

## Potential Root Causes

### 1. Database Query Failure in Auto Entry Supervisor

**Scenario:** Database connection fails or query returns None/empty result

**Symptoms:**
- `paper_trade` defaults to False even when it's True in database
- Auto entry supervisor sends `paper_trade: False` in payload
- Trade manager treats it as live trade

**Diagnosis:**
- Check logs for: `[AUTO ENTRY] ⚠️ Could not get paper_trade setting`
- Check if database connection is stable
- Verify monitor_list table has paper_trade column

**Test:**
```sql
SELECT id, paper_trade FROM users.monitor_list_0001 WHERE id = 10019;
```

---

### 2. Executor Failure for Live Trades

**Scenario:** Trade executor is down, unreachable, or times out

**Symptoms:**
- Live trades are sent to executor but fail
- Trade is still inserted into database as 'pending'
- Trade never gets confirmed by executor
- Active trade supervisor never receives 'open' status

**Diagnosis:**
- Check logs for: `EXECUTOR ERROR` or `EXECUTOR RESPONSE: 500/404/timeout`
- Check if trade_executor service is running
- Check if executor port is correct

**Test:**
```bash
# Check if executor is running
ps aux | grep trade_executor

# Check executor logs
tail -50 logs/trade_executor.out.log
```

---

### 3. Payload Mismatch

**Scenario:** `paper_trade` value is not being passed correctly through the chain

**Symptoms:**
- Auto entry supervisor fetches paper_trade=True from DB
- But payload sent to trade_manager has paper_trade=False
- Or payload is missing paper_trade entirely

**Diagnosis:**
- Check auto_entry_supervisor logs for: `📤 Sending trade to trade_manager`
- Verify `paper_trade` is in the payload JSON
- Check trade_manager logs for: `📝 PAPER TRADE` or `SENDING TO EXECUTOR`

**Test:**
Add logging to verify payload:
```python
log(f"[AUTO ENTRY] Paper trade value in payload: {trade_payload.get('paper_trade')}")
log(f"[AUTO ENTRY] Paper trade type: {type(trade_payload.get('paper_trade'))}")
```

---

### 4. State Caching Issue

**Scenario:** Some component is caching the paper_trade value and not refreshing it

**Symptoms:**
- Switching paper_trade in database doesn't take effect
- Auto entry supervisor continues using old value
- Requires restart to pick up new value

**Diagnosis:**
- Check if any global variables cache paper_trade
- Check if any functions cache monitor configuration
- Verify database query is executed every time (not cached)

**Test:**
- Toggle paper_trade in database
- Check auto_entry_supervisor logs immediately
- Verify new value is fetched

---

### 5. Exception Swallowing

**Scenario:** Exceptions are being caught and logged but not properly handled

**Symptoms:**
- Errors in logs but code continues
- Trade appears to be sent but nothing happens
- Silent failures

**Diagnosis:**
- Check all exception handlers in auto_entry_supervisor
- Check all exception handlers in trade_manager
- Look for `except Exception as e:` blocks that might be swallowing errors

---

## Diagnostic Steps

### Step 1: Verify Database Value

```sql
SELECT id, name, paper_trade, auto_trade, auto_trade_status 
FROM users.monitor_list_0001 
WHERE id = 10019;
```

**Expected:**
- `paper_trade` should be `t` (True) or `f` (False)
- `auto_trade` should be `t` (True)
- `auto_trade_status` should be `ACTIVE`

---

### Step 2: Check Auto Entry Supervisor Logs

```bash
tail -100 logs/auto_entry_supervisor_0001_10019.out.log | grep -E "(paper_trade|PAPER|Sending trade)"
```

**Look for:**
- `paper_trade: True` or `paper_trade: False` in trade payload
- Any errors fetching paper_trade setting
- Trade payload being sent to trade_manager

---

### Step 3: Check Trade Manager Logs

```bash
tail -100 logs/trade_manager.out.log | grep -E "(PAPER TRADE|SENDING TO EXECUTOR|EXECUTOR ERROR)"
```

**Look for:**
- `📝 PAPER TRADE: Skipping executor` (for paper trades)
- `SENDING TO EXECUTOR` (for live trades)
- `EXECUTOR ERROR` (if executor is failing)
- `EXECUTOR RESPONSE: 200` (if executor succeeds)

---

### Step 4: Check Executor Status

```bash
# Check if executor is running
ps aux | grep trade_executor

# Check executor logs
tail -50 logs/trade_executor.out.log
```

**Look for:**
- Executor process running
- Recent trade requests in logs
- Any errors or exceptions

---

### Step 5: Test Database Query Directly

```python
import psycopg2
import os

conn = psycopg2.connect(
    host=os.getenv('POSTGRES_HOST', 'localhost'),
    database=os.getenv('POSTGRES_DB', 'rec_io_db'),
    user=os.getenv('POSTGRES_USER', 'rec_io_user'),
    password=os.getenv('POSTGRES_PASSWORD', 'rec_io_password')
)

with conn.cursor() as cursor:
    cursor.execute("SELECT paper_trade FROM users.monitor_list_0001 WHERE id = 10019")
    result = cursor.fetchone()
    print(f"Paper trade value: {result[0] if result else None}")
    print(f"Paper trade type: {type(result[0]) if result else None}")
    print(f"Paper trade bool: {bool(result[0]) if result else None}")

conn.close()
```

---

### Step 6: Add Diagnostic Logging

**In `auto_entry_supervisor.py` at line 1964 (after paper_trade fetch):**
```python
log(f"[AUTO ENTRY] 🔍 DEBUG: Fetched paper_trade from DB: {paper_trade} (type: {type(paper_trade)})")
log(f"[AUTO ENTRY] 🔍 DEBUG: Monitor ID: {MONITOR_ID}, User Number: {USER_NUMBER}")
```

**In `auto_entry_supervisor.py` at line 1988 (before sending payload):**
```python
log(f"[AUTO ENTRY] 🔍 DEBUG: Paper trade in payload: {trade_payload.get('paper_trade')} (type: {type(trade_payload.get('paper_trade'))})")
```

**In `trade_manager.py` at line 2327 (after paper_trade extraction):**
```python
log(f"[TRADE MANAGER] 🔍 DEBUG: Extracted paper_trade from payload: {paper_trade} (type: {type(paper_trade)})")
log(f"[TRADE MANAGER] 🔍 DEBUG: Raw paper_trade value: {data.get('paper_trade')}")
```

---

## Critical Code Structure Issue

**File:** `backend/trade_manager.py`
**Lines:** 2382-2399

**Issue:** The database insertion code (lines 2382-2399) is OUTSIDE the `else` block. This means:

1. **For paper trades:**
   - Code enters `if paper_trade:` block
   - Inserts trade and returns at line 2368
   - Lines 2382-2399 never execute ✅ (correct)

2. **For live trades:**
   - Code enters `else:` block
   - Sends to executor (lines 2372-2380)
   - Continues to lines 2382-2399 for database insertion ✅ (correct)

**However, there's a potential issue:**
- If executor call fails or times out, code still continues to insert into database
- This might cause duplicate trades or inconsistent state
- Trade might be inserted as 'pending' but executor never processes it

**Recommendation:**
- Consider moving database insertion INSIDE the else block
- Or add error handling to prevent database insertion if executor fails

---

## Questions to Answer

1. **Does auto_entry_supervisor require restart when paper_trade changes?**
   - **Answer:** NO - paper_trade is fetched fresh from database every time
   - **But:** If there's a database connection issue, it might default to False

2. **Does trade_manager cache paper_trade value?**
   - **Answer:** NO - paper_trade is extracted from payload each time
   - **But:** If payload is missing paper_trade, it defaults to False

3. **Is executor required for live trades?**
   - **Answer:** YES - live trades must go through executor
   - **But:** If executor is down, trades will fail

4. **What happens if executor fails for live trade?**
   - **Answer:** Trade is still inserted into database as 'pending'
   - **But:** Trade never gets confirmed, active_trade_supervisor never tracks it

---

## Recommended Diagnostic Actions

1. ✅ Check database value for paper_trade
2. ✅ Check auto_entry_supervisor logs for paper_trade in payload
3. ✅ Check trade_manager logs for paper_trade handling
4. ✅ Check executor status and logs
5. ✅ Add diagnostic logging to trace paper_trade value through entire chain
6. ✅ Test with paper_trade=True and paper_trade=False separately
7. ✅ Verify executor is running and responding for live trades

---

## Next Steps

1. Run diagnostic queries to verify database state
2. Check logs for paper_trade value at each step
3. Verify executor is running and responding
4. Add diagnostic logging if needed
5. Test with explicit paper_trade values to isolate issue


