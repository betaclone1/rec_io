# Paper Trading Implementation - Complete Technical Documentation

**Date:** 2025-11-30
**Purpose:** Complete technical documentation of all changes made to implement paper trading functionality. This document is for AI agents to use for re-implementation, debugging, or reverting changes.

---

## Table of Contents

1. [Database Schema Changes](#database-schema-changes)
2. [Backend Changes - Trade Manager](#backend-changes-trade-manager)
3. [Backend Changes - Auto Entry Supervisor](#backend-changes-auto-entry-supervisor)
4. [Backend Changes - Active Trade Supervisor](#backend-changes-active-trade-supervisor)
5. [Backend Changes - Main App](#backend-changes-main-app)
6. [Frontend Changes - Dashboard](#frontend-changes-dashboard)
7. [Frontend Changes - Dashboard Mobile](#frontend-changes-dashboard-mobile)
8. [Frontend Changes - Trade Monitor](#frontend-changes-trade-monitor)
9. [Frontend Changes - JavaScript Files](#frontend-changes-javascript-files)
10. [Known Issues and Bugs](#known-issues-and-bugs)

---

## Database Schema Changes

### 1. `users.trades_0001` Table

**File:** `backend/core/config/database.py`

**Change:** Added `paper_trade` column to the trades table.

**Location in code:**
- Line ~1487: Added `paper_trade BOOLEAN DEFAULT FALSE` to CREATE TABLE statement
- Lines ~160-168: Added migration logic to conditionally add column if it doesn't exist

**SQL:**
```sql
ALTER TABLE users.trades_0001 ADD COLUMN paper_trade BOOLEAN DEFAULT FALSE;
```

**Migration Logic:**
```python
IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'users'
      AND table_name = 'trades_0001'
      AND column_name = 'paper_trade'
) THEN
    ALTER TABLE users.trades_0001 ADD COLUMN paper_trade BOOLEAN DEFAULT FALSE;
END IF;
```

### 2. `users.monitor_list_XXXX` Tables

**Files:**
- `backend/core/config/database.py`
- `scripts/manage_monitors_list.sh`
- `scripts/user_registration_system.sh`

**Change:** Added `paper_trade` column to all monitor_list tables.

**Location in code:**
- `database.py` line ~168: Added to CREATE TABLE for `monitor_list_0001`
- `database.py` lines ~169-180: Added migration loop for all `monitor_list_XXXX` tables
- `manage_monitors_list.sh`: Added to CREATE TABLE statement
- `user_registration_system.sh`: Added to CREATE TABLE statement

**SQL:**
```sql
ALTER TABLE users.monitor_list_0001 ADD COLUMN paper_trade BOOLEAN DEFAULT FALSE;
```

**Migration Logic:**
```python
# Loop through all monitor_list tables
DO $$
DECLARE
    table_name TEXT;
BEGIN
    FOR table_name IN 
        SELECT tablename FROM pg_tables 
        WHERE schemaname = 'users' 
        AND tablename LIKE 'monitor_list_%'
    LOOP
        EXECUTE format('
            ALTER TABLE users.%I 
            ADD COLUMN IF NOT EXISTS paper_trade BOOLEAN DEFAULT FALSE
        ', table_name);
    END LOOP;
END $$;
```

### 3. Schema Reference Documentation

**File:** `docs/MASTER_DB_SCHEMA_REFERENCE.md`

**Changes:**
- Line 9847: Added `paper_trade` column to `users.monitor_list_0001` table definition
- Line 10191: Added `paper_trade` column to `users.trades_0001` table definition

**Format:**
```
| `paper_trade` | `boolean` | YES | false | |
```

---

## Backend Changes - Trade Manager

### File: `backend/trade_manager.py`

### 1. `insert_trade()` Function

**Location:** Lines ~269-420

**Changes:**
- Added extraction of `paper_trade` from trade payload (lines ~381-386)
- Added `paper_trade` to INSERT statement (line ~395)
- Added `paper_trade` to VALUES tuple (line ~420)

**Code:**
```python
# Get paper_trade value from trade payload, default to False
paper_trade = trade.get('paper_trade', False)
if isinstance(paper_trade, str):
    paper_trade = paper_trade.lower() in ('true', '1', 'yes')
elif paper_trade is None:
    paper_trade = False

# In INSERT statement:
cursor.execute("""
    INSERT INTO users.trades_0001 (
        ...
        paper_trade
    ) VALUES (..., %s)
    RETURNING id
""", (..., paper_trade))
```

### 2. `add_trade()` Endpoint - OPEN TRADE Section

**Location:** Lines ~2100-2399

**Changes:**
- Added paper_trade check at line ~2323-2327
- Added paper trade handling block at lines ~2329-2368
- Modified live trade section at lines ~2369-2399

**Paper Trade Logic (lines 2329-2368):**
```python
if paper_trade:
    # PAPER TRADE: Skip executor, create pending trade, then immediately mark as open
    log(f"📝 PAPER TRADE: Skipping executor, processing immediately")
    
    # Insert trade with 'pending' status first
    data['status'] = 'pending'
    trade_id = insert_trade(data)
    
    if trade_id is None:
        log(f"❌ Failed to insert paper trade to database")
        log_event(data.get("ticket_id", "UNKNOWN"), "MANAGER: PAPER TRADE — DATABASE INSERT FAILED")
        return {"error": "Failed to insert paper trade to database", "id": None}
    
    # Notify active trade supervisor about the new pending trade
    notify_active_trade_supervisor_direct(trade_id, data.get("ticket_id", "PAPER"), "pending")
    
    # Immediately mark as open with fees = 0.00, using original buy_price
    try:
        pg_conn = get_postgresql_connection()
        if pg_conn:
            with pg_conn.cursor() as cursor:
                # Update to open status with fees = 0.00, order_id_open = NULL
                cursor.execute("""
                    UPDATE users.trades_0001 
                    SET status = 'open', 
                        fees = 0.00, 
                        order_id_open = NULL
                    WHERE id = %s
                """, (trade_id,))
                pg_conn.commit()
            pg_conn.close()
    except Exception as e:
        log(f"⚠️ Failed to update paper trade to open: {e}")
    
    log_event(data.get("ticket_id", "UNKNOWN"), "MANAGER: PAPER TRADE — OPENED IMMEDIATELY")
    
    # Notify active trade supervisor that trade is now open
    notify_active_trade_supervisor_direct(trade_id, data.get("ticket_id", "PAPER"), "open")
    
    return {"id": trade_id}
```

**Live Trade Logic (lines 2369-2399):**
```python
else:
    # LIVE TRADE: Send to executor as normal
    # IMMEDIATELY send to executor first
    try:
        import requests
        executor_port = get_executor_port()
        log(f"SENDING TO EXECUTOR")
        response = requests.post(f"http://localhost:{executor_port}/trigger_trade", json=data, timeout=5)
        log(f"EXECUTOR RESPONSE: {response.status_code}")
    except Exception as e:
        log(f"EXECUTOR ERROR: {e}")
        log_event(data.get("ticket_id", "UNKNOWN"), f"EXECUTOR ERROR: {e}")

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

**CRITICAL BUG FIX:** Line 2380 - `log_event` was outside the except block, causing NameError when executor call succeeded. Fixed by moving it inside the except block.

### 3. `add_trade()` Endpoint - CLOSE TRADE Section

**Location:** Lines ~2105-2311

**Changes:**
- Added paper_trade check at lines ~2113-2128
- Added paper trade close handling at lines ~2132-2251
- Modified live trade close section at lines ~2252-2299

**Paper Trade Close Logic (lines 2132-2251):**
```python
if paper_trade:
    # PAPER TRADE: Skip executor, mark as closing, then immediately finalize
    log(f"📝 PAPER TRADE CLOSE: Skipping executor, processing immediately")
    
    # Get current_close_price from request (sent as "buy_price" in payload)
    # Note: Frontend/ATS already calculates sell_price = 1 - current_close_price
    # So buy_price in payload is already the final sell_price we should use
    sell_price = data.get("buy_price")  # This is already 1 - current_close_price from frontend/ATS
    close_method = data.get("close_method", "manual")
    ticket_id = data.get("ticket_id")
    
    # Get symbol from trade to fetch one_minute_avg
    symbol = None
    try:
        pg_conn_symbol = get_postgresql_connection()
        if pg_conn_symbol:
            with pg_conn_symbol.cursor() as cursor:
                cursor.execute("SELECT symbol FROM users.trades_0001 WHERE id = %s", (trade_id,))
                result = cursor.fetchone()
                if result and result[0]:
                    symbol = result[0]
            pg_conn_symbol.close()
    except Exception as e:
        log(f"⚠️ Failed to get symbol for paper trade close: {e}")
    
    # Get one_minute_avg from live price log for symbol_close
    symbol_close = None
    if symbol:
        try:
            pg_conn_symbol = get_postgresql_connection()
            if pg_conn_symbol:
                with pg_conn_symbol.cursor() as cursor:
                    cursor.execute(f"SELECT one_minute_avg FROM live_data.live_price_log_1s_{symbol.lower()} ORDER BY timestamp DESC LIMIT 1")
                    result = cursor.fetchone()
                    if result and result[0] is not None:
                        symbol_close = float(result[0])
                        log(f"📝 PAPER TRADE: Retrieved one_minute_avg for close: {symbol_close}")
                    else:
                        # Fallback to current price if one_minute_avg not available
                        cursor.execute(f"SELECT price FROM live_data.live_price_log_1s_{symbol.lower()} ORDER BY timestamp DESC LIMIT 1")
                        fallback_result = cursor.fetchone()
                        if fallback_result and fallback_result[0] is not None:
                            symbol_close = float(fallback_result[0])
                            log(f"📝 PAPER TRADE: Using current price as fallback: {symbol_close}")
                pg_conn_symbol.close()
        except Exception as e:
            log(f"⚠️ Failed to get one_minute_avg from live price log: {e}")
    
    # Mark as closing first
    try:
        pg_conn_closing = get_postgresql_connection()
        if pg_conn_closing:
            with pg_conn_closing.cursor() as cursor:
                cursor.execute("UPDATE users.trades_0001 SET status = 'closing', symbol_close = %s, close_method = %s WHERE id = %s", (symbol_close, close_method, trade_id))
                pg_conn_closing.commit()
            pg_conn_closing.close()
    except Exception as pg_err:
        log(f"❌ Failed to update paper trade to closing: {pg_err}")
    
    # Notify active trade supervisor that it's closing
    notify_active_trade_supervisor_direct(trade_id, ticket_id, "closing")
    
    # Immediately finalize the trade
    try:
        now_est = datetime.now(ZoneInfo("America/New_York"))
        closed_at = now_est.strftime("%H:%M:%S")
        
        # Get trade data for calculations
        pg_conn_trade = get_postgresql_connection()
        if pg_conn_trade:
            with pg_conn_trade.cursor() as cursor:
                cursor.execute("SELECT buy_price, position, bankroll FROM users.trades_0001 WHERE id = %s", (trade_id,))
                trade_data = cursor.fetchone()
            pg_conn_trade.close()
        else:
            trade_data = None
        
        if trade_data and sell_price is not None:
            buy_price, position, bankroll = trade_data
            
            # Calculate PnL (fees = 0.00 for paper trades)
            fees = 0.00
            buy_value = buy_price * position
            sell_value_actual = sell_price * position # Use the already calculated sell_price
            pnl = round(sell_value_actual - (buy_price * position) - fees, 2)
            win_loss = "W" if pnl > 0 else "L" if pnl < 0 else "D"
            
            # Calculate ret_pct
            ret_pct = None
            if bankroll is not None and bankroll > 0:
                ret_pct = round((pnl / (bankroll / 100.0)) * 100, 5)
            
            # Get high_price and low_price from active_trades
            high_price, low_price = get_high_low_prices_from_active_trades(trade_id)
            
            # Update trade to closed with all calculated values
            update_trade_status_with_ret_pct(trade_id, "closed", closed_at, sell_price, symbol_close, win_loss, pnl, close_method, fees, ret_pct, high_price, low_price)
            
            # Set order_id_close to NULL for paper trades
            pg_conn_update = get_postgresql_connection()
            if pg_conn_update:
                with pg_conn_update.cursor() as cursor:
                    cursor.execute("UPDATE users.trades_0001 SET order_id_close = NULL WHERE id = %s", (trade_id,))
                    pg_conn_update.commit()
                pg_conn_update.close()
            
            log(f"📝 PAPER TRADE CLOSED: Trade {trade_id}, PnL=${pnl}, W/L={win_loss}, Fees=${fees}")
            log_event(ticket_id, f"MANAGER: PAPER TRADE CLOSED - PnL: ${pnl}, W/L: {win_loss}, Fees: ${fees}")
            
            # Notify active trade supervisor that it's closed
            notify_active_trade_supervisor_direct(trade_id, ticket_id, "closed")
            
            # Notify strike table for display update
            notify_strike_table_trade_change(trade_id, "closed")
        else:
            log(f"❌ Failed to finalize paper trade {trade_id}: missing trade data or sell_price")
            log_event(ticket_id, f"MANAGER: PAPER TRADE CLOSE FAILED - missing data")
    except Exception as e:
        log(f"❌ Error finalizing paper trade {trade_id}: {e}")
        log_event(ticket_id, f"MANAGER: PAPER TRADE CLOSE ERROR: {e}")
```

### 4. `confirm_close_trade()` Function

**Location:** Lines ~612-815

**Changes:**
- Modified to use `one_minute_avg` from live price log instead of API endpoint (lines ~712-732)

**Code:**
```python
# Get one_minute_avg from live price log for symbol_close
symbol_close = None
try:
    pg_conn_symbol = get_postgresql_connection()
    if pg_conn_symbol:
        with pg_conn_symbol.cursor() as cursor:
            cursor.execute(f"SELECT one_minute_avg FROM live_data.live_price_log_1s_{symbol.lower()} ORDER BY timestamp DESC LIMIT 1")
            result = cursor.fetchone()
            if result and result[0] is not None:
                symbol_close = float(result[0])
                log_event(ticket_id, f"MANAGER: Retrieved one_minute_avg for close: {symbol_close}")
            else:
                # Fallback to current price if one_minute_avg not available
                cursor.execute(f"SELECT price FROM live_data.live_price_log_1s_{symbol.lower()} ORDER BY timestamp DESC LIMIT 1")
                fallback_result = cursor.fetchone()
                if fallback_result and fallback_result[0] is not None:
                    symbol_close = float(fallback_result[0])
                    log_event(ticket_id, f"MANAGER: Using current price as fallback for close: {symbol_close}")
        pg_conn_symbol.close()
except Exception as e:
    log_event(ticket_id, f"MANAGER: Failed to get one_minute_avg from live price log: {e}")
```

### 5. `check_expired_trades()` Function

**Location:** Lines ~2663-2885

**Changes:**
- Modified to use `one_minute_avg` instead of `price` from live price log (lines ~2693-2704)
- Added paper trade separation logic (lines ~2742-2769)
- Added paper trade settlement logic (lines ~2771-2878)
- Modified live trade processing (lines ~2880-2882)

**Paper Trade Separation (lines 2742-2769):**
```python
# Separate paper trades from live trades
paper_trade_ids = []
live_trade_tickers = []

try:
    pg_conn_check = get_postgresql_connection()
    if pg_conn_check:
        with pg_conn_check.cursor() as cursor:
            for trade_id, ticker, symbol in active_trades:
                cursor.execute("SELECT paper_trade FROM users.trades_0001 WHERE id = %s", (trade_id,))
                result = cursor.fetchone()
                if result and result[0] is True:
                    paper_trade_ids.append((trade_id, ticker, symbol))
                else:
                    live_trade_tickers.append(ticker)
        pg_conn_check.close()
    else:
        # If we can't check, treat all as live trades
        for trade_id, ticker, symbol in active_trades:
            live_trade_tickers.append(ticker)
except Exception as e:
    log(f"⚠️ Error separating paper/live trades: {e}, treating all as live")
    for trade_id, ticker, symbol in active_trades:
        live_trade_tickers.append(ticker)

# Notify active_trade_supervisor for all expired trades (both paper and live)
for trade_id, ticker, symbol in active_trades:
    notify_active_trade_supervisor_direct(trade_id, str(ticker), "expired")
```

**Paper Trade Settlement Logic (lines 2771-2878):**
```python
# Process paper trades immediately (manual settlement)
if paper_trade_ids:
    log(f"📝 Processing {len(paper_trade_ids)} expired paper trades")
    for trade_id, ticker, symbol in paper_trade_ids:
        pg_conn_paper = None
        try:
            # Get trade data for settlement calculation
            pg_conn_paper = get_postgresql_connection()
            if not pg_conn_paper:
                log(f"⚠️ Cannot connect to PostgreSQL for paper trade {trade_id} settlement")
                continue
            
            with pg_conn_paper.cursor() as cursor:
                cursor.execute("""
                    SELECT strike, side, symbol_close, buy_price, position, bankroll, high_price, low_price
                    FROM users.trades_0001 
                    WHERE id = %s AND status = 'expired'
                """, (trade_id,))
                trade_data = cursor.fetchone()
            
            if not trade_data:
                log(f"⚠️ Paper trade {trade_id} not found or not expired")
                continue
            
            strike, side, symbol_close, buy_price, position, bankroll, high_price, low_price = trade_data
            
            if symbol_close is None:
                log(f"⚠️ Paper trade {trade_id} has no symbol_close, skipping settlement")
                continue
            
            # Clean strike (remove $ and commas)
            strike_clean = str(strike).replace('$', '').replace(',', '')
            strike_float = float(strike_clean)
            symbol_close_float = float(symbol_close)
            
            # Determine winner/loser based on strike and side
            is_winner = False
            if side and side.upper() in ('Y', 'YES'):
                # YES trade: WINNER if symbol_close >= strike
                is_winner = symbol_close_float >= strike_float
            elif side and side.upper() in ('N', 'NO'):
                # NO trade: WINNER if symbol_close <= strike
                is_winner = symbol_close_float <= strike_float
            else:
                log(f"⚠️ Paper trade {trade_id} has invalid side: {side}")
                continue
            
            # Set sell_price: 1.0000 for winners, 0.0000 for losers
            sell_price = 1.0000 if is_winner else 0.0000
            fees = 0.00
            
            # Calculate PnL
            pnl = None
            if buy_price is not None and position is not None:
                buy_value = buy_price * position
                sell_value = sell_price * position
                pnl = round(sell_value - buy_value - fees, 2)
            
            # Determine win_loss
            win_loss = "W" if is_winner else "L"
            
            # Calculate ret_pct
            ret_pct = None
            if bankroll is not None and bankroll > 0 and pnl is not None:
                ret_pct = round((pnl / (bankroll / 100.0)) * 100, 5)
            
            # Finalize the trade
            now_est = datetime.now(ZoneInfo("America/New_York"))
            closed_at = now_est.strftime("%H:%M:%S")
            
            update_trade_status_with_ret_pct(
                trade_id=trade_id,
                status="closed",
                closed_at=closed_at,
                sell_price=sell_price,
                symbol_close=symbol_close,
                win_loss=win_loss,
                pnl=pnl,
                close_method="expired",
                fees=fees,
                ret_pct=ret_pct,
                high_price=high_price,
                low_price=low_price
            )
            
            # Set order_id_close to NULL for paper trades
            if pg_conn_paper:
                with pg_conn_paper.cursor() as cursor:
                    cursor.execute("UPDATE users.trades_0001 SET order_id_close = NULL WHERE id = %s", (trade_id,))
                    pg_conn_paper.commit()
            
            log(f"📝 PAPER TRADE SETTLED: Trade {trade_id}, {ticker}, W/L={win_loss}, PnL=${pnl}, Sell=${sell_price}, SymbolClose=${symbol_close_float}, Strike=${strike_float}")
            
            # Notify active trade supervisor that it's closed
            notify_active_trade_supervisor_direct(trade_id, str(ticker), "closed")
            
            # Notify strike table for display update
            notify_strike_table_trade_change(trade_id, "closed")
            
        except Exception as e:
            log(f"❌ Error processing paper trade {trade_id} settlement: {e}")
        finally:
            # Always close the connection if it was opened
            if pg_conn_paper:
                try:
                    pg_conn_paper.close()
                except:
                    pass
```

**Live Trade Processing (lines 2880-2882):**
```python
# Process live trades with normal settlement polling
if live_trade_tickers:
    poll_settlements_for_matches(live_trade_tickers)
```

**One Minute Avg Change (lines 2693-2704):**
```python
# Get one_minute_avg from symbol-specific price log
pg_conn = get_postgresql_connection()
if pg_conn:
    with pg_conn.cursor() as cursor:
        cursor.execute(f"SELECT one_minute_avg FROM live_data.live_price_log_1s_{symbol.lower()} ORDER BY timestamp DESC LIMIT 1")
        result = cursor.fetchone()
        if result and result[0] is not None:
            symbol_prices[symbol] = float(result[0])
        else:
            # Fallback to current price if one_minute_avg not available
            cursor.execute(f"SELECT price FROM live_data.live_price_log_1s_{symbol.lower()} ORDER BY timestamp DESC LIMIT 1")
            fallback_result = cursor.fetchone()
            if fallback_result and fallback_result[0] is not None:
                symbol_prices[symbol] = float(fallback_result[0])
            else:
                symbol_prices[symbol] = None
    pg_conn.close()
```

---

## Backend Changes - Auto Entry Supervisor

### File: `backend/auto_entry_supervisor.py`

### 1. `trigger_auto_entry_trade()` Function

**Location:** Lines ~1919-2116

**Changes:**
- Added paper_trade fetching from monitor config (lines ~1949-1962)
- Added paper_trade to trade_payload (line ~2070)
- Added diff to trade_payload (line ~2069)

**Code:**
```python
# Get paper_trade setting from monitor config
paper_trade = False
try:
    import psycopg2
    conn = psycopg2.connect(
        host=os.getenv('POSTGRES_HOST', 'localhost'),
        database=os.getenv('POSTGRES_DB', 'rec_io_db'),
        user=os.getenv('POSTGRES_USER', 'rec_io_user'),
        password=os.getenv('POSTGRES_PASSWORD', 'rec_io_password')
    )
    with conn.cursor() as cursor:
        cursor.execute(f"SELECT paper_trade FROM users.monitor_list_{USER_NUMBER} WHERE id = %s", (MONITOR_ID,))
        result = cursor.fetchone()
        if result and result[0] is not None:
            paper_trade = bool(result[0])
    conn.close()
except Exception as e:
    log(f"[AUTO ENTRY] ⚠️ Could not get paper_trade setting: {e}, defaulting to False")

# In trade_payload:
trade_payload = {
    ...
    "diff": strike_data.get("diff"),
    "paper_trade": paper_trade
}
```

### 2. `get_trade_strategy()` Function

**Location:** Lines ~1823-1848

**Changes:**
- Removed log statement that was logging every second (line ~1838)

**Before:**
```python
log(f"[AUTO ENTRY] Trade strategy loaded from monitor {MONITOR_ID}: {trade_strategy}")
```

**After:**
```python
# Log statement removed - function called too frequently
```

### 3. Logging Path Fix

**Location:** Lines ~661-678

**Changes:**
- Changed from hardcoded `/opt/rec_io_server/logs/` to server-agnostic `get_logs_dir()`
- Added directory creation with `os.makedirs(logs_dir, exist_ok=True)`

**Before:**
```python
log_file_path = f"/opt/rec_io_server/logs/auto_entry_supervisor_{MONITOR_IDENTIFIER}.log"
```

**After:**
```python
logs_dir = get_logs_dir()
os.makedirs(logs_dir, exist_ok=True)  # Create directory if it doesn't exist
log_file_path = os.path.join(logs_dir, f"auto_entry_supervisor_{MONITOR_IDENTIFIER}.log")
```

**Import Added:**
```python
from backend.util.paths import get_host, get_data_dir, get_service_url, get_trade_history_dir, get_logs_dir
```

### 4. Diagnostic Logging Added

**Location:** Lines ~2225-2238, ~2214-2215, ~2222-2223

**Changes:**
- Added periodic logging for strike scanning (every 60 seconds)
- Added periodic logging for TTC outside window (every 5 minutes)
- Added periodic logging for missing strike table data (every 60 seconds)
- Enhanced exception logging with full tracebacks

**Code:**
```python
# Log that we're scanning strikes (only log occasionally to avoid spam)
import time
current_time = time.time()
if not hasattr(check_auto_entry_conditions_hourly_htc, 'last_scan_log'):
    check_auto_entry_conditions_hourly_htc.last_scan_log = 0
if current_time - check_auto_entry_conditions_hourly_htc.last_scan_log >= 60:  # Log every 60 seconds
    strike_count = len(strike_table_data.get("strikes", []))
    log(f"[AUTO ENTRY] 🔍 Scanning {strike_count} strikes | TTC: {current_ttc}s | Window: {min_time}-{max_time}s | Prob: {min_probability}-{max_probability}%")
    check_auto_entry_conditions_hourly_htc.last_scan_log = current_time
```

---

## Backend Changes - Active Trade Supervisor

### File: `backend/active_trade_supervisor.py`

### 1. `trigger_auto_stop_close()` Function

**Location:** Lines ~1050-1150 (approximate, need to verify exact location)

**Changes:**
- Modified to calculate `sell_price = 1 - current_close_price` for paper trades

**Code:**
```python
# For paper trades, calculate sell_price as 1 - current_close_price
if trade.get('paper_trade'):
    current_close_price = trade.get('current_close_price')
    if current_close_price is not None:
        sell_price = 1 - float(current_close_price)
    else:
        sell_price = None
else:
    sell_price = data.get("buy_price")  # For live trades, use provided sell_price
```

**Note:** Exact location needs verification - this change was made to handle paper trade auto-stop closes.

---

## Backend Changes - Main App

### File: `backend/main.py`

### 1. `trigger_open_trade` Endpoint

**Location:** Lines ~1500-1600 (approximate)

**Changes:**
- Added extraction of `paper_trade` and `diff` from request body
- Added `paper_trade` and `diff` to trade_data forwarded to trade_manager

**Code:**
```python
paper_trade = data.get("paper_trade", False)
diff = data.get("diff")

trade_data = {
    ...
    "diff": diff,
    "paper_trade": paper_trade
}
```

### 2. `get_monitors` Endpoint

**Location:** Lines ~800-900 (approximate)

**Changes:**
- Added `paper_trade` to SELECT query
- Added `paper_trade` to formatted_monitor dictionary

**Code:**
```python
cursor.execute("""
    SELECT id, name, symbol, strategy, auto_trade, auto_trade_status, 
           trades, win_loss, ret_pct, pnl, bankroll_allotment_pct, 
           status, created, bankroll_allotment_total, position_size, 
           position_type, multiplier, total_position, dashboard_order, 
           cooldown_timer, cooldown_start_time, updated_at, 
           created_strategy, updated_strategy, default_strategy, 
           min_probability, min_differential, min_time, max_time, 
           allow_re_entry, spike_alert_enabled, spike_alert_momentum_threshold, 
           spike_alert_cooldown_threshold, spike_alert_cooldown_minutes, 
           current_probability, min_ttc_seconds, momentum_spike_enabled, 
           momentum_spike_threshold, user_id_strategy, 
           verification_period_enabled, verification_period_seconds, 
           min_volume, max_differential, win_streak, loss_prevention, 
           win_streak_threshold, last_processed_cycle, 
           momentum_scalp_entry_threshold, momentum_scalp_trailing_stop_amount, 
           momentum_scalp_profit_target, min_ask, max_ask, max_profit, 
           loss_prevention_toggle, max_probability, current_contract, 
           current_weekly_cycle, current_performance_modifier, 
           current_max_pct_exposure, performance_based_allocation, 
           max_price_spread, paper_trade
    FROM users.monitor_list_0001
    WHERE status = 'active'
    ORDER BY dashboard_order ASC, id ASC
""")

# In formatted_monitor:
formatted_monitor = {
    ...
    "paper_trade": row[XX]  # Add paper_trade field
}
```

### 3. `get_monitor_details` Endpoint

**Location:** Lines ~4986-5050 (approximate)

**Changes:**
- Added `paper_trade` to SELECT query
- Added `paper_trade` to monitor dictionary returned

**Code:**
```python
cursor.execute("""
    SELECT id, name, symbol, strategy, auto_trade, auto_trade_status, 
           ... paper_trade
    FROM users.monitor_list_0001
    WHERE id = %s
""", (monitor_id,))

# In monitor dictionary:
monitor = {
    ...
    "paper_trade": row[XX]
}
```

### 4. `toggle_paper_trade` Endpoint

**Location:** Lines ~5100-5200 (approximate)

**Changes:**
- New endpoint to toggle paper_trade boolean
- Handles different monitor ID formats
- Broadcasts WebSocket message on change

**Code:**
```python
@app.post("/api/monitor/toggle-paper-trade")
async def toggle_paper_trade(request: Request):
    data = await request.json()
    monitor_id_raw = data.get("monitor_id")
    paper_trade = data.get("paper_trade", False)
    
    # Extract numeric monitor ID from format like "MON_0001_10019" or "10019"
    if isinstance(monitor_id_raw, str) and '_' in monitor_id_raw:
        parts = monitor_id_raw.split('_')
        if len(parts) >= 3:
            monitor_id = int(parts[-1])
        else:
            monitor_id = int(monitor_id_raw)
    else:
        monitor_id = int(monitor_id_raw) if monitor_id_raw else None
    
    if monitor_id is None:
        return {"status": "error", "message": "Invalid monitor_id"}
    
    # Extract user number
    user_number = "0001"  # Default, or extract from monitor_id format
    
    try:
        conn = get_postgresql_connection()
        if conn:
            with conn.cursor() as cursor:
                cursor.execute(f"""
                    UPDATE users.monitor_list_{user_number}
                    SET paper_trade = %s, updated_at = CURRENT_TIMESTAMP
                    WHERE id = %s
                """, (paper_trade, monitor_id))
                conn.commit()
            conn.close()
        
        # Broadcast WebSocket message
        await broadcast_preferences_update(
            {"type": "paper_trade_toggled", "monitor_id": monitor_id, "paper_trade": paper_trade}
        )
        
        return {"status": "ok", "paper_trade": paper_trade}
    except Exception as e:
        return {"status": "error", "message": str(e)}
```

---

## Frontend Changes - Dashboard

### File: `frontend/tabs/dashboard.html`

### 1. CSS Styling

**Location:** Lines ~400-450 (approximate)

**Changes:**
- Added `.monitor-tile.paper-trading-active` class with inset box-shadow for green border
- Added `.paper-trading-button` styles for active/inactive states

**Code:**
```css
.monitor-tile.paper-trading-active {
    box-shadow: inset 0 0 0 2px #48bb78;
}

.paper-trading-button {
    padding: 4px 12px;
    border-radius: 4px;
    border: 1px solid #4a5568;
    background-color: #2d3748;
    color: #a0aec0;
    font-size: 0.85rem;
    cursor: pointer;
    transition: all 0.2s;
}

.paper-trading-button.active {
    background-color: #48bb78;
    color: white;
    border-color: #48bb78;
}

.paper-trading-button:hover {
    background-color: #38a169;
    border-color: #38a169;
}
```

### 2. HTML Structure

**Location:** Lines ~600-700 (approximate, in monitor tile rendering)

**Changes:**
- Added `paper-trading-button` to bottom row of monitor tiles
- Added conditional `paper-trading-active` class to monitor-tile

**Code:**
```html
<div class="monitor-tile ${monitor.paper_trade ? 'paper-trading-active' : ''}">
    ...
    <div class="monitor-bottom-row">
        <div class="monitor-uptime">${uptimeText}</div>
        <button class="paper-trading-button ${monitor.paper_trade ? 'active' : ''}" 
                onclick="togglePaperTrade('${monitor.id}')">
            PAPER TRADING
        </button>
        <div class="monitor-name">${monitor.name}</div>
    </div>
</div>
```

### 3. JavaScript Functions

**Location:** Lines ~1500-1700 (approximate)

**Changes:**
- Added `togglePaperTrade()` function
- Added WebSocket handler for `paper_trade_toggled` messages

**Code:**
```javascript
async function togglePaperTrade(monitorId) {
    try {
        // Extract numeric ID from format like "mon_0001_10019"
        const parts = monitorId.split('_');
        const numericId = parts.length >= 3 ? parts[2] : monitorId;
        const formattedMonitorId = `MON_0001_${numericId}`;
        
        // Get current state
        const monitor = monitors.find(m => m.id === monitorId);
        const currentPaperTrade = monitor ? monitor.paper_trade : false;
        const newPaperTrade = !currentPaperTrade;
        
        // Optimistically update UI
        updatePaperTradingUI(monitorId, newPaperTrade);
        
        // Send API request
        const response = await fetch('/api/monitor/toggle-paper-trade', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                monitor_id: formattedMonitorId,
                paper_trade: newPaperTrade
            })
        });
        
        const data = await response.json();
        if (data.status !== 'ok') {
            // Revert UI on error
            updatePaperTradingUI(monitorId, currentPaperTrade);
            console.error('Failed to toggle paper trade:', data.message);
        }
    } catch (error) {
        console.error('Error toggling paper trade:', error);
    }
}

function updatePaperTradingUI(monitorId, paperTrade) {
    const tile = document.querySelector(`[data-monitor-id="${monitorId}"]`);
    if (tile) {
        if (paperTrade) {
            tile.classList.add('paper-trading-active');
        } else {
            tile.classList.remove('paper-trading-active');
        }
        
        const button = tile.querySelector('.paper-trading-button');
        if (button) {
            if (paperTrade) {
                button.classList.add('active');
            } else {
                button.classList.remove('active');
            }
        }
    }
}

// WebSocket handler
if (ws && ws.readyState === WebSocket.OPEN) {
    ws.addEventListener('message', (event) => {
        const data = JSON.parse(event.data);
        if (data.type === 'paper_trade_toggled') {
            const monitorId = `mon_0001_${data.monitor_id}`;
            updatePaperTradingUI(monitorId, data.paper_trade);
        }
    });
}
```

---

## Frontend Changes - Dashboard Mobile

### File: `frontend/mobile/dashboard_mobile.html`

**Changes:** Identical to dashboard.html changes:
- Same CSS styling for paper-trading-active and paper-trading-button
- Same HTML structure in monitor tile rendering
- Same JavaScript functions (togglePaperTrade, updatePaperTradingUI)
- Same WebSocket handler

**Location:** Similar line ranges as dashboard.html

---

## Frontend Changes - Trade Monitor

### File: `frontend/tabs/trade_monitor.html`

### 1. HTML Structure

**Location:** Lines ~1300-1350 (approximate)

**Changes:**
- Added `id="accountPanel"` to account panel
- Added `id="watchlistPanel"` to watchlist panel
- Added `paper-trading-button` next to account dropdown

**Code:**
```html
<div id="accountPanel" class="panel">
    ...
    <select id="account-selector">...</select>
    <button class="paper-trading-button" onclick="togglePaperTrade()">PAPER TRADING</button>
</div>

<div id="watchlistPanel" class="panel">
    ...
</div>
```

### 2. CSS Styling

**Location:** Lines ~400-500 (approximate)

**Changes:**
- Added `.paper-trading-button` styles
- Added `#accountPanel.paper-trading-active` and `#watchlistPanel.paper-trading-active` with inset box-shadow

**Code:**
```css
.paper-trading-button {
    padding: 6px 12px;
    border-radius: 4px;
    border: 1px solid #4a5568;
    background-color: #2d3748;
    color: #a0aec0;
    font-size: 0.9rem;
    cursor: pointer;
    transition: all 0.2s;
    margin-left: 10px;
}

.paper-trading-button.active {
    background-color: #48bb78;
    color: white;
    border-color: #48bb78;
}

#accountPanel.paper-trading-active,
#watchlistPanel.paper-trading-active {
    box-shadow: inset 0 0 0 2px #48bb78;
}
```

### 3. JavaScript Functions

**Location:** Lines ~1600-1750 (approximate)

**Changes:**
- Added `currentPaperTrade` variable (made global as `window.currentPaperTrade`)
- Added `updatePaperTradingUI()` function (made global as `window.updatePaperTradingUI`)
- Added `fetchPaperTradeStatus()` function (made global as `window.fetchPaperTradeStatus`)
- Added `togglePaperTrade()` function
- Modified `loadMonitorDetails()` to set paper_trade status on page load
- Added WebSocket handler for `paper_trade_toggled` messages

**Code:**
```javascript
let currentPaperTrade = false;
window.currentPaperTrade = false;

function updatePaperTradingUI(paperTrade) {
    currentPaperTrade = paperTrade;
    window.currentPaperTrade = paperTrade;
    
    const button = document.querySelector('.paper-trading-button');
    if (button) {
        if (paperTrade) {
            button.classList.add('active');
            document.getElementById('accountPanel')?.classList.add('paper-trading-active');
            document.getElementById('watchlistPanel')?.classList.add('paper-trading-active');
        } else {
            button.classList.remove('active');
            document.getElementById('accountPanel')?.classList.remove('paper-trading-active');
            document.getElementById('watchlistPanel')?.classList.remove('paper-trading-active');
        }
    }
}
window.updatePaperTradingUI = updatePaperTradingUI;

async function fetchPaperTradeStatus() {
    try {
        if (!window.currentMonitorId) {
            return false;
        }
        
        const response = await fetch(`${window.location.origin}/api/monitors?user_id=user_0001`);
        const data = await response.json();
        
        if (data.status === 'ok' && data.monitors) {
            const monitor = data.monitors.find(m => m.id === window.currentMonitorId);
            if (monitor) {
                const paperTrade = monitor.paper_trade === true || monitor.paper_trade === 'true' || monitor.paper_trade === 1;
                updatePaperTradingUI(paperTrade);
                return paperTrade;
            }
        }
        return false;
    } catch (error) {
        console.error('Error fetching paper trade status:', error);
        return false;
    }
}
window.fetchPaperTradeStatus = fetchPaperTradeStatus;

async function togglePaperTrade() {
    try {
        if (!window.currentMonitorId) {
            console.error('No current monitor ID, cannot toggle paper trade');
            return;
        }
        
        const newPaperTrade = !currentPaperTrade;
        
        // Optimistically update UI
        updatePaperTradingUI(newPaperTrade);
        
        // Extract numeric monitor ID from mon_0001_10002 format and convert to MON_0001_10002 format
        const numericId = window.currentMonitorId.split('_').pop();
        const formattedMonitorId = `MON_0001_${numericId}`;
        
        const response = await fetch('/api/monitor/toggle-paper-trade', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                monitor_id: formattedMonitorId,
                paper_trade: newPaperTrade
            })
        });
        
        const data = await response.json();
        if (data.status !== 'ok') {
            // Revert UI on error
            updatePaperTradingUI(!newPaperTrade);
            console.error('Failed to toggle paper trade:', data.message);
        }
    } catch (error) {
        console.error('Error toggling paper trade:', error);
    }
}

// In loadMonitorDetails function:
async function loadMonitorDetails(monitorId) {
    ...
    if (data.status === 'ok' && data.monitor) {
        const monitor = data.monitor;
        ...
        // Set paper_trade status
        if ('paper_trade' in monitor) {
            const paperTrade = monitor.paper_trade === true || monitor.paper_trade === 'true' || monitor.paper_trade === 1;
            updatePaperTradingUI(paperTrade);
        }
        ...
    }
}

// WebSocket handler
if (ws && ws.readyState === WebSocket.OPEN) {
    ws.addEventListener('message', (event) => {
        const data = JSON.parse(event.data);
        if (data.type === 'paper_trade_toggled') {
            if (window.currentMonitorId && window.currentMonitorId.includes(data.monitor_id.toString())) {
                updatePaperTradingUI(data.paper_trade);
            }
        }
    });
}
```

### 4. Manual Close Button Update

**Location:** Lines ~2000-2100 (approximate, in renderTrades function)

**Changes:**
- Modified manual close button onclick to pass `current_close_price` from trade object

**Code:**
```javascript
closeBtn.onclick = function() { 
    // Pass the current_close_price from the trade object
    closeTrade(trade.id, trade.current_close_price, event); 
};
```

---

## Frontend Changes - JavaScript Files

### File: `frontend/js/trade-execution-controller.js`

### 1. `prepareTradeData()` Function

**Location:** Lines ~100-250 (approximate)

**Changes:**
- Added fetching of `paper_trade` from monitor API response
- Added extraction of `diff` from button's `data-diff` attribute
- Added `paper_trade` and `diff` to tradeData object

**Code:**
```javascript
let paperTrade = false;
let diffValue = null;

try {
    const monitorResponse = await fetch(`${window.location.origin}/api/monitors?user_id=user_0001`);
    const monitorData = await monitorResponse.json();
    
    if (monitorData.status === 'ok' && monitorData.monitors) {
        const monitor = monitorData.monitors.find(m => m.id === window.currentMonitorId);
        if (monitor) {
            paperTrade = monitor.paper_trade || false;
        }
    }
} catch (error) {
    console.error('Error fetching monitor data:', error);
}

// Get diff from data attribute
const diffAttr = target.getAttribute('data-diff');
if (diffAttr) {
    diffValue = parseFloat(diffAttr);
}

const tradeData = {
    ...
    "diff": diffValue,
    "paper_trade": paperTrade
};
```

### 2. `window.closeTrade()` Function

**Location:** Lines ~400-600 (approximate)

**Changes:**
- Added logic to fetch `current_close_price` from active trades API for paper trades
- Calculate `finalSellPrice = 1 - current_close_price` for paper trades
- Use `finalSellPrice` in payload instead of symbol price

**Code:**
```javascript
// For paper trades, fetch current_close_price from active trades instead of using symbol price
let finalSellPrice = sellPrice;
if (trade.paper_trade) {
    try {
        // Get current monitor name for monitor-specific active trades
        const currentMonitorName = window.currentMonitorName;
        if (currentMonitorName) {
            const activeTradesUrl = window.location.origin + `/api/active_trades/${currentMonitorName}`;
            const activeTradesRes = await fetch(activeTradesUrl, { cache: 'no-store' });
            if (activeTradesRes.ok) {
                const activeTradesData = await activeTradesRes.json();
                if (activeTradesData.active_trades && Array.isArray(activeTradesData.active_trades)) {
                    const activeTrade = activeTradesData.active_trades.find(t => t.trade_id == tradeId);
                    if (activeTrade && activeTrade.current_close_price !== null && activeTrade.current_close_price !== undefined) {
                        // Calculate sell_price as 1 - current_close_price
                        finalSellPrice = 1 - parseFloat(activeTrade.current_close_price);
                        console.log(`[PAPER TRADE] Using calculated sell_price (1 - current_close_price) from active trades: ${finalSellPrice}`);
                    }
                }
            }
        }
    } catch (error) {
        console.warn(`[PAPER TRADE] Could not fetch current_close_price from active trades: ${error}, using provided sellPrice`);
    }
}

// Compose payload
const payload = {
    ...
    "buy_price": finalSellPrice,  // Use finalSellPrice (1 - current_close_price for paper trades)
    ...
};
```

### File: `frontend/js/strike-table.js`

### 1. `updateYesNoButton()` Function

**Location:** Lines ~500-700 (approximate)

**Changes:**
- Added `data-diff` attribute to button elements
- Added `diff` and `paper_trade` to JSON payload sent to `/api/trigger_open_trade`

**Code:**
```javascript
// Store diff value as a data attribute
if (diffValue !== null) {
    spanEl.setAttribute('data-diff', diffValue);
} else {
    spanEl.removeAttribute('data-diff');
}

// In onclick handler:
body: JSON.stringify({
    ...
    "diff": tradeData.diff,
    "paper_trade": tradeData.paper_trade
})
```

### File: `frontend/js/watchlist-table.js`

### 1. `updateWatchlistBuyButton()` Function

**Location:** Lines ~400-600 (approximate)

**Changes:**
- Added `data-diff` attribute to button elements
- Added `diff` and `paper_trade` to JSON payload sent to `/api/trigger_open_trade`

**Code:**
```javascript
// Store diff value as a data attribute
if (diffValue !== null) {
    spanEl.setAttribute('data-diff', diffValue);
} else {
    spanEl.removeAttribute('data-diff');
}

// In onclick handler:
body: JSON.stringify({
    ...
    "diff": tradeData.diff,
    "paper_trade": tradeData.paper_trade
})
```

### File: `frontend/js/active-trade-supervisor_panel.js`

### 1. `closeActiveTrade()` Function

**Location:** Lines ~800-1000 (approximate)

**Changes:**
- Modified to accept `currentClosePrice` parameter
- Calculate `sellPrice = 1 - parseFloat(currentClosePrice)` for paper trades
- Pass calculated `sellPrice` to `window.closeTrade()`

**Code:**
```javascript
async function closeActiveTrade(tradeId, ticketId, currentClosePrice = null) {
    try {
        if (typeof window.closeTrade === 'function') {
            let sellPrice;
            if (currentClosePrice !== null && currentClosePrice !== undefined) {
                // Calculate sell_price as 1 - current_close_price
                sellPrice = 1 - parseFloat(currentClosePrice);
                console.log(`[ACTIVE TRADE SUPERVISOR] Using calculated sell_price (1 - current_close_price): ${sellPrice}`);
            } else {
                // Fallback to symbol price for live trades (should not happen for paper trades)
                sellPrice = typeof getCurrentSymbolTickerPrice === 'function' ? getCurrentSymbolTickerPrice() : 
                            (typeof getCurrentBTCTickerPrice === 'function' ? getCurrentBTCTickerPrice() : 0.5);
            }
            
            await window.closeTrade(tradeId, sellPrice, mockEvent);
        }
    } catch (error) {
        console.error('Error closing active trade:', error);
    }
}

// In renderActiveTradeSupervisorTrades, onclick handler:
closeSpan.onclick = () => closeActiveTrade(trade.trade_id, trade.ticket_id, trade.current_close_price);
```

---

## Known Issues and Bugs

### 1. Live Trading Broken

**Issue:** Live trades are not being recorded in the database or sent to active_trade_supervisor.

**Root Cause:** Line 2380 in `trade_manager.py` - `log_event` was outside the except block, causing NameError when executor call succeeded, preventing trade insertion.

**Fix Applied:** Moved `log_event` inside the except block.

**Status:** Fixed

### 2. Position Sizer Not Updating total_position

**Issue:** `total_position` column not updating when `position_size` or `multiplier` changes.

**Root Cause:** `monitor_id` was being sent as `"mon_0001_10019"` but backend was using it directly as integer in SQL query.

**Fix Applied:** Added parsing to extract numeric ID from monitor_id format.

**Status:** Fixed

### 3. Auto Entry Supervisor Logging Issues

**Issue:** 
- Log file path was hardcoded to `/opt/rec_io_server/logs/`
- `get_trade_strategy()` was logging every second
- No diagnostic logging to show why auto entry isn't working

**Fixes Applied:**
- Changed to use `get_logs_dir()` for server-agnostic path
- Removed log statement from `get_trade_strategy()`
- Added periodic diagnostic logging

**Status:** Fixed

### 4. Auto Entry Supervisor Not Running

**Issue:** Auto entry supervisor starts but shows no activity logs, not scanning strikes.

**Potential Causes:**
- Function returning early without logging (TTC outside window, missing strike data, etc.)
- Exceptions being silently caught
- Missing settings causing early return

**Fixes Applied:**
- Added periodic logging for TTC outside window (every 5 minutes)
- Added periodic logging for missing strike table data (every 60 seconds)
- Added periodic logging for strike scanning (every 60 seconds)
- Enhanced exception logging with full tracebacks

**Status:** Diagnostic logging added, root cause not yet identified

### 5. Paper Trade Sell Price Calculation

**Issue:** Initially, `sell_price` was being recorded incorrectly for paper trades.

**Root Cause:** Frontend was sending symbol price instead of calculated `1 - current_close_price`.

**Fix Applied:**
- Modified `window.closeTrade()` to fetch `current_close_price` from active trades API
- Calculate `finalSellPrice = 1 - parseFloat(current_close_price)`
- Modified `closeActiveTrade()` to pass `current_close_price` and calculate `sellPrice`
- Modified `active_trade_supervisor.py` to calculate `sell_price = 1 - current_close_price` for auto-stop

**Status:** Fixed

### 6. Diff Not Recorded

**Issue:** `diff` value was not being recorded in trades table for paper trades.

**Root Cause:** `diff` was not being passed through the entire chain from frontend to database.

**Fix Applied:**
- Added `data-diff` attribute to strike table and watchlist buttons
- Added `diff` extraction in `prepareTradeData()`
- Added `diff` to trade payloads in `strike-table.js` and `watchlist-table.js`
- Added `diff` extraction in `main.py` `trigger_open_trade` endpoint
- Confirmed `auto_entry_supervisor.py` already included `diff`

**Status:** Fixed

---

## Reversion Checklist

If reverting all paper trading changes, follow this order:

1. **Database Schema:**
   - Remove `paper_trade` column from `users.trades_0001`
   - Remove `paper_trade` column from all `users.monitor_list_XXXX` tables
   - Update `MASTER_DB_SCHEMA_REFERENCE.md`

2. **Backend - Trade Manager:**
   - Remove paper_trade extraction from `insert_trade()`
   - Remove paper trade handling from `add_trade()` OPEN section
   - Remove paper trade handling from `add_trade()` CLOSE section
   - Remove paper trade settlement logic from `check_expired_trades()`
   - Revert `one_minute_avg` changes (if desired) or keep them

3. **Backend - Auto Entry Supervisor:**
   - Remove paper_trade fetching and inclusion in trade_payload
   - Revert logging path changes (if reverting to hardcoded path)
   - Remove diagnostic logging (if not desired)

4. **Backend - Active Trade Supervisor:**
   - Remove paper trade sell_price calculation logic

5. **Backend - Main App:**
   - Remove `paper_trade` from `get_monitors` endpoint
   - Remove `paper_trade` from `get_monitor_details` endpoint
   - Remove `toggle_paper_trade` endpoint
   - Remove `paper_trade` and `diff` from `trigger_open_trade` endpoint

6. **Frontend - Dashboard:**
   - Remove CSS for paper-trading-active and paper-trading-button
   - Remove HTML button from monitor tiles
   - Remove JavaScript functions and WebSocket handlers

7. **Frontend - Dashboard Mobile:**
   - Same as Dashboard

8. **Frontend - Trade Monitor:**
   - Remove CSS for paper-trading-active
   - Remove HTML button
   - Remove JavaScript functions and WebSocket handlers
   - Revert manual close button changes

9. **Frontend - JavaScript Files:**
   - Remove `paper_trade` and `diff` from `trade-execution-controller.js`
   - Remove `data-diff` attributes and `diff`/`paper_trade` from `strike-table.js`
   - Remove `data-diff` attributes and `diff`/`paper_trade` from `watchlist-table.js`
   - Revert `closeActiveTrade()` changes in `active-trade-supervisor_panel.js`

---

## Testing Checklist

When re-implementing, test at each step:

1. **Database:** Verify columns exist and have correct defaults
2. **Trade Entry:** Test paper trade entry from UI and auto_entry
3. **Trade Closing:** Test manual close and auto-stop close for paper trades
4. **Trade Expiration:** Test paper trade expiration and settlement
5. **UI Toggle:** Test paper trading button on all three pages
6. **WebSocket Sync:** Test that toggling on one page updates others
7. **Live Trading:** Verify live trades still work correctly
8. **Position Sizer:** Verify total_position updates correctly
9. **Auto Entry:** Verify auto entry supervisor is scanning and logging

---

## Critical Dependencies

- `paper_trade` must be passed from entry point (UI or auto_entry) through to trade_manager
- `diff` must be passed along with `paper_trade` for complete trade records
- `current_close_price` must be available for paper trade closes (from active_trades API)
- `one_minute_avg` must be available in `live_data.live_price_log_1s_{symbol}` tables
- WebSocket system must be functional for UI synchronization
- Monitor ID parsing must handle both `"mon_0001_10019"` and `"10019"` formats

---

## Notes

- All changes maintain backward compatibility (paper_trade defaults to FALSE)
- Paper trades do not trigger `kalshi_account_sync` activity
- Paper trades use `fees = 0.00` and `order_id_open = NULL` / `order_id_close = NULL`
- Paper trade expiration settlement uses manual winner/loser determination based on strike and symbol_close
- The `one_minute_avg` change affects both paper and live trades (used for symbol_close recording)


