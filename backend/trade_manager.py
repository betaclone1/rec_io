
import threading
import time
import os
import sys
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import re
import requests
import psycopg2
from psycopg2.extras import RealDictCursor

# Import the universal centralized port system
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from backend.core.port_config import get_port, get_port_info
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from backend.util.paths import get_project_root, get_trade_history_dir, get_logs_dir, get_host, get_data_dir
from backend.account_mode import get_account_mode
from backend.util.paths import get_accounts_data_dir
# Function to get momentum data from PostgreSQL (replacement for archived unified_production_coordinator)
def get_momentum_data_from_postgresql():
    """Get current momentum data directly from PostgreSQL."""
    try:
        import psycopg2
        conn = psycopg2.connect(
            host="localhost",
            database="rec_io_db",
            user="rec_io_user",
            password="rec_io_password"
        )
        cursor = conn.cursor()
        cursor.execute("SELECT momentum FROM live_data.live_price_log_1s_btc ORDER BY timestamp DESC LIMIT 1")
        result = cursor.fetchone()
        conn.close()
        
        if result and result[0] is not None:
            momentum_score = float(result[0])
            return {
                "weighted_momentum_score": momentum_score
            }
        else:
            return {
                "weighted_momentum_score": 0
            }
    except Exception as e:
        print(f"Error getting momentum from PostgreSQL: {e}")
        return {
            "weighted_momentum_score": 0
        }

# Get port from centralized system
TRADE_MANAGER_PORT = get_port("trade_manager")

# Thread-safe set to track trades being processed
processing_trades = set()
processing_lock = threading.Lock()

# PostgreSQL connection function
def get_postgresql_connection():
    """Get a connection to the PostgreSQL database"""
    try:
        conn = psycopg2.connect(
            host="localhost",
            database="rec_io_db",
            user="rec_io_user",
            password="rec_io_password"
        )
        return conn
    except Exception as e:
        print(f"❌ Failed to connect to PostgreSQL: {e}")
        return None

def get_executor_port():
    return get_port("trade_executor")

# ---------- CORE TRADE FUNCTIONS ----------------------------------------------------

def insert_trade(trade):
    """Insert a new trade with BTC price from unified endpoint"""

    
    # Get current BTC price directly from PostgreSQL live_data table - INSTANT
    try:
        pg_conn = get_postgresql_connection()
        if pg_conn:
            with pg_conn.cursor() as cursor:
                cursor.execute("SELECT price FROM live_data.live_price_log_1s_btc ORDER BY timestamp DESC LIMIT 1")
                result = cursor.fetchone()
            
            if result and result[0] is not None:
                symbol_open = int(float(result[0]))
            else:
                symbol_open = None
        else:
            symbol_open = None
    except Exception as e:
        symbol_open = None
    
    # Get current momentum from API and format it correctly for database
    momentum_for_db = 0
    try:
        momentum_data = get_momentum_data_from_postgresql()
        momentum_score = momentum_data.get('weighted_momentum_score', 0)
        
        if momentum_score != 0:
            momentum_for_db = round(momentum_score * 100)
        else:
            momentum_for_db = 0
    except Exception as e:
        momentum_for_db = 0
    
    contract_name = truncate_contract_name(trade.get('contract'))
    
    # Write to PostgreSQL only
    try:
        pg_conn = get_postgresql_connection()
        if pg_conn:
            with pg_conn.cursor() as cursor:
                cursor.execute("""
                    INSERT INTO users.trades_0001 (
                        status, date, time, symbol, market, trade_strategy,
                        contract, strike, side, prob, diff, buy_price, position,
                        sell_price, closed_at, fees, pnl, symbol_open, symbol_close,
                        momentum, volatility, win_loss, ticker, ticket_id, market_id,
                        momentum_delta, entry_method, close_method, monitor
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING id
                """, (
                    trade.get('status', 'pending'), trade['date'], trade['time'], 
                    trade.get('symbol', 'BTC'), trade.get('market', 'Kalshi'), trade.get('trade_strategy', 'Hourly HTC'),
                    contract_name, trade['strike'], trade['side'], trade.get('prob'),
                    trade.get('diff'), trade['buy_price'], trade['position'], None, None,
                    None, None, symbol_open, None, momentum_for_db, trade.get('volatility'),
                    None, trade.get('ticker'), trade.get('ticket_id'), trade.get('market_id', 'BTC-USD'),
                    trade.get('momentum_delta'), trade.get('entry_method', 'manual'), trade.get('close_method'),
                    trade.get('monitor')  # Monitor must be specified - no fallback
                ))
                last_id = cursor.fetchone()[0]
                pg_conn.commit()
                print(f"💾 Trade written to PostgreSQL users.trades_0001 with ID {last_id}")
            pg_conn.close()
        else:
            print(f"⚠️ Skipping PostgreSQL write - no connection available")
            return None
    except Exception as pg_err:
        print(f"❌ Failed to write trade to PostgreSQL: {pg_err}")
        return None
    
    notify_frontend_trade_change()
    return last_id

def confirm_open_trade(id: int, ticket_id: str) -> None:
    """Confirms a PENDING trade has been opened in the market account"""
    # Get initial trade info
    pg_conn = get_postgresql_connection()
    if pg_conn:
        with pg_conn.cursor() as cursor:
            cursor.execute("SELECT ticker FROM users.trades_0001 WHERE id = %s", (id,))
            row = cursor.fetchone()
        pg_conn.close()
    else:
        row = None
    
    if not row:
        log_event(ticket_id, f"MANAGER: No trade found for ID {id}")
        return
    
    expected_ticker = row[0]
    mode = get_account_mode()
    
    deadline = time.time() + 30  # 30 second timeout
    connection_refresh_time = time.time() + 10  # Refresh connection every 10 seconds
    
    while time.time() < deadline:
        try:
            # Refresh connection every 10 seconds to prevent stale connections
            if time.time() >= connection_refresh_time:
                pg_conn = get_postgresql_connection()
                connection_refresh_time = time.time() + 10
            else:
                pg_conn = get_postgresql_connection()
            
            if not pg_conn:
                log_event(ticket_id, f"MANAGER: Cannot connect to PostgreSQL positions table")
                time.sleep(1)
                continue
            
            with pg_conn.cursor() as cursor_pos:
                cursor_pos.execute("SELECT position, market_exposure, fees_paid FROM users.positions_0001 WHERE ticker = %s", (expected_ticker,))
                row = cursor_pos.fetchone()
            
            if row and row[0] is not None and row[1] is not None:
                pos = abs(row[0])
                exposure = abs(row[1])
                fees_paid = float(row[2]) if row[2] is not None else None
                price = round(float(exposure) / float(pos) / 100, 2) if pos > 0 else 0.0
                
                # Get current status with fresh connection
                pg_conn_status = get_postgresql_connection()
                if pg_conn_status:
                    with pg_conn_status.cursor() as cursor:
                        cursor.execute("SELECT status FROM users.trades_0001 WHERE id = %s", (id,))
                        status_row = cursor.fetchone()
                        current_status = status_row[0] if status_row else None
                    pg_conn_status.close()
                else:
                    current_status = None
                
                if current_status == "pending" and pos > 0 and exposure > 0:
                    # Get probability with fresh connection
                    pg_conn_prob = get_postgresql_connection()
                    if pg_conn_prob:
                        with pg_conn_prob.cursor() as cursor:
                            cursor.execute("SELECT prob FROM users.trades_0001 WHERE id = %s", (id,))
                            prob_row = cursor.fetchone()
                        pg_conn_prob.close()
                    else:
                        prob_row = None
                    
                    prob_value = prob_row[0] if prob_row and prob_row[0] is not None else None
                    diff_value = None
                    
                    if prob_value is not None:
                        prob_decimal = float(prob_value) / 100
                        diff_decimal = prob_decimal - price
                        diff_value = int(round(diff_decimal * 100))
                        diff_formatted = f"+{diff_value}" if diff_value >= 0 else f"{diff_value}"
                    else:
                        diff_formatted = None
                    
                    # Get current symbol price for symbol_open (same as symbol_close logic)
                    symbol_open = None
                    try:
                        import requests
                        main_port = get_port("main_app")
                        response = requests.get(f"http://localhost:{main_port}/api/btc_price", timeout=5)
                        if response.ok:
                            btc_data = response.json()
                            symbol_open = btc_data.get('price')
                            if symbol_open:
                                log_event(ticket_id, f"MANAGER: Retrieved current symbol price for open: {symbol_open}")
                            else:
                                log_event(ticket_id, f"MANAGER: No price data in unified endpoint response")
                                symbol_open = None
                        else:
                            log_event(ticket_id, f"MANAGER: Unified BTC price endpoint returned status {response.status_code}")
                            symbol_open = None
                    except Exception as e:
                        log_event(ticket_id, f"MANAGER: Failed to get current symbol price from unified endpoint: {e}")
                        symbol_open = None
                    
                    # Update additional fields in PostgreSQL BEFORE status change
                    try:
                        pg_conn_update = get_postgresql_connection()
                        if pg_conn_update:
                            with pg_conn_update.cursor() as cursor:
                                # First try to update by ID
                                cursor.execute("""
                                    UPDATE users.trades_0001
                                    SET position = %s,
                                        buy_price = %s,
                                        fees = %s,
                                        diff = %s,
                                        symbol_open = %s
                                    WHERE id = %s
                                """, (pos, price, fees_paid, diff_formatted, symbol_open, id))
                                
                                # If no rows were updated, try to find by ticker
                                if cursor.rowcount == 0:
                                    cursor.execute("""
                                        UPDATE users.trades_0001
                                        SET position = %s,
                                            buy_price = %s,
                                            fees = %s,
                                            diff = %s,
                                            symbol_open = %s
                                        WHERE ticker = %s
                                    """, (pos, price, fees_paid, diff_formatted, symbol_open, expected_ticker))
                                    
                                    if cursor.rowcount > 0:
                                        print(f"💾 Trade additional fields updated in PostgreSQL users.trades_0001 (found by ticker)")
                                    else:
                                        print(f"⚠️ No matching trade found in PostgreSQL for ID {id} or ticker {expected_ticker}")
                                else:
                                    print(f"💾 Trade additional fields also updated in PostgreSQL users.trades_0001")
                                
                                pg_conn_update.commit()
                            pg_conn_update.close()
                        else:
                            print(f"⚠️ Skipping PostgreSQL additional fields update - no connection available")
                    except Exception as pg_err:
                        print(f"❌ Failed to update trade additional fields in PostgreSQL: {pg_err}")
                    
                    # Update trade status to open (this will also update PostgreSQL and notify ATS)
                    update_trade_status(id, 'open')
                    
                    log_event(ticket_id, f"MANAGER: OPEN TRADE CONFIRMED — pos={pos}, price={price}, fees={fees_paid}, diff={diff_formatted}")
                    # Notify strike table for display update (lowest priority)
                    notify_strike_table_trade_change(id, "open")
                    break
                    
        except Exception as e:
            log_event(ticket_id, f"MANAGER: OPEN TRADE WATCH DB read error: {e}")
        
        time.sleep(1)
    
    # Close the main polling connection
    if 'pg_conn' in locals() and pg_conn:
        pg_conn.close()
    
    log_event(ticket_id, f"MANAGER: OPEN TRADE polling complete for ticker: {expected_ticker}")
    
    # Final status check with fresh connection
    pg_conn_final = get_postgresql_connection()
    if pg_conn_final:
        with pg_conn_final.cursor() as cursor:
            cursor.execute("SELECT status FROM users.trades_0001 WHERE id = %s", (id,))
            status_row = cursor.fetchone()
            current_status = status_row[0] if status_row else None
        pg_conn_final.close()
    else:
        current_status = None
    
    if current_status == "pending":
        log_event(ticket_id, f"MANAGER: PENDING TRADE FAILED TO FILL - TIMEOUT")
        notify_active_trade_supervisor_direct(id, ticket_id, "error")

def confirm_close_trade(id: int, ticket_id: str) -> None:
    """Confirms a CLOSING trade has been closed in the market account"""
    log(f"CONFIRMING CLOSE TRADE: {id}")
    
    try:
        pg_conn = get_postgresql_connection()
        if pg_conn:
            with pg_conn.cursor() as cursor:
                cursor.execute("SELECT ticker FROM users.trades_0001 WHERE id = %s", (id,))
                row = cursor.fetchone()
        else:
            row = None
        
        if not row:
            log_event(ticket_id, f"MANAGER: No trade found for ID {id}")
            log(f"NO TRADE FOUND FOR ID: {id}")
            return
        
        expected_ticker = row[0]
        
        mode = get_account_mode()
        
        # Read from PostgreSQL positions table
        pg_conn = get_postgresql_connection()
        if not pg_conn:
            log_event(ticket_id, f"MANAGER: Cannot connect to PostgreSQL positions table")
            return
        
        # Check position once - positions change notification should handle timing
        try:
            with pg_conn.cursor() as cursor_pos:
                cursor_pos.execute("SELECT position FROM users.positions_0001 WHERE ticker = %s", (expected_ticker,))
                row = cursor_pos.fetchone()
            
            if row and row[0] == 0:
                import time
                zero_time = time.time()
                log_event(ticket_id, f"MANAGER: [{zero_time}] POSITION ZEROED OUT for {expected_ticker}")
                log(f"POSITION ZEROED OUT: {expected_ticker}")
                
                now_est = datetime.now(ZoneInfo("America/New_York"))
                closed_at = now_est.strftime("%H:%M:%S")
                
                # Calculate total fees from orders table (opening + closing orders)
                total_fees_paid = None
                pg_conn_orders = get_postgresql_connection()
                if pg_conn_orders:
                    with pg_conn_orders.cursor() as cursor_orders:
                        import time
                        current_time = time.time()
                        log_event(ticket_id, f"MANAGER: [{current_time}] Querying orders table for ticker: {expected_ticker}")
                        cursor_orders.execute("""
                            SELECT SUM(taker_fees) as total_fees
                            FROM users.orders_0001 
                            WHERE ticker = %s
                        """, (expected_ticker,))
                        fees_row = cursor_orders.fetchone()
                        log_event(ticket_id, f"MANAGER: [{current_time}] Raw fees_row from cursor: {fees_row}")
                        # Convert cents to dollars for PnL calculation
                        raw_fees_cents = fees_row[0] if fees_row and fees_row[0] is not None else None
                        total_fees_paid = float(raw_fees_cents) / 100.0 if raw_fees_cents is not None else None
                        log_event(ticket_id, f"MANAGER: Raw fees from SQL (cents): {raw_fees_cents}, converted to dollars: {total_fees_paid}")
                    pg_conn_orders.close()
                
                log_event(ticket_id, f"MANAGER: Calculated total fees from orders: {total_fees_paid}")
                
                pg_conn = get_postgresql_connection()
                if pg_conn:
                    with pg_conn.cursor() as cursor:
                        cursor.execute("SELECT side FROM users.trades_0001 WHERE id = %s", (id,))
                        side_row = cursor.fetchone()
                else:
                    side_row = None
                
                original_side = side_row[0] if side_row else None
                

                
                pg_conn = get_postgresql_connection()
                if pg_conn:
                    with pg_conn.cursor() as cursor_fills:
                        opposite_side = 'no' if original_side == 'Y' else 'yes'
                        
                        cursor_fills.execute("""
                            SELECT yes_price, no_price, created_time, side 
                            FROM users.fills_0001 
                            WHERE ticker = %s AND side = %s 
                            ORDER BY created_time DESC 
                            LIMIT 1
                        """, (expected_ticker, opposite_side))
                        fill_row = cursor_fills.fetchone()
                else:
                    fill_row = None
                
                if not fill_row or not original_side:
                    log_event(ticket_id, f"MANAGER: No closing fill found for {opposite_side} side - cannot calculate sell price")
                    log(f"NO CLOSING FILL FOUND")
                    return
                
                yes_price, no_price, fill_time, fill_side = fill_row
                
                # Use the price for the opposite side (the side we're buying to close)
                # Sell price should be 1 - the price we're paying to close
                if original_side == 'Y':  # Original was YES, so use NO price (we're buying NO to close)
                    sell_price = 1 - float(no_price)  # Keep as decimal
                elif original_side == 'N':  # Original was NO, so use YES price (we're buying YES to close)
                    sell_price = 1 - float(yes_price)  # Keep as decimal
                else:
                    log_event(ticket_id, f"MANAGER: Invalid original side: {original_side}")
                    log(f"INVALID ORIGINAL SIDE")
                    return
                
                symbol_close = None
                try:
                    import requests
                    main_port = get_port("main_app")
                    response = requests.get(f"http://localhost:{main_port}/api/btc_price", timeout=5)
                    if response.ok:
                        btc_data = response.json()
                        symbol_close = btc_data.get('price')
                        if symbol_close:
                            log_event(ticket_id, f"MANAGER: Retrieved current symbol price for close: {symbol_close}")
                        else:
                            log_event(ticket_id, f"MANAGER: No price data in unified endpoint response")
                            symbol_close = None
                    else:
                        log_event(ticket_id, f"MANAGER: Unified BTC price endpoint returned status {response.status_code}")
                        symbol_close = None
                except Exception as e:
                    log_event(ticket_id, f"MANAGER: Failed to get current symbol price from unified endpoint: {e}")
                    symbol_close = None
                
                pg_conn_trade = get_postgresql_connection()
                if pg_conn_trade:
                    with pg_conn_trade.cursor() as cursor:
                        cursor.execute("SELECT buy_price, position FROM users.trades_0001 WHERE id = %s", (id,))
                        trade_data = cursor.fetchone()
                else:
                    trade_data = None
                
                if trade_data:
                    buy_price, position = trade_data
                    buy_value = buy_price * position
                    sell_value = sell_price * position
                    fees = total_fees_paid if total_fees_paid is not None else None
                    pnl = round(sell_value - buy_value - fees, 2)
                    win_loss = "W" if pnl > 0 else "L" if pnl < 0 else "D"
                    
                    pg_conn_method = get_postgresql_connection()
                    if pg_conn_method:
                        with pg_conn_method.cursor() as cursor:
                            cursor.execute("SELECT close_method FROM users.trades_0001 WHERE id = %s", (id,))
                            close_method_row = cursor.fetchone()
                            close_method = close_method_row[0] if close_method_row else "manual"
                    else:
                        close_method = "manual"
                    
                    try:
                        # Update the fees in the trades table to match the calculated total
                        log_event(ticket_id, f"MANAGER: About to write fees to database: {total_fees_paid}")
                        pg_conn_fees = get_postgresql_connection()
                        if pg_conn_fees:
                            with pg_conn_fees.cursor() as cursor_fees:
                                cursor_fees.execute("""
                                    UPDATE users.trades_0001 
                                    SET fees = %s 
                                    WHERE id = %s
                                """, (total_fees_paid, id))
                                pg_conn_fees.commit()
                                log_event(ticket_id, f"MANAGER: Fees written to database successfully")
                            pg_conn_fees.close()
                        
                        update_trade_status(id, "closed", closed_at, sell_price, symbol_close, win_loss, pnl, close_method, total_fees_paid)
                        
                        # Add 5-second pause after trade is marked as closed, before final fee calculation
                        import time
                        pause_start = time.time()
                        log_event(ticket_id, f"MANAGER: [{pause_start}] Trade marked as closed, adding 5-second pause before final fee calculation")
                        time.sleep(5)
                        pause_end = time.time()
                        log_event(ticket_id, f"MANAGER: [{pause_end}] 5-second pause completed")
                        
                        # Recalculate fees after pause to ensure we have the latest data
                        pg_conn_final = get_postgresql_connection()
                        if pg_conn_final:
                            with pg_conn_final.cursor() as cursor_final:
                                import time
                                final_time = time.time()
                                log_event(ticket_id, f"MANAGER: [{final_time}] Final query for ticker: {expected_ticker}")
                                cursor_final.execute("""
                                    SELECT SUM(taker_fees) as total_fees
                                    FROM users.orders_0001 
                                    WHERE ticker = %s
                                """, (expected_ticker,))
                                final_fees_row = cursor_final.fetchone()
                                final_raw_fees_cents = final_fees_row[0] if final_fees_row and final_fees_row[0] is not None else None
                                final_total_fees_paid = float(final_raw_fees_cents) / 100.0 if final_raw_fees_cents is not None else None
                                log_event(ticket_id, f"MANAGER: [{final_time}] Final fee calculation after pause (cents): {final_raw_fees_cents}, converted to dollars: {final_total_fees_paid}")
                                
                                # Recalculate PnL with final fees
                                final_pnl = (sell_price - buy_price) * position - final_total_fees_paid
                                log_event(ticket_id, f"MANAGER: [{final_time}] Final PnL calculation with final fees: {final_pnl}")
                                
                                # Update fees and PnL with final calculation
                                cursor_final.execute("""
                                    UPDATE users.trades_0001 
                                    SET fees = %s, pnl = %s
                                    WHERE id = %s
                                """, (final_total_fees_paid, final_pnl, id))
                                pg_conn_final.commit()
                                log_event(ticket_id, f"MANAGER: [{final_time}] Final fees and PnL written to database: fees={final_total_fees_paid}, pnl={final_pnl}")
                            pg_conn_final.close()
                        
                        log_event(ticket_id, f"MANAGER: CLOSE TRADE CONFIRMED - PnL: {final_pnl}, W/L: {win_loss}, Fees: {final_total_fees_paid}")
                        log(f"CLOSE TRADE CONFIRMED: {expected_ticker}, PnL={final_pnl}, W/L={win_loss}")
                        
                        # Try to notify active trade supervisor, but don't fail if it doesn't work
                        try:
                            notify_active_trade_supervisor_direct(id, ticket_id, "closed")
                        except Exception as e:
                            log(f"NOTIFICATION FAILED BUT TRADE FINALIZED")
                        
                        # Notify strike table for display update (lowest priority)
                        notify_strike_table_trade_change(id, "closed")
                        
                        return
                    except Exception as e:
                        log_event(ticket_id, f"MANAGER: Error in finalization: {e}")
                        log(f"TRADE FINALIZATION FAILED")
                        return
                else:
                    log_event(ticket_id, f"MANAGER: Could not get trade data for PnL calculation")
                    log(f"COULD NOT GET TRADE DATA FOR PNL")
                    return
            else:
                position_value = row[0] if row else "None"
                log_event(ticket_id, f"MANAGER: Position not zeroed out yet - Current: {position_value}")
                log(f"POSITION NOT ZEROED OUT - Current: {position_value}")
                return
        except Exception as e:
            log_event(ticket_id, f"MANAGER: Error checking position: {e}")
            log(f"ERROR CHECKING POSITION: {e}")
            return
    except Exception as e:
        log_event(ticket_id, f"MANAGER: Error in confirm_close_trade: {e}")
        log(f"ERROR IN CONFIRM_CLOSE_TRADE: {e}")
        return

# ---------- UTILITY FUNCTIONS ----------------------------------------------------

def log(msg):
    """Log messages with timestamp"""
    timestamp = datetime.now(ZoneInfo("America/New_York")).strftime("%H:%M:%S")
    print(f"[TRADE_MANAGER {timestamp}] {msg}", flush=True)

from backend.util.trade_logger import log_trade_event

def log_event(ticket_id, message):
    """Log trade events to PostgreSQL instead of text files"""
    try:
        log_trade_event(ticket_id, message, service="trade_manager")
    except Exception as e:
        print(f"[LOG ERROR] Failed to write log: {message} — {e}")

def notify_active_trade_supervisor_direct(trade_id: int, ticket_id: str, status: str) -> None:
    """Send direct notification to active trade supervisor via HTTP API"""
    try:
        import requests
        from backend.core.port_config import get_port
        
        # Get the monitor field from the trade record
        monitor_identifier = None
        pg_conn = get_postgresql_connection()
        if pg_conn:
            with pg_conn.cursor() as cursor:
                cursor.execute("SELECT monitor FROM users.trades_0001 WHERE id = %s", (trade_id,))
                row = cursor.fetchone()
                if row and row[0]:
                    monitor_identifier = row[0]
            pg_conn.close()
        
        # Extract monitor identifier (e.g., "0001_10002" from "mon_0001_10002")
        if monitor_identifier and monitor_identifier.startswith('mon_'):
            monitor_suffix = monitor_identifier[4:]  # Remove "mon_" prefix
        else:
            # No fallback - monitor must be specified
            log(f"ERROR: No valid monitor identifier found for trade {trade_id}")
            return
        
        # Get the port for the specific monitor's active trade supervisor
        # Each monitor instance runs on a different port
        active_trade_supervisor_port = get_port("active_trade_supervisor")
        
        # For now, we'll use the centralized port since all instances share the same port
        # In the future, this could be enhanced to use monitor-specific ports
        notification_url = f"http://localhost:{active_trade_supervisor_port}/api/trade_manager_notification"
        payload = {
            "trade_id": trade_id,
            "ticket_id": ticket_id,
            "status": status,
            "monitor_identifier": monitor_suffix  # Add monitor identifier to payload
        }
        
        response = requests.post(notification_url, json=payload, timeout=5)
        
        if response.status_code == 200:
            result = response.json()
            if result.get("success", False):
                log(f"NOTIFIED ACTIVE TRADE SUPERVISOR for monitor {monitor_suffix}")
            else:
                log(f"ACTIVE TRADE SUPERVISOR ERROR for monitor {monitor_suffix}")
        else:
            log(f"ACTIVE TRADE SUPERVISOR ERROR for monitor {monitor_suffix}")
            
    except ImportError:
        log(f"REQUESTS NOT AVAILABLE")
    except Exception as e:
        log(f"ERROR SENDING NOTIFICATION: {e}")

def notify_frontend_trade_change() -> None:
    """Send notification to frontend when trades are updated"""
    try:
        import requests
        notification_url = f"http://localhost:{get_port('main_app')}/api/notify_db_change"
        payload = {
            "db_name": "trades",
            "timestamp": time.time(),
            "change_data": {"trades": 1}
        }
        
        response = requests.post(notification_url, json=payload, timeout=2)
        if response.status_code == 200:
            log("NOTIFIED FRONTEND")
        else:
            log(f"FRONTEND NOTIFICATION FAILED")
    except Exception as e:
        # Don't log errors for frontend notifications - they're not critical
        pass

def notify_strike_table_trade_change(trade_id: int, status: str) -> None:
    """Notify strike table about trade status changes for display updates"""
    try:
        import requests
        notification_url = f"http://localhost:{get_port('main_app')}/api/notify_db_change"
        payload = {
            "db_name": "trades",
            "timestamp": time.time(),
            "change_data": {"trade_id": trade_id, "status": status}
        }
        
        response = requests.post(notification_url, json=payload, timeout=1)
        if response.status_code == 200:
            log(f"NOTIFIED STRIKE TABLE")
        else:
            log(f"STRIKE TABLE NOTIFICATION FAILED")
    except Exception as e:
        # Don't log errors for strike table notifications - they're not critical
        pass

def truncate_contract_name(contract_name):
    """Truncate contract name to short form like 'BTC 5pm'"""
    if not contract_name:
        return contract_name
    
    if contract_name.startswith("BTC ") and len(contract_name) < 20:
        return contract_name
    
    import re
    time_match = re.search(r'at (\d+)(am|pm)', contract_name, re.IGNORECASE)
    if time_match:
        hour = time_match.group(1)
        ampm = time_match.group(2).lower()
        return f"BTC {hour}{ampm}"
    
    return contract_name

# ---------- DATABASE FUNCTIONS ----------------------------------------------------

def init_trades_db():
    """Initialize PostgreSQL database structure for fresh installs"""
    try:
        pg_conn = get_postgresql_connection()
        if not pg_conn:
            print("⚠️ Cannot connect to PostgreSQL - skipping database initialization")
            return
        
        with pg_conn.cursor() as cursor:
            # Create users schema if it doesn't exist
            cursor.execute("CREATE SCHEMA IF NOT EXISTS users")
            
            # Create trades table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS users.trades_0001 (
                    id INTEGER PRIMARY KEY,
                    status TEXT DEFAULT 'pending',
                    date TEXT NOT NULL,
                    time TEXT NOT NULL,
                    symbol TEXT DEFAULT 'BTC',
                    market TEXT DEFAULT 'Kalshi',
                    trade_strategy TEXT DEFAULT 'Hourly HTC',
                    contract TEXT,
                    strike TEXT NOT NULL,
                    side TEXT NOT NULL,
                    prob REAL,
                    diff TEXT,
                    buy_price REAL NOT NULL,
                    position INTEGER NOT NULL,
                    sell_price REAL,
                    closed_at TEXT,
                    fees REAL,
                    pnl REAL,
                    symbol_open REAL,
                    symbol_close REAL,
                    momentum REAL,
                    volatility REAL,
                    win_loss TEXT,
                    ticker TEXT,
                    ticket_id TEXT,
                    market_id TEXT DEFAULT 'BTC-USD',
                    momentum_delta REAL,
                    entry_method TEXT DEFAULT 'manual',
                    close_method TEXT
                )
            """)
            
            # Create sequence for auto-incrementing ID
            cursor.execute("""
                CREATE SEQUENCE IF NOT EXISTS users.trades_0001_id_seq1
                INCREMENT 1
                START 1
                OWNED BY users.trades_0001.id
            """)
            
            # Create fills table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS users.fills_0001 (
                    id SERIAL PRIMARY KEY,
                    trade_id TEXT UNIQUE,
                    ticker TEXT,
                    order_id TEXT,
                    side TEXT,
                    action TEXT,
                    count INTEGER,
                    yes_price REAL,
                    no_price REAL,
                    is_taker BOOLEAN,
                    created_time TEXT,
                    raw_json TEXT
                )
            """)
            
            # Create settlements table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS users.settlements_0001 (
                    id SERIAL PRIMARY KEY,
                    ticker TEXT,
                    market_result TEXT,
                    yes_count INTEGER,
                    yes_total_cost DECIMAL(10,2),
                    no_count INTEGER,
                    no_total_cost DECIMAL(10,2),
                    revenue DECIMAL(10,2),
                    settled_time TEXT,
                    raw_json TEXT,
                    UNIQUE(ticker, settled_time)
                )
            """)
            
            # Create positions table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS users.positions_0001 (
                    id SERIAL PRIMARY KEY,
                    ticker TEXT,
                    position INTEGER,
                    market_exposure REAL,
                    fees_paid REAL,
                    created_time TEXT,
                    raw_json TEXT
                )
            """)
            
            # Create live_data schema if it doesn't exist
            cursor.execute("CREATE SCHEMA IF NOT EXISTS live_data")
            

            
            # Create indexes for better performance
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_trades_0001_status ON users.trades_0001(status)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_trades_0001_ticker ON users.trades_0001(ticker)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_fills_0001_ticker ON users.fills_0001(ticker)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_settlements_0001_ticker ON users.settlements_0001(ticker)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_positions_0001_ticker ON users.positions_0001(ticker)")

            
            pg_conn.commit()
            print("✅ PostgreSQL database structure initialized successfully")
            
        pg_conn.close()
        
    except Exception as e:
        print(f"❌ Error initializing PostgreSQL database structure: {e}")
        try:
            pg_conn.close()
        except:
            pass

init_trades_db()



def update_trade_status(trade_id, status, closed_at=None, sell_price=None, symbol_close=None, win_loss=None, pnl=None, close_method=None, fees=None):
    """Update trade status in PostgreSQL database only."""
    if status == 'closed':
        if closed_at is None:
            utc_now = datetime.utcnow().replace(tzinfo=ZoneInfo("UTC"))
            est_now = utc_now.astimezone(ZoneInfo("America/New_York"))
            closed_at = est_now.isoformat()

        if pnl is not None:
            calculated_pnl = pnl
        else:
            pg_conn = get_postgresql_connection()
            if pg_conn:
                with pg_conn.cursor() as cursor_pg:
                    cursor_pg.execute("SELECT buy_price, position FROM users.trades_0001 WHERE id = %s", (trade_id,))
                    row = cursor_pg.fetchone()
                    buy_price = row[0] if row else None
                    position = row[1] if row else None
                    fees_paid = fees if fees is not None else 0.0
            else:
                buy_price = None
                position = None
                fees_paid = fees if fees is not None else 0.0

            if buy_price is not None and sell_price is not None:
                win_loss = 'W' if sell_price > buy_price else 'L'
            else:
                win_loss = None

            calculated_pnl = None
            if buy_price is not None and sell_price is not None and position is not None:
                buy_value = buy_price * position
                sell_value = sell_price * position
                fees = fees_paid if fees_paid is not None else 0.0
                calculated_pnl = round(sell_value - buy_value - fees, 2)

    # Update PostgreSQL only
    try:
        pg_conn = get_postgresql_connection()
        if pg_conn:
            with pg_conn.cursor() as cursor:
                # First try to update by ID
                if status == 'closed':
                    cursor.execute("""
                        UPDATE users.trades_0001 
                        SET status = %s, closed_at = %s, sell_price = %s, symbol_close = %s, win_loss = %s, pnl = %s, close_method = %s 
                        WHERE id = %s
                    """, (status, closed_at, sell_price, symbol_close, win_loss, calculated_pnl, close_method, trade_id))
                else:
                    cursor.execute("""
                        UPDATE users.trades_0001 
                        SET status = %s 
                        WHERE id = %s
                    """, (status, trade_id))
                
                # If no rows were updated, try to find by ticker
                if cursor.rowcount == 0:
                    # Get ticker from PostgreSQL
                    pg_conn_ticker = get_postgresql_connection()
                    if pg_conn_ticker:
                        with pg_conn_ticker.cursor() as cursor_ticker:
                            cursor_ticker.execute("SELECT ticker FROM users.trades_0001 WHERE id = %s", (trade_id,))
                            ticker_row = cursor_ticker.fetchone()
                    else:
                        ticker_row = None
                    
                    if ticker_row and ticker_row[0]:
                        ticker = ticker_row[0]
                        if status == 'closed':
                            cursor.execute("""
                                UPDATE users.trades_0001 
                                SET status = %s, closed_at = %s, sell_price = %s, symbol_close = %s, win_loss = %s, pnl = %s, close_method = %s 
                                WHERE ticker = %s
                            """, (status, closed_at, sell_price, symbol_close, win_loss, calculated_pnl, close_method, ticker))
                        else:
                            cursor.execute("""
                                UPDATE users.trades_0001 
                                SET status = %s 
                                WHERE ticker = %s
                            """, (status, ticker))
                        
                        if cursor.rowcount > 0:
                            print(f"💾 Trade status update written to PostgreSQL users.trades_0001 (found by ticker)")
                        else:
                            print(f"⚠️ No matching trade found in PostgreSQL for ID {trade_id} or ticker {ticker}")
                    else:
                        print(f"⚠️ Could not find ticker for trade ID {trade_id} in PostgreSQL")
                else:
                    print(f"💾 Trade status update written to PostgreSQL users.trades_0001")
                
                pg_conn.commit()
                pg_conn.close()
                
                # Broadcast active trades change to frontend
                try:
                    import requests
                    broadcast_url = f"http://localhost:{get_port('main_app')}/api/broadcast_active_trades_change"
                    broadcast_payload = {
                        "count": 1,
                        "trade_id": trade_id,
                        "status": status,
                        "timestamp": time.time()
                    }
                    response = requests.post(broadcast_url, json=broadcast_payload, timeout=2)
                    if response.status_code == 200:
                        log("NOTIFIED FRONTEND - ACTIVE TRADES CHANGE")
                    else:
                        log(f"ACTIVE TRADES BROADCAST FAILED: {response.status_code}")
                except Exception as e:
                    log(f"ACTIVE TRADES BROADCAST ERROR: {e}")
        else:
            print(f"⚠️ Skipping PostgreSQL update - no connection available")
    except Exception as e:
        print(f"❌ Failed to update PostgreSQL: {e}")
        if pg_conn:
            pg_conn.close()
    
    notify_frontend_trade_change()
    
    # Notify Active Trade Supervisor when status changes to open
    if status == 'open':
        # Get ticket_id from PostgreSQL
        pg_conn = get_postgresql_connection()
        if pg_conn:
            with pg_conn.cursor() as cursor:
                cursor.execute("SELECT ticket_id FROM users.trades_0001 WHERE id = %s", (trade_id,))
                ticket_row = cursor.fetchone()
        else:
            ticket_row = None
        
        if ticket_row and ticket_row[0]:
            ticket_id = ticket_row[0]
            notify_active_trade_supervisor_direct(trade_id, ticket_id, "open")

# ---------- API ENDPOINTS ----------------------------------------------------

from fastapi import APIRouter, HTTPException, status, Request
router = APIRouter()

@router.get("/api/ports")
async def get_ports():
    """Get all port assignments from centralized system"""
    return get_port_info()

@router.get("/trades")
def get_trades(status: str = None, recent_hours: int = None):
    """Get trades with optional filtering by status"""
    pg_conn = get_postgresql_connection()
    if not pg_conn:
        return []
    
    try:
        with pg_conn.cursor() as cursor:
            if status == "open":
                cursor.execute("SELECT id, date, time, strike, side, buy_price, position, status, contract FROM users.trades_0001 WHERE status = 'open'")
                rows = cursor.fetchall()
                result = [dict(zip(["id","date","time","strike","side","buy_price","position","status","contract"], row)) for row in rows]
            elif status == "closed" and recent_hours:
                cutoff = datetime.utcnow() - timedelta(hours=recent_hours)
                cutoff_iso = cutoff.isoformat()
                cursor.execute("""
                    SELECT id, date, time, strike, side, buy_price, position, status, closed_at, contract, sell_price, pnl, win_loss
                    FROM users.trades_0001
                    WHERE status = 'closed' AND closed_at >= %s
                    ORDER BY closed_at DESC
                """, (cutoff_iso,))
                rows = cursor.fetchall()
                result = [dict(zip(["id","date","time","strike","side","buy_price","position","status","closed_at","contract","sell_price","pnl","win_loss"], row)) for row in rows]
            elif status == "closed":
                cursor.execute("SELECT * FROM users.trades_0001 WHERE status = 'closed' ORDER BY id DESC")
                rows = cursor.fetchall()
                columns = [desc[0] for desc in cursor.description]
                result = [dict(zip(columns, row)) for row in rows]
            else:
                cursor.execute("SELECT * FROM users.trades_0001 ORDER BY id DESC")
                rows = cursor.fetchall()
                columns = [desc[0] for desc in cursor.description]
                result = [dict(zip(columns, row)) for row in rows]
        
        return result
    except Exception as e:
        print(f"❌ Error reading trades from PostgreSQL: {e}")
        return []
    finally:
        pg_conn.close()

@router.post("/trades", status_code=status.HTTP_201_CREATED)
async def add_trade(request: Request):
    """Create a new trade - handles both open and close intents"""
    data = await request.json()
    intent = data.get("intent", "open").lower()
    
    if intent == "close":
        log(f"CLOSE TICKET RECEIVED")
        ticker = data.get("ticker")
        if ticker:
            # IMMEDIATELY send to executor FIRST
            try:
                import requests
                executor_port = get_executor_port()
                log(f"SENDING CLOSE TO EXECUTOR")
                close_payload = {
                    "ticker": ticker,
                    "side": data.get("side"),
                    "count": data.get("count"),
                    "action": "close",
                    "type": "market",
                    "time_in_force": "IOC",
                    "buy_price": 1.00,  # Set to 100 cents for unlimited close orders
                    "symbol_close": None,
                    "intent": "close"
                }
                response = requests.post(f"http://localhost:{executor_port}/trigger_trade", json=close_payload, timeout=5)
                log(f"EXECUTOR RESPONSE: {response.status_code}")
            except Exception as e:
                log(f"CLOSE EXECUTOR ERROR: {e}")
            
            # Get trade_id for notifications
            pg_conn = get_postgresql_connection()
            if pg_conn:
                with pg_conn.cursor() as cursor:
                    cursor.execute("SELECT id FROM users.trades_0001 WHERE ticker = %s", (ticker,))
                    row = cursor.fetchone()
            else:
                row = None
            
            if row:
                trade_id = row[0]
                # Update database status
                symbol_close = None
                sell_price = data.get("buy_price")
                close_method = data.get("close_method", "manual")
                
                # Update PostgreSQL
                try:
                    pg_conn_update = get_postgresql_connection()
                    if pg_conn_update:
                        with pg_conn_update.cursor() as cursor:
                            cursor.execute("UPDATE users.trades_0001 SET status = 'closing', symbol_close = %s, close_method = %s WHERE ticker = %s", (symbol_close, close_method, ticker))
                            pg_conn_update.commit()
                            print(f"💾 Manual close trade also marked as 'closing' in PostgreSQL users.trades_0001")
                        pg_conn_update.close()
                    else:
                        print(f"⚠️ Skipping PostgreSQL manual close update - no connection available")
                except Exception as pg_err:
                    print(f"❌ Failed to update manual close trade in PostgreSQL: {pg_err}")
                
                # Notify active trade supervisor
                notify_active_trade_supervisor_direct(trade_id, data.get('ticket_id'), "closing")
                
                # Check positions
                try:
                    mode = get_account_mode()
                    pg_conn = get_postgresql_connection()
                    
                    if pg_conn:
                        with pg_conn.cursor() as cursor_pos:
                            cursor_pos.execute("SELECT position FROM users.positions_0001 WHERE ticker = %s", (ticker,))
                            row = cursor_pos.fetchone()

                        if row:
                            pos_db = abs(row[0])
                            pg_conn_trade = get_postgresql_connection()
                            if pg_conn_trade:
                                with pg_conn_trade.cursor() as cursor:
                                    cursor.execute("SELECT position FROM users.trades_0001 WHERE ticker = %s", (ticker,))
                                    trade_row = cursor.fetchone()
                            else:
                                trade_row = None

                            if trade_row and abs(trade_row[0]) == pos_db:
                                log(f"CLOSE POSITION CONFIRMED: {ticker}")
                            else:
                                log(f"CLOSE CHECK MISMATCH")
                        else:
                            log(f"NO MATCHING ENTRY IN POSITIONS TABLE")
                    else:
                        log(f"CANNOT CONNECT TO POSTGRESQL POSITIONS TABLE")
                except Exception as e:
                    log(f"CLOSE CHECK ERROR: {e}")

                log(f"CLOSE TICKET SENT - WAITING FOR CONFIRMATION")
            else:
                log(f"COULD NOT FIND TRADE ID FOR TICKER")

        return {"message": "Close ticket received and processed"}
    
    # OPEN TRADE
    log("OPEN TICKET RECEIVED")
    required_fields = {"date", "time", "strike", "side", "buy_price", "position"}
    if not required_fields.issubset(data.keys()):
        raise HTTPException(status_code=400, detail="Missing required trade fields")

    now_est = datetime.now(ZoneInfo("America/New_York"))
    data["time"] = now_est.strftime("%H:%M:%S")

    # IMMEDIATELY send to executor first
    try:
        import requests
        executor_port = get_executor_port()
        log(f"SENDING TO EXECUTOR")
        response = requests.post(f"http://localhost:{executor_port}/trigger_trade", json=data, timeout=5)
        log(f"EXECUTOR RESPONSE: {response.status_code}")
    except Exception as e:
        log(f"EXECUTOR ERROR: {e}")
        log_event(data["ticket_id"], f"EXECUTOR ERROR: {e}")

    # Log immediately after executor call, before heavy database operations
    log(f"TRADE SENT TO EXECUTOR - PROCESSING DATABASE")

    # Ensure the trade is inserted with 'pending' status
    data['status'] = 'pending'
    trade_id = insert_trade(data)
    log_event(data["ticket_id"], "MANAGER: SENT TO EXECUTOR — CONFIRMED")
    
    # Notify active trade supervisor about the new pending trade
    notify_active_trade_supervisor_direct(trade_id, data["ticket_id"], "pending")

    return {"id": trade_id}

@router.post("/api/update_trade_status")
async def update_trade_status_api(request: Request):
    """Handle status updates from executor"""
    log(f"STATUS UPDATE RECEIVED")
    data = await request.json()
    id = data.get("id")
    ticket_id = data.get("ticket_id")
    new_status = data.get("status", "").strip().lower()
        
    if not new_status or (not id and not ticket_id):
        raise HTTPException(status_code=400, detail="Missing id or ticket_id or status")

    if not id and ticket_id:
        pg_conn = get_postgresql_connection()
        if pg_conn:
            with pg_conn.cursor() as cursor:
                cursor.execute("SELECT id FROM users.trades_0001 WHERE ticket_id = %s", (ticket_id,))
                row = cursor.fetchone()
        else:
            row = None
        if not row:
            raise HTTPException(status_code=404, detail="Trade with provided ticket_id not found")
        id = row[0]

    if not ticket_id:
        pg_conn = get_postgresql_connection()
        if pg_conn:
            with pg_conn.cursor() as cursor:
                cursor.execute("SELECT ticket_id FROM users.trades_0001 WHERE id = %s", (id,))
                row = cursor.fetchone()
        else:
            row = None
        ticket_id = row[0] if row else None

    if new_status == "accepted":
        log(f"TRADE ACCEPTED BY EXECUTOR")
        log(f"WAITING FOR POSITION CONFIRMATION")
        return {"message": "Trade accepted – waiting for position confirmation", "id": id}

    elif new_status == "error":
        error_message = data.get("error_message", "")
        intent = data.get("intent", "open")  # Get the original intent
        
        # Check if it's a close order failure
        if intent == "close":
            log(f"CLOSE ORDER FAILED - Marking as close_failed")
            if ticket_id:
                log_event(ticket_id, f"MANAGER: CLOSE ORDER FAILED - Marking as close_failed")
            
            # Mark as close_failed instead of error
            update_trade_status(id, "close_failed")
            
            # Notify active trade supervisor about close failure
            notify_active_trade_supervisor_direct(id, ticket_id, "close_failed")
            
            return {"message": "Close order failed - marked as close_failed", "id": id}
        
        # Check if it's an insufficient volume or insufficient balance error for OPEN orders
        elif "insufficient_resting_volume" in error_message.lower() or "insufficient balance" in error_message.lower():
            error_type = "INSUFFICIENT VOLUME" if "insufficient_resting_volume" in error_message.lower() else "INSUFFICIENT BALANCE"
            log(f"{error_type} ERROR - DELETING PENDING TRADE")
            if ticket_id:
                log_event(ticket_id, f"MANAGER: {error_type} - DELETING PENDING TRADE")
            
            # Delete the pending trade instead of marking as error
            pg_conn = get_postgresql_connection()
            if pg_conn:
                with pg_conn.cursor() as cursor:
                    cursor.execute("DELETE FROM users.trades_0001 WHERE id = %s AND status = 'pending'", (id,))
                    deleted_count = cursor.rowcount
                    pg_conn.commit()
                    pg_conn.close()
                    
                    if deleted_count > 0:
                        log(f"DELETED PENDING TRADE {id} DUE TO {error_type}")
                        notify_active_trade_supervisor_direct(id, ticket_id, "deleted")
                        return {"message": f"Pending trade deleted due to {error_type.lower()}", "id": id}
                    else:
                        log(f"NO PENDING TRADE FOUND TO DELETE")
                        return {"message": "No pending trade found to delete", "id": id}
            else:
                log(f"CANNOT CONNECT TO DATABASE TO DELETE TRADE")
                return {"message": "Database connection error", "id": id}
        else:
            # Handle other errors normally
            update_trade_status(id, "error")
            if ticket_id:
                log_event(ticket_id, f"MANAGER: STATUS UPDATED — SET TO 'ERROR' - {error_message}")
            
            notify_active_trade_supervisor_direct(id, ticket_id, "error")
            
            return {"message": "Trade marked error", "id": id}

    else:
        raise HTTPException(status_code=400, detail=f"Unrecognized status value: '{new_status}'")

@router.post("/api/positions_updated")
async def positions_updated_api(request: Request):
    """Endpoint for kalshi_account_sync to notify about database updates"""
    try:
        data = await request.json()
        db_name = data.get("database", "positions")
        # log(f"[🔔 POSITIONS UPDATED] Database: {db_name} - checking for pending/closing trades")
        
        # Handle pending trades (only when positions database is updated)
        if db_name == "positions":
            pg_conn = get_postgresql_connection()
            if pg_conn:
                with pg_conn.cursor() as cursor:
                    cursor.execute("SELECT id, ticket_id FROM users.trades_0001 WHERE status = 'pending'")
                    pending_trades = cursor.fetchall()
            else:
                pending_trades = []
            
            if pending_trades:
                log(f"[🔔 POSITIONS UPDATED] Found {len(pending_trades)} pending trades to confirm")
                for id, ticket_id in pending_trades:
                    threading.Thread(target=confirm_open_trade, args=(id, ticket_id), daemon=True).start()
        
        # Handle closing trades (only when fills database is updated)
        if db_name == "fills":
            pg_conn = get_postgresql_connection()
            if pg_conn:
                with pg_conn.cursor() as cursor:
                    cursor.execute("SELECT id, ticket_id FROM users.trades_0001 WHERE status = 'closing'")
                    closing_trades = cursor.fetchall()
            else:
                closing_trades = []
            
            if closing_trades:
                # log(f"[🔔 POSITIONS UPDATED] Found {len(closing_trades)} closing trades to confirm")
                for id, ticket_id in closing_trades:
                    pg_conn = get_postgresql_connection()
                    if pg_conn:
                        with pg_conn.cursor() as cursor:
                            cursor.execute("SELECT status FROM users.trades_0001 WHERE id = %s", (id,))
                            current_status = cursor.fetchone()
                    else:
                        current_status = None
                    
                    if current_status and current_status[0] == 'closing':
                        # Process closing trade directly - no threading needed for single trades
                        confirm_close_trade(id, ticket_id)
        
        return {"message": f"{db_name}_updated received"}
    except Exception as e:
        log(f"[ERROR /api/positions_updated] {e}")
        return {"error": str(e)}

@router.post("/api/manual_expiration_check")
async def manual_expiration_check():
    """Manually trigger the expiration check - marks all open trades as expired"""
    try:
        log("[MANUAL] Manual expiration check triggered")
        
        # Run the expiration check in a separate thread to avoid blocking
        threading.Thread(target=check_expired_trades, daemon=True).start()
        
        return {"message": "Manual expiration check triggered"}
    except Exception as e:
        log(f"[ERROR /api/manual_expiration_check] {e}")
        return {"error": str(e)}

@router.post("/api/manual_settlement_poll")
async def manual_settlement_poll():
    """Manually trigger settlement polling for expired trades"""
    try:
        log("[MANUAL] Manual settlement polling triggered")
        
        # Get expired trades that need settlement
        pg_conn = get_postgresql_connection()
        if pg_conn:
            with pg_conn.cursor() as cursor:
                cursor.execute("SELECT ticker FROM users.trades_0001 WHERE status = 'expired'")
                expired_trades = cursor.fetchall()
        else:
            expired_trades = []
        
        if expired_trades:
            expired_tickers = [trade[0] for trade in expired_trades]
            log(f"[MANUAL] Found {len(expired_tickers)} expired trades to poll settlements for")
            
            # Run settlement polling in a separate thread
            threading.Thread(target=poll_settlements_for_matches, args=(expired_tickers,), daemon=True).start()
            
            return {"message": f"Manual settlement polling triggered for {len(expired_tickers)} expired trades"}
        else:
            return {"message": "No expired trades found to poll settlements for"}
            
    except Exception as e:
        log(f"[ERROR /api/manual_settlement_poll] {e}")
        return {"error": str(e)}

# ---------- EXPIRATION FUNCTIONS ----------------------------------------------------

def check_expired_trades():
    """Check for expired trades at top of every hour"""
    try:
        # Step 1: Delete trades with status ERROR
        delete_error_trades()
        
        # Step 2: Check for open trades to mark as expired
        pg_conn = get_postgresql_connection()
        if pg_conn:
            with pg_conn.cursor() as cursor:
                cursor.execute("SELECT id, ticker FROM users.trades_0001 WHERE status = 'open'")
                open_trades = cursor.fetchall()
        else:
            open_trades = []
        
        if not open_trades:
            return
        
        now_est = datetime.now(ZoneInfo("America/New_York"))
        closed_at = now_est.strftime("%H:%M:%S")
        
        try:
            import requests
            main_port = get_port("main_app")
            response = requests.get(f"http://localhost:{main_port}/api/btc_price", timeout=5)
            if response.ok:
                btc_data = response.json()
                symbol_close = btc_data.get('price')
                if symbol_close:
                    pass
                else:
                    symbol_close = None
            else:
                symbol_close = None
        except Exception as e:
            symbol_close = None
        
        # Update PostgreSQL
        try:
            pg_conn = get_postgresql_connection()
            if pg_conn:
                with pg_conn.cursor() as cursor:
                    cursor.execute("""
                        UPDATE users.trades_0001 
                        SET status = 'expired', 
                            closed_at = %s, 
                            symbol_close = %s,
                            close_method = 'expired'
                        WHERE status = 'open'
                    """, (closed_at, symbol_close))
                    pg_conn.commit()
                    print(f"💾 Expired trades update also written to PostgreSQL users.trades_0001")
                pg_conn.close()
            else:
                print(f"⚠️ Skipping PostgreSQL expired trades update - no connection available")
        except Exception as pg_err:
            print(f"❌ Failed to update expired trades in PostgreSQL: {pg_err}")
        
        notify_frontend_trade_change()
        
        for id, ticker in open_trades:
            notify_active_trade_supervisor_direct(id, str(ticker), "expired")
        
        expired_tickers = [trade[1] for trade in open_trades]
        poll_settlements_for_matches(expired_tickers)
        
    except Exception as e:
        pass

def delete_error_trades():
    """Delete trades with status ERROR from PostgreSQL database"""
    try:
        pg_conn = get_postgresql_connection()
        if not pg_conn:
            log(f"❌ Cannot connect to PostgreSQL for error cleanup")
            return
        
        with pg_conn.cursor() as cursor:
            # Count ERROR trades before deletion
            cursor.execute("SELECT COUNT(*) FROM users.trades_0001 WHERE status = 'error'")
            error_count = cursor.fetchone()[0]
            
            if error_count > 0:
                # Delete trades with status ERROR
                cursor.execute("DELETE FROM users.trades_0001 WHERE status = 'error'")
                deleted_count = cursor.rowcount
                pg_conn.commit()
                
                log(f"🧹 DELETED {deleted_count} ERROR trades from PostgreSQL database")
            else:
                log(f"🧹 No ERROR trades found to delete")
        
        pg_conn.close()
        
    except Exception as e:
        log(f"❌ Error deleting ERROR trades: {e}")
        try:
            pg_conn.close()
        except:
            pass

def poll_settlements_for_matches(expired_tickers):
    """Poll settlements for matches to expired trades"""
    mode = get_account_mode()
    

    
    found_tickers = set()
    start_time = time.time()
    timeout_seconds = 30 * 60
    
    while len(found_tickers) < len(expired_tickers):
        if time.time() - start_time > timeout_seconds:
            break
            
        try:
            for ticker in expired_tickers:
                if ticker in found_tickers:
                    continue
                    
                pg_conn = get_postgresql_connection()
                if pg_conn:
                    with pg_conn.cursor() as cursor:
                        cursor.execute("SELECT revenue FROM users.settlements_0001 WHERE ticker = %s ORDER BY settled_time DESC LIMIT 1", (ticker,))
                        row = cursor.fetchone()
                else:
                    row = None
                
                if row:
                    revenue = row[0]
                    sell_price = 1.00 if revenue > 0 else 0.00
                    
                    total_fees_paid = None
                    pg_conn = get_postgresql_connection()
                    if pg_conn:
                        with pg_conn.cursor() as cursor_pos:
                            cursor_pos.execute("SELECT fees_paid FROM users.positions_0001 WHERE ticker = %s", (ticker,))
                            fees_row = cursor_pos.fetchone()
                            total_fees_paid = float(fees_row[0]) if fees_row and fees_row[0] is not None else None
                    
                    pg_conn_trades = get_postgresql_connection()
                    if pg_conn_trades:
                        with pg_conn_trades.cursor() as cursor_trades:
                            cursor_trades.execute("SELECT buy_price, position, fees FROM users.trades_0001 WHERE ticker = %s AND status = 'expired'", (ticker,))
                            trade_row = cursor_trades.fetchone()
                    else:
                        trade_row = None
                    if trade_row:
                        buy_price, position, fees = trade_row
                        pnl = None
                        if buy_price is not None and sell_price is not None and position is not None:
                            buy_value = buy_price * position
                            sell_value = sell_price * position
                            fees = fees if fees is not None else None
                            pnl = round(sell_value - buy_value - fees, 2)
                    
                    # Update PostgreSQL
                    try:
                        pg_conn = get_postgresql_connection()
                        if pg_conn:
                            with pg_conn.cursor() as cursor:
                                cursor.execute("""
                                    UPDATE users.trades_0001 
                                    SET status = 'closed',
                                        sell_price = %s,
                                        win_loss = %s,
                                        pnl = %s
                                    WHERE ticker = %s AND status = 'expired'
                                """, (sell_price, 'W' if sell_price > 0 else 'L', pnl, ticker))
                                pg_conn.commit()
                                print(f"💾 Settlement trade update also written to PostgreSQL users.trades_0001")
                            pg_conn.close()
                        else:
                            print(f"⚠️ Skipping PostgreSQL settlement update - no connection available")
                    except Exception as pg_err:
                        print(f"❌ Failed to update settlement trade in PostgreSQL: {pg_err}")
                    
                    notify_frontend_trade_change()
                    
                    found_tickers.add(ticker)
                    
            if len(found_tickers) < len(expired_tickers):
                time.sleep(2)
            else:
                break
            
        except Exception as e:
            time.sleep(2)

# ---------- APScheduler Setup ----------------------------------------------------

_scheduler = BackgroundScheduler(timezone=ZoneInfo("America/New_York"))
_scheduler.add_job(check_expired_trades, CronTrigger(minute=0, second=0), max_instances=1, coalesce=True)

from fastapi import FastAPI

app = FastAPI()

from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Start APScheduler when FastAPI app starts"""
    try:
        _scheduler.start()
    except Exception as e:
        pass
    yield
    try:
        _scheduler.shutdown()
    except Exception as e:
        pass

app = FastAPI(lifespan=lifespan)

app.include_router(router)

if __name__ == "__main__":
    import uvicorn
    import os

    port = get_port("trade_manager")
    uvicorn.run(app, host="0.0.0.0", port=port)


