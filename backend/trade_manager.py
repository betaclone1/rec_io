
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
from backend.symbol_price_watchdog import calculate_momentum_percentile
# Function to get momentum data from PostgreSQL (replacement for archived unified_production_coordinator)
def get_momentum_data_from_postgresql(symbol):
    """Get current momentum data directly from PostgreSQL for the specified symbol."""
    try:
        import psycopg2
        conn = psycopg2.connect(
            host="localhost",
            database="rec_io_db",
            user="rec_io_user",
            password="rec_io_password"
        )
        cursor = conn.cursor()
        cursor.execute(f"SELECT momentum FROM live_data.live_price_log_1s_{symbol.lower()} ORDER BY timestamp DESC LIMIT 1")
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
    """Insert a new trade with symbol-specific price from unified endpoint"""

    # Get the symbol from trade data - NO FALLBACKS, symbol must be provided
    symbol = trade.get('symbol')
    if not symbol:
        raise ValueError("Trade symbol must be provided - no fallbacks allowed")
    symbol_lower = symbol.lower()
    
    # Get current symbol price directly from PostgreSQL live_data table - INSTANT
    try:
        pg_conn = get_postgresql_connection()
        if pg_conn:
            with pg_conn.cursor() as cursor:
                cursor.execute(f"SELECT price FROM live_data.live_price_log_1s_{symbol_lower} ORDER BY timestamp DESC LIMIT 1")
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
    momentum_percentile_for_db = None
    momentum_5s_avg_for_db = None
    try:
        momentum_data = get_momentum_data_from_postgresql(symbol)
        momentum_score = momentum_data.get('weighted_momentum_score', 0)
        
        if momentum_score != 0:
            momentum_for_db = round(momentum_score * 100)
            # Calculate momentum percentile using the momentum score
            momentum_percentile = calculate_momentum_percentile(symbol, momentum_score)
            momentum_percentile_for_db = momentum_percentile
            # Get 5s momentum average from the API data
            momentum_5s_avg_for_db = momentum_data.get('momentum_5s_avg')
        else:
            momentum_for_db = 0
            momentum_percentile_for_db = None
            momentum_5s_avg_for_db = None
    except Exception as e:
        momentum_for_db = 0
        momentum_percentile_for_db = None
        momentum_5s_avg_for_db = None
    
    contract_name = truncate_contract_name(trade.get('contract'), symbol)
    
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
                        momentum_percentile, momentum_5s_avg, entry_method, close_method, monitor, bankroll
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING id
                """, (
                    trade.get('status', 'pending'), trade['date'], trade['time'], 
                    symbol, trade.get('market', 'Kalshi'), trade.get('trade_strategy', 'Hourly HTC'),
                    contract_name, trade['strike'], trade['side'], trade.get('prob'),
                    trade.get('diff'), trade['buy_price'], trade['position'], None, None,
                    None, None, symbol_open, None, momentum_for_db, trade.get('volatility'),
                    None, trade.get('ticker'), trade.get('ticket_id'), trade.get('market_id', f'{symbol}-USD'),
                    momentum_percentile_for_db, momentum_5s_avg_for_db, trade.get('entry_method', 'manual'), trade.get('close_method'),
                    trade.get('monitor'), trade.get('bankroll_allotment_total')  # Monitor must be specified - no fallback
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
    """Confirms a PENDING trade has been opened by checking ORDERS table for complete fill"""
    # Get initial trade info including the order_id_open we stored
    pg_conn = get_postgresql_connection()
    if pg_conn:
        with pg_conn.cursor() as cursor:
            cursor.execute("SELECT ticker, symbol, order_id_open FROM users.trades_0001 WHERE id = %s", (id,))
            row = cursor.fetchone()
        pg_conn.close()
    else:
        row = None
    
    if not row:
        log_event(ticket_id, f"MANAGER: No trade found for ID {id}")
        return
    
    expected_ticker = row[0]
    symbol = row[1]
    stored_order_id_open = row[2]
    
    if not stored_order_id_open:
        log_event(ticket_id, f"MANAGER: No order_id_open stored for trade ID {id} - cannot confirm via ORDERS table")
        return
    
    deadline = time.time() + 30  # 30 second timeout
    
    while time.time() < deadline:
        try:
            pg_conn = get_postgresql_connection()
            if not pg_conn:
                log_event(ticket_id, f"MANAGER: Cannot connect to PostgreSQL orders table")
                time.sleep(1)
                continue
            
            # Check ORDERS table for our specific order_id
            with pg_conn.cursor() as cursor:
                cursor.execute("""
                    SELECT remaining_count, fill_count, initial_count, status, 
                           taker_fees, maker_fees, taker_fill_cost, side
                    FROM users.orders_0001 
                    WHERE order_id = %s
                """, (stored_order_id_open,))
                order_row = cursor.fetchone()
            
            if order_row:
                remaining_count, fill_count, initial_count, order_status, taker_fees, maker_fees, taker_fill_cost, side = order_row
                
                log_event(ticket_id, f"MANAGER: Opening order {stored_order_id_open} status: {order_status}, remaining: {remaining_count}, filled: {fill_count}/{initial_count}")
                
                # Check if order is completely filled (remaining_count = 0) and executed
                if order_status == "executed" and remaining_count == 0 and fill_count > 0:
                    # Calculate fees from orders table (already in cents, convert to dollars)
                    total_fees_cents = (taker_fees or 0) + (maker_fees or 0)
                    total_fees_dollars = total_fees_cents / 100.0
                    
                    # Calculate position size and buy price from order data
                    position_size = fill_count
                    # taker_fill_cost is in cents, convert to price per share
                    buy_price = (taker_fill_cost / 100.0) / position_size if position_size > 0 else 0.0
                    
                    log_event(ticket_id, f"MANAGER: Order completely filled - pos={position_size}, price={buy_price:.4f}, fees=${total_fees_dollars:.4f}")
                
                    # Get current trade status
                    pg_conn_status = get_postgresql_connection()
                    if pg_conn_status:
                        with pg_conn_status.cursor() as cursor:
                            cursor.execute("SELECT status FROM users.trades_0001 WHERE id = %s", (id,))
                            status_row = cursor.fetchone()
                            current_status = status_row[0] if status_row else None
                        pg_conn_status.close()
                    else:
                        current_status = None
                    
                    if current_status == "pending":
                        # Get probability for diff calculation
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
                            diff_decimal = prob_decimal - buy_price
                            diff_value = int(round(diff_decimal * 100))
                            diff_formatted = f"+{diff_value}" if diff_value >= 0 else f"{diff_value}"
                        else:
                            diff_formatted = None
                    
                        # Get current symbol price for symbol_open
                        symbol_open = None
                        try:
                            import requests
                            main_port = get_port("main_app")
                            response = requests.get(f"http://localhost:{main_port}/api/{symbol.lower()}_price", timeout=5)
                            if response.ok:
                                symbol_data = response.json()
                                symbol_open = symbol_data.get('price')
                                if symbol_open:
                                    log_event(ticket_id, f"MANAGER: Retrieved current symbol price for open: {symbol_open}")
                                else:
                                    log_event(ticket_id, f"MANAGER: No price data in unified endpoint response")
                                    symbol_open = None
                            else:
                                log_event(ticket_id, f"MANAGER: Unified price endpoint returned status {response.status_code}")
                                symbol_open = None
                        except Exception as e:
                            log_event(ticket_id, f"MANAGER: Failed to get current symbol price from unified endpoint: {e}")
                            symbol_open = None
                        
                        # Update additional fields in PostgreSQL BEFORE status change
                        try:
                            pg_conn_update = get_postgresql_connection()
                            if pg_conn_update:
                                with pg_conn_update.cursor() as cursor:
                                    cursor.execute("""
                                        UPDATE users.trades_0001
                                        SET position = %s,
                                            buy_price = %s,
                                            fees = %s,
                                            diff = %s,
                                            symbol_open = %s
                                        WHERE id = %s
                                    """, (position_size, buy_price, total_fees_dollars, diff_formatted, symbol_open, id))
                                    
                                    if cursor.rowcount > 0:
                                        print(f"💾 Trade additional fields updated in PostgreSQL users.trades_0001 from ORDERS data")
                                    else:
                                        print(f"⚠️ No matching trade found in PostgreSQL for ID {id}")
                                    
                                    pg_conn_update.commit()
                                pg_conn_update.close()
                            else:
                                print(f"⚠️ Skipping PostgreSQL additional fields update - no connection available")
                        except Exception as pg_err:
                            print(f"❌ Failed to update trade additional fields in PostgreSQL: {pg_err}")
                        
                        # Update trade status to open (this will also update PostgreSQL and notify ATS)
                        update_trade_status(id, 'open')
                        
                        log_event(ticket_id, f"MANAGER: OPEN TRADE CONFIRMED via ORDERS table — pos={position_size}, price={buy_price:.4f}, fees=${total_fees_dollars:.4f}, diff={diff_formatted}")
                        # Notify strike table for display update (lowest priority)
                        notify_strike_table_trade_change(id, "open")
                        pg_conn.close()
                        break
                    else:
                        log_event(ticket_id, f"MANAGER: Trade status is not pending (current: {current_status}) - skipping confirmation")
                        pg_conn.close()
                        break
                else:
                    log_event(ticket_id, f"MANAGER: Order not yet completely filled - status: {order_status}, remaining: {remaining_count}")
            else:
                log_event(ticket_id, f"MANAGER: Opening order {stored_order_id_open} not found in ORDERS table yet")
            
            pg_conn.close()
                    
        except Exception as e:
            log_event(ticket_id, f"MANAGER: OPEN TRADE WATCH DB read error: {e}")
        
        time.sleep(1)
    
    log_event(ticket_id, f"MANAGER: OPEN TRADE polling complete for order_id_open: {stored_order_id_open}")
    
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
        log_event(ticket_id, f"MANAGER: PENDING TRADE FAILED TO FILL - TIMEOUT (order_id_open: {stored_order_id_open})")
        notify_active_trade_supervisor_direct(id, ticket_id, "error")

def confirm_close_trade(id: int, ticket_id: str) -> None:
    """Confirms a CLOSING trade has been closed by checking ORDERS table for complete close fill"""
    log(f"CONFIRMING CLOSE TRADE: {id}")
    
    try:
        # Get trade info including the order_id_close we stored
        pg_conn = get_postgresql_connection()
        if pg_conn:
            with pg_conn.cursor() as cursor:
                cursor.execute("SELECT ticker, symbol, order_id_close FROM users.trades_0001 WHERE id = %s", (id,))
                row = cursor.fetchone()
            pg_conn.close()
        else:
            row = None
        
        if not row:
            log_event(ticket_id, f"MANAGER: No trade found for ID {id}")
            log(f"NO TRADE FOUND FOR ID: {id}")
            return
        
        expected_ticker = row[0]
        symbol = row[1]
        stored_order_id_close = row[2]
        
        if not stored_order_id_close:
            log_event(ticket_id, f"MANAGER: No order_id_close stored for trade ID {id} - cannot confirm via ORDERS table")
            log(f"NO CLOSE ORDER_ID FOR TRADE: {id}")
            return
        
        # Check ORDERS table for our specific close order_id
        pg_conn = get_postgresql_connection()
        if not pg_conn:
            log_event(ticket_id, f"MANAGER: Cannot connect to PostgreSQL orders table")
            return
        
        # Check close order once - orders change notification should handle timing
        try:
            with pg_conn.cursor() as cursor:
                cursor.execute("""
                    SELECT remaining_count, fill_count, status, taker_fees, maker_fees
                    FROM users.orders_0001 
                    WHERE order_id = %s
                """, (stored_order_id_close,))
                order_row = cursor.fetchone()
            
            if order_row:
                remaining_count, fill_count, order_status, taker_fees, maker_fees = order_row
                log_event(ticket_id, f"MANAGER: Close order {stored_order_id_close} status: {order_status}, remaining: {remaining_count}, filled: {fill_count}")
                
                # Check if close order is completely filled (remaining_count = 0) and executed
                if order_status == "executed" and remaining_count == 0 and fill_count > 0:
                    log_event(ticket_id, f"MANAGER: CLOSE ORDER COMPLETELY FILLED - Trade {id} confirmed closed")
                    log(f"CLOSE ORDER COMPLETELY FILLED: {expected_ticker}")
                    
                    now_est = datetime.now(ZoneInfo("America/New_York"))
                    closed_at = now_est.strftime("%H:%M:%S")
                    
                    # SIMPLE: Get opening fees already recorded + add closing fees from this order
                    pg_conn_trade = get_postgresql_connection()
                    if pg_conn_trade:
                        with pg_conn_trade.cursor() as cursor:
                            cursor.execute("SELECT fees FROM users.trades_0001 WHERE id = %s", (id,))
                            existing_fees_row = cursor.fetchone()
                            existing_fees = existing_fees_row[0] if existing_fees_row else 0.0
                        pg_conn_trade.close()
                    else:
                        existing_fees = 0.0
                    
                    # Add closing order fees to existing opening fees
                    close_order_fees_cents = (taker_fees or 0) + (maker_fees or 0)
                    close_order_fees_dollars = close_order_fees_cents / 100.0
                    total_fees_paid = existing_fees + close_order_fees_dollars
                    
                    log_event(ticket_id, f"MANAGER: SIMPLE fee calc - existing: ${existing_fees}, close order: ${close_order_fees_dollars}, total: ${total_fees_paid}")
                    
                    # Get sell price from the close order data
                    pg_conn_close_order = get_postgresql_connection()
                    if pg_conn_close_order:
                        with pg_conn_close_order.cursor() as cursor:
                            cursor.execute("""
                                SELECT side, taker_fill_cost, fill_count
                                FROM users.orders_0001 
                                WHERE order_id = %s
                            """, (stored_order_id_close,))
                            close_order_data = cursor.fetchone()
                        pg_conn_close_order.close()
                    else:
                        close_order_data = None
                    
                    if close_order_data:
                        close_side, close_fill_cost, close_fill_count = close_order_data
                        # Calculate sell price from close order (cost per share)
                        sell_price = (close_fill_cost / 100.0) / close_fill_count if close_fill_count > 0 else 0.0
                        # For close orders, sell_price should be 1 - the price we paid to close
                        sell_price = 1 - sell_price
                        log_event(ticket_id, f"MANAGER: Calculated sell_price from close order: {sell_price}")
                    else:
                        sell_price = None
                        log_event(ticket_id, f"MANAGER: Could not get close order data for sell price calculation")
                    
                    # Get current symbol price for symbol_close
                    symbol_close = None
                    try:
                        import requests
                        main_port = get_port("main_app")
                        response = requests.get(f"http://localhost:{main_port}/api/{symbol.lower()}_price", timeout=5)
                        if response.ok:
                            symbol_data = response.json()
                            symbol_close = symbol_data.get('price')
                            log_event(ticket_id, f"MANAGER: Retrieved current symbol price for close: {symbol_close}")
                    except Exception as e:
                        log_event(ticket_id, f"MANAGER: Failed to get current symbol price: {e}")
                    
                    # Get trade data for PnL calculation including existing fees
                    pg_conn_trade = get_postgresql_connection()
                    if pg_conn_trade:
                        with pg_conn_trade.cursor() as cursor:
                            cursor.execute("SELECT buy_price, position, close_method, fees FROM users.trades_0001 WHERE id = %s", (id,))
                            trade_data = cursor.fetchone()
                        pg_conn_trade.close()
                    else:
                        trade_data = None
                    
                    if trade_data and sell_price is not None:
                        buy_price, position, close_method, existing_fees = trade_data
                        close_method = close_method or "manual"
                        existing_fees = existing_fees or 0.0
                        
                        # Use the total fees we calculated (existing + close order fees)
                        total_fees = total_fees_paid if total_fees_paid is not None else 0.0
                        
                        log_event(ticket_id, f"MANAGER: Final total fees for PnL: ${total_fees}")
                        
                        # Calculate PnL with total fees
                        buy_value = buy_price * position
                        sell_value = sell_price * position
                        pnl = round(sell_value - buy_value - total_fees, 2)
                        win_loss = "W" if pnl > 0 else "L" if pnl < 0 else "D"
                        
                        log_event(ticket_id, f"MANAGER: PnL calculation - buy: ${buy_price}, sell: ${sell_price}, total_fees: ${total_fees}, pnl: ${pnl}")
                        
                        # Calculate ret_pct (return percentage) - same logic as settlement process
                        ret_pct = None
                        pg_conn_bankroll = get_postgresql_connection()
                        if pg_conn_bankroll:
                            with pg_conn_bankroll.cursor() as cursor_bankroll:
                                cursor_bankroll.execute("SELECT bankroll FROM users.trades_0001 WHERE id = %s", (id,))
                                bankroll_row = cursor_bankroll.fetchone()
                                bankroll = bankroll_row[0] if bankroll_row else None
                            pg_conn_bankroll.close()
                        else:
                            bankroll = None
                        
                        if bankroll is not None and bankroll > 0:  # Prevent division by zero
                            # PnL is in dollars, bankroll is in cents
                            # Formula: (pnl / (bankroll/100.0)) * 100
                            ret_pct = round((pnl / (bankroll / 100.0)) * 100, 5)
                            log_event(ticket_id, f"MANAGER: Calculated ret_pct: {ret_pct}% (PnL: ${pnl}, Bankroll: {bankroll} cents)")
                        else:
                            log_event(ticket_id, f"MANAGER: Bankroll is zero or None for trade {id}, cannot calculate ret_pct")
                        
                        # Get high_price and low_price from active_trades before it's removed
                        high_price, low_price = get_high_low_prices_from_active_trades(id)
                        
                        # Update trade status to closed with all calculated values including ret_pct and high/low prices
                        update_trade_status_with_ret_pct(id, "closed", closed_at, sell_price, symbol_close, win_loss, pnl, close_method, total_fees, ret_pct, high_price, low_price)
                        
                        log_event(ticket_id, f"MANAGER: CLOSE TRADE CONFIRMED - PnL: ${pnl}, W/L: {win_loss}, Fees: ${total_fees}")
                        log(f"CLOSE TRADE CONFIRMED: {expected_ticker}, PnL=${pnl}, W/L={win_loss}")
                    else:
                        # Fallback - just mark as closed without detailed calculations
                        update_trade_status(id, "closed")
                        log_event(ticket_id, f"MANAGER: CLOSE TRADE CONFIRMED (minimal data)")
                    
                    # Notify active trade supervisor
                    notify_active_trade_supervisor_direct(id, ticket_id, "closed")
                    
                    # Notify strike table for display update
                    notify_strike_table_trade_change(id, "closed")
                    
                    pg_conn.close()
                    return
                else:
                    log_event(ticket_id, f"MANAGER: Close order not yet completely filled - status: {order_status}, remaining: {remaining_count}")
            else:
                log_event(ticket_id, f"MANAGER: Close order {stored_order_id_close} not found in ORDERS table yet")
            
            pg_conn.close()
                    
        except Exception as e:
            log_event(ticket_id, f"MANAGER: CLOSE TRADE WATCH DB read error: {e}")
            log(f"ERROR CHECKING CLOSE ORDER: {e}")
            return
    except Exception as e:
        log_event(ticket_id, f"MANAGER: Error in confirm_close_trade: {e}")
        log(f"ERROR IN CONFIRM_CLOSE_TRADE: {e}")
        return

# ---------- UTILITY FUNCTIONS ----------------------------------------------------

def get_high_low_prices_from_active_trades(trade_id: int) -> tuple:
    """
    Get high_price and low_price from active_trades table before trade is removed.
    
    Args:
        trade_id: The trade ID
        
    Returns:
        tuple: (high_price, low_price) or (None, None) if not found
    """
    try:
        # Get monitor identifier from trades table
        pg_conn = get_postgresql_connection()
        if not pg_conn:
            return (None, None)
        
        with pg_conn.cursor() as cursor:
            cursor.execute("SELECT monitor FROM users.trades_0001 WHERE id = %s", (trade_id,))
            monitor_row = cursor.fetchone()
        pg_conn.close()
        
        if not monitor_row or not monitor_row[0]:
            log(f"⚠️ No monitor found for trade {trade_id}, cannot get high/low prices")
            return (None, None)
        
        monitor_identifier = monitor_row[0]
        
        # Extract user number and monitor ID from monitor identifier (e.g., "mon_0001_10002" -> "0001", "10002")
        if monitor_identifier.startswith('mon_'):
            monitor_suffix = monitor_identifier[4:]  # Remove "mon_" prefix
            parts = monitor_suffix.split('_')
            if len(parts) == 2:
                user_number = parts[0]
                monitor_id = parts[1]
            else:
                log(f"⚠️ Invalid monitor identifier format: {monitor_identifier}")
                return (None, None)
        else:
            log(f"⚠️ Monitor identifier doesn't start with 'mon_': {monitor_identifier}")
            return (None, None)
        
        # Construct active_trades table name
        active_trades_table = f"active_trades_{user_number}_{monitor_id}"
        
        # Query active_trades table for high_price and low_price
        pg_conn = get_postgresql_connection()
        if not pg_conn:
            return (None, None)
        
        with pg_conn.cursor() as cursor:
            cursor.execute(f"""
                SELECT high_price, low_price
                FROM users.{active_trades_table}
                WHERE trade_id = %s
            """, (trade_id,))
            price_row = cursor.fetchone()
        pg_conn.close()
        
        if price_row:
            high_price, low_price = price_row
            log(f"📊 Retrieved high_price={high_price}, low_price={low_price} for trade {trade_id}")
            return (high_price, low_price)
        else:
            log(f"⚠️ Trade {trade_id} not found in active_trades table {active_trades_table}")
            return (None, None)
            
    except Exception as e:
        log(f"❌ Error getting high/low prices from active_trades for trade {trade_id}: {e}")
        return (None, None)

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

def notify_active_trade_supervisor_direct_with_monitor(trade_id: int, ticket_id: str, status: str, monitor_identifier: str) -> None:
    """Send direct notification to active trade supervisor via HTTP API with pre-fetched monitor identifier"""
    try:
        import requests
        from backend.core.port_config import get_monitor_port
        
        # Extract monitor identifier (e.g., "0001_10002" from "mon_0001_10002")
        if monitor_identifier and monitor_identifier.startswith('mon_'):
            monitor_suffix = monitor_identifier[4:]  # Remove "mon_" prefix
        else:
            # No fallback - monitor must be specified
            log(f"ERROR: No valid monitor identifier found for trade {trade_id}")
            return
        
        # Get the port for the specific monitor's active trade supervisor
        # Each monitor instance runs on its own dedicated port
        active_trade_supervisor_port = get_monitor_port("active_trade_supervisor", monitor_suffix)
        
        # Use monitor-specific port for notifications
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

def notify_active_trade_supervisor_direct(trade_id: int, ticket_id: str, status: str) -> None:
    """Send direct notification to active trade supervisor via HTTP API"""
    try:
        import requests
        from backend.core.port_config import get_monitor_port
        
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
        # Each monitor instance runs on its own dedicated port
        active_trade_supervisor_port = get_monitor_port("active_trade_supervisor", monitor_suffix)
        
        # Use monitor-specific port for notifications
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

def truncate_contract_name(contract_name, symbol=None):
    """Truncate contract name to short form like 'SYMBOL 5pm'"""
    if not contract_name:
        return contract_name
    
    # If already short and contains symbol, return as-is
    if symbol and contract_name.startswith(f"{symbol} ") and len(contract_name) < 20:
        return contract_name
    
    import re
    time_match = re.search(r'at (\d+)(am|pm)', contract_name, re.IGNORECASE)
    if time_match and symbol:
        hour = time_match.group(1)
        ampm = time_match.group(2).lower()
        return f"{symbol} {hour}{ampm}"
    
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
                    symbol TEXT NOT NULL,
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
                    market_id TEXT,
                    momentum_percentile REAL,
                    entry_method TEXT DEFAULT 'manual',
                    close_method TEXT,
                    order_id_open TEXT,
                    order_id_close TEXT,
                    high_price DECIMAL(10,4),
                    low_price DECIMAL(10,4)
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
                    yes_price_fixed TEXT,
                    no_price_fixed TEXT,
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
                    total_traded INTEGER,
                    position INTEGER,
                    market_exposure INTEGER,
                    realized_pnl REAL,
                    fees_paid REAL,
                    last_updated_ts TEXT,
                    total_traded_dollars TEXT,
                    market_exposure_dollars TEXT,
                    realized_pnl_dollars TEXT,
                    fees_paid_dollars TEXT,
                    raw_json TEXT
                )
            """)
            
            # Create live_data schema if it doesn't exist
            cursor.execute("CREATE SCHEMA IF NOT EXISTS live_data")
            

            
            # Add order_id columns if they don't exist (for existing databases)
            try:
                cursor.execute("ALTER TABLE users.trades_0001 ADD COLUMN order_id_open TEXT")
                print("✅ Added order_id_open column to existing trades table")
            except Exception as e:
                if "already exists" in str(e).lower() or "duplicate column" in str(e).lower():
                    print("✅ order_id_open column already exists in trades table")
                else:
                    print(f"⚠️ Note: Could not add order_id_open column: {e}")
            
            try:
                cursor.execute("ALTER TABLE users.trades_0001 ADD COLUMN order_id_close TEXT")
                print("✅ Added order_id_close column to existing trades table")
            except Exception as e:
                if "already exists" in str(e).lower() or "duplicate column" in str(e).lower():
                    print("✅ order_id_close column already exists in trades table")
                else:
                    print(f"⚠️ Note: Could not add order_id_close column: {e}")
            
            # Migrate existing order_id data to order_id_open
            try:
                cursor.execute("UPDATE users.trades_0001 SET order_id_open = order_id WHERE order_id IS NOT NULL AND order_id_open IS NULL")
                migrated_count = cursor.rowcount
                if migrated_count > 0:
                    print(f"✅ Migrated {migrated_count} existing order_id values to order_id_open")
            except Exception as e:
                print(f"⚠️ Could not migrate existing order_id data: {e}")
            
            # Create indexes for better performance
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_trades_0001_status ON users.trades_0001(status)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_trades_0001_ticker ON users.trades_0001(ticker)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_trades_0001_order_id_open ON users.trades_0001(order_id_open)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_trades_0001_order_id_close ON users.trades_0001(order_id_close)")
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



def update_trade_status_with_ret_pct(trade_id, status, closed_at=None, sell_price=None, symbol_close=None, win_loss=None, pnl=None, close_method=None, fees=None, ret_pct=None, high_price=None, low_price=None):
    """Update trade status in PostgreSQL database with ret_pct calculation."""
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
                        SET status = %s, closed_at = %s, sell_price = %s, symbol_close = %s, win_loss = %s, pnl = %s, close_method = %s, fees = %s, ret_pct = %s, high_price = %s, low_price = %s
                        WHERE id = %s
                    """, (status, closed_at, sell_price, symbol_close, win_loss, calculated_pnl, close_method, fees, ret_pct, high_price, low_price, trade_id))
                else:
                    cursor.execute("""
                        UPDATE users.trades_0001 
                        SET status = %s 
                        WHERE id = %s
                    """, (status, trade_id))
                
                if cursor.rowcount > 0:
                    print(f"💾 Trade status update written to PostgreSQL users.trades_0001")
                else:
                    print(f"⚠️ No matching trade found in PostgreSQL for ID {trade_id}")
                
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
        
        ticket_id = ticket_row[0] if ticket_row else None
        
        # Get monitor identifier for this trade
        pg_conn = get_postgresql_connection()
        if pg_conn:
            with pg_conn.cursor() as cursor:
                cursor.execute("SELECT monitor FROM users.trades_0001 WHERE id = %s", (trade_id,))
                monitor_row = cursor.fetchone()
                monitor = monitor_row[0] if monitor_row else None
            pg_conn.close()
        else:
            monitor = None
        
        if monitor:
            notify_active_trade_supervisor_direct_with_monitor(trade_id, ticket_id, status, monitor)
        else:
            notify_active_trade_supervisor_direct(trade_id, ticket_id, status)
    
    # Notify monitor_manager when trade is closed
    if status == 'closed':
        notify_monitor_manager_trade_closed(trade_id, status)
        # Update win_streak for the monitor
        update_monitor_win_streak(trade_id)

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
                    # Calculate ret_pct if we have pnl and bankroll
                    ret_pct = None
                    if calculated_pnl is not None:
                        pg_conn_ret = get_postgresql_connection()
                        if pg_conn_ret:
                            with pg_conn_ret.cursor() as cursor_ret:
                                cursor_ret.execute("SELECT bankroll FROM users.trades_0001 WHERE id = %s", (trade_id,))
                                bankroll_row = cursor_ret.fetchone()
                                bankroll = bankroll_row[0] if bankroll_row else None
                            pg_conn_ret.close()
                            
                            if bankroll is not None and bankroll > 0:
                                # Formula: (pnl / (bankroll/100.0)) * 100
                                ret_pct = round((calculated_pnl / (bankroll / 100.0)) * 100, 5)
                    
                    cursor.execute("""
                        UPDATE users.trades_0001 
                        SET status = %s, closed_at = %s, sell_price = %s, symbol_close = %s, win_loss = %s, pnl = %s, close_method = %s, fees = %s, ret_pct = %s 
                        WHERE id = %s
                    """, (status, closed_at, sell_price, symbol_close, win_loss, calculated_pnl, close_method, fees, ret_pct, trade_id))
                else:
                    cursor.execute("""
                        UPDATE users.trades_0001 
                        SET status = %s 
                        WHERE id = %s
                    """, (status, trade_id))
                
                if cursor.rowcount > 0:
                    print(f"💾 Trade status update written to PostgreSQL users.trades_0001")
                else:
                    print(f"⚠️ No matching trade found in PostgreSQL for ID {trade_id}")
                
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

    # Notify monitor_manager when a trade is closed
    if status == 'closed':
        notify_monitor_manager_trade_closed(trade_id, status)
        # Update win_streak for the monitor
        update_monitor_win_streak(trade_id)

def update_monitor_win_streak(trade_id: int) -> None:
    """Update the win_streak for a monitor based on the trade result.
    
    CYCLE LOGIC: Any cycle (settlement hour) with a loss results in win_streak=0.
    Wins only count if the entire cycle has no losses.
    """
    try:
        pg_conn = get_postgresql_connection()
        if not pg_conn:
            log(f"⚠️ Cannot connect to database to update win_streak")
            return
        
        # Get the monitor, contract, and win_loss for this trade
        with pg_conn.cursor() as cursor:
            cursor.execute("SELECT monitor, win_loss, contract, ticker FROM users.trades_0001 WHERE id = %s", (trade_id,))
            trade_row = cursor.fetchone()
        
        if not trade_row or not trade_row[0]:
            pg_conn.close()
            return
        
        monitor = trade_row[0]
        win_loss = trade_row[1]
        contract = trade_row[2]
        ticker = trade_row[3]
        
        # Extract monitor ID from monitor identifier (e.g., "mon_0001_10002" -> "10002")
        if monitor and monitor.startswith('mon_'):
            parts = monitor.split('_')
            if len(parts) >= 3:
                monitor_id = parts[2]  # Get the monitor ID (10002)
                user_number = parts[1]  # Get the user number (0001)
            else:
                pg_conn.close()
                return
        else:
            pg_conn.close()
            return
        
        # CYCLE-BASED WIN STREAK LOGIC:
        # A cycle is defined by the contract (settlement hour).
        # If ANY trade in a cycle is a loss, the entire cycle doesn't count toward win_streak.
        # We need to check if we've already processed this cycle to avoid double-counting.
        
        # First, check if we've already processed this cycle (using ticker as cycle identifier)
        # Extract the settlement hour from ticker (e.g., KXBTCD-25OCT1314 means Oct 13, 14:00)
        cycle_id = None
        if ticker and '-' in ticker:
            # Extract the date-hour portion (everything before the last hyphen)
            parts = ticker.rsplit('-', 1)
            if len(parts) >= 1:
                cycle_id = parts[0]  # e.g., "KXBTCD-25OCT1314"
        
        if not cycle_id:
            # Fallback to contract if ticker parsing fails
            cycle_id = contract
        
        # Check if we've already processed this cycle for this monitor
        with pg_conn.cursor() as cursor:
            cursor.execute(f"""
                SELECT last_processed_cycle FROM users.monitor_list_{user_number}
                WHERE id = %s
            """, (monitor_id,))
            result = cursor.fetchone()
            last_processed_cycle = result[0] if result and result[0] else None
        
        if last_processed_cycle == cycle_id:
            # Already processed this cycle, skip to avoid double-counting
            log(f"⏭️  Skipping win_streak update for {monitor} - cycle {cycle_id} already processed")
            pg_conn.close()
            return
        
        # Check if there are ANY pending trades in this cycle (expired but not yet settled)
        with pg_conn.cursor() as cursor:
            cursor.execute("""
                SELECT COUNT(*) 
                FROM users.trades_0001 
                WHERE monitor = %s 
                AND ticker LIKE %s
                AND status = 'expired'
            """, (monitor, f"{cycle_id}%"))
            pending_count = cursor.fetchone()[0]
        
        if pending_count > 0:
            # There are still unsettled trades in this cycle - skip for now
            # They will trigger this function again when they settle
            log(f"⏭️  Waiting for {pending_count} pending trades in cycle {cycle_id} for {monitor} to settle")
            pg_conn.close()
            return
        
        # Get all trades from this cycle for this monitor
        with pg_conn.cursor() as cursor:
            # Use ticker pattern to find all trades from the same cycle
            # Note: We use ONLY ticker (not contract) because contract is too generic
            # (e.g., "BTC 4pm" matches multiple days, but "KXBTCD-25OCT1316" is unique to one hour)
            cursor.execute("""
                SELECT id, win_loss, contract, ticker 
                FROM users.trades_0001 
                WHERE monitor = %s 
                AND status = 'closed'
                AND ticker LIKE %s
                ORDER BY id ASC
            """, (monitor, f"{cycle_id}%"))
            cycle_trades = cursor.fetchall()
        
        if not cycle_trades:
            pg_conn.close()
            return
        
        # Check if ANY trade in this cycle is a loss
        has_loss = any(trade[1] == 'L' for trade in cycle_trades)
        win_count = sum(1 for trade in cycle_trades if trade[1] == 'W')
        
        # Get the win_streak_threshold from the database for this monitor
        with pg_conn.cursor() as cursor:
            cursor.execute(f"""
                SELECT win_streak_threshold FROM users.monitor_list_{user_number}
                WHERE id = %s
            """, (monitor_id,))
            threshold_row = cursor.fetchone()
            win_streak_threshold = threshold_row[0] if threshold_row and threshold_row[0] is not None else 22
        
        # Update win_streak based on cycle result
        with pg_conn.cursor() as cursor:
            if has_loss:
                # Any loss in the cycle means win_streak = 0 for this cycle
                cursor.execute(f"""
                    UPDATE users.monitor_list_{user_number}
                    SET win_streak = 0,
                        loss_prevention = 'one_contract',
                        last_processed_cycle = %s
                    WHERE id = %s
                """, (cycle_id, monitor_id))
                log(f"🔄 Cycle {cycle_id} for {monitor} had a loss - win_streak reset to 0 (trades: {len(cycle_trades)})")
            else:
                # All wins in the cycle - increment win_streak by the number of wins
                cursor.execute(f"""
                    UPDATE users.monitor_list_{user_number}
                    SET win_streak = win_streak + %s,
                        loss_prevention = CASE 
                            WHEN win_streak + %s >= %s THEN 'off'
                            ELSE 'one_contract'
                        END,
                        last_processed_cycle = %s
                    WHERE id = %s
                """, (win_count, win_count, win_streak_threshold, cycle_id, monitor_id))
                log(f"📈 Cycle {cycle_id} for {monitor} all wins - win_streak +{win_count} (trades: {len(cycle_trades)}, threshold: {win_streak_threshold})")
            
            pg_conn.commit()
        
        pg_conn.close()
        
    except Exception as e:
        log(f"⚠️ Error updating win_streak for trade {trade_id}: {e}")
        try:
            pg_conn.close()
        except:
            pass

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
        trade_id = data.get("id")  # Get trade_id directly from request
        ticker = data.get("ticker")  # Still need ticker for executor payload
        
        if trade_id:
            log(f"CLOSING SPECIFIC TRADE ID: {trade_id}")
            
            # Verify this trade exists and is open
            pg_conn = get_postgresql_connection()
            if pg_conn:
                with pg_conn.cursor() as cursor:
                    cursor.execute("SELECT ticker, status FROM users.trades_0001 WHERE id = %s", (trade_id,))
                    row = cursor.fetchone()
            else:
                row = None
            
            if row and row[1] == 'open':
                verified_ticker = row[0]
                log(f"VERIFIED OPEN TRADE: ID={trade_id}, TICKER={verified_ticker}")
                
                # IMMEDIATELY send to executor with trade_id
                try:
                    import requests
                    executor_port = get_executor_port()
                    log(f"SENDING CLOSE TO EXECUTOR")
                    close_payload = {
                        "id": trade_id,  # Include trade_id for close orders
                        "ticker": verified_ticker,  # Use verified ticker from database
                        "side": data.get("side"),
                        "count": data.get("count"),
                        "action": "close",
                        "type": "market",
                        "time_in_force": "IOC",
                        "buy_price": 1.00,  # Set to 100 cents for unlimited close orders
                        "symbol_close": None,
                        "intent": "close",
                        "ticket_id": data.get("ticket_id")  # Include ticket_id for close orders
                    }
                    response = requests.post(f"http://localhost:{executor_port}/trigger_trade", json=close_payload, timeout=5)
                    log(f"EXECUTOR RESPONSE: {response.status_code}")
                except Exception as e:
                    log(f"CLOSE EXECUTOR ERROR: {e}")
                
                # Update database status
                symbol_close = None
                sell_price = data.get("buy_price")
                close_method = data.get("close_method", "manual")
                
                # Update PostgreSQL
                try:
                    pg_conn_update = get_postgresql_connection()
                    if pg_conn_update:
                        with pg_conn_update.cursor() as cursor:
                            cursor.execute("UPDATE users.trades_0001 SET status = 'closing', symbol_close = %s, close_method = %s WHERE id = %s", (symbol_close, close_method, trade_id))
                            pg_conn_update.commit()
                            print(f"💾 Manual close trade also marked as 'closing' in PostgreSQL users.trades_0001")
                        pg_conn_update.close()
                    else:
                        print(f"⚠️ Skipping PostgreSQL manual close update - no connection available")
                except Exception as pg_err:
                    print(f"❌ Failed to update manual close trade in PostgreSQL: {pg_err}")
                
                # Notify active trade supervisor
                notify_active_trade_supervisor_direct(trade_id, data.get('ticket_id'), "closing")
                
                log(f"CLOSE TICKET SENT FOR TRADE {trade_id} - WAITING FOR CONFIRMATION")
            else:
                if row:
                    log(f"TRADE {trade_id} EXISTS BUT STATUS IS: {row[1]} (expected: open)")
                    return {"error": f"Trade {trade_id} is not open (status: {row[1]})", "id": trade_id}
                else:
                    log(f"TRADE {trade_id} NOT FOUND")
                    return {"error": f"Trade {trade_id} not found", "id": trade_id}
        else:
            log(f"NO TRADE_ID PROVIDED IN CLOSE REQUEST")
            return {"error": "trade_id (id) is required for close requests"}

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
    order_id = data.get("order_id")  # Extract order_id from payload
    intent = data.get("intent", "open")  # Extract intent to determine which order_id field to use
        
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
        
        # Store the order_id in the database if provided
        if order_id:
            # Determine which order_id field to update based on intent
            if intent == "close":
                order_id_field = "order_id_close"
                log_type = "CLOSING"
            else:
                order_id_field = "order_id_open"
                log_type = "OPENING"
            
            log(f"STORING {log_type} ORDER_ID: {order_id}")
            if ticket_id:
                log_event(ticket_id, f"MANAGER: STORING KALSHI {log_type} ORDER_ID: {order_id}")
            
            try:
                pg_conn = get_postgresql_connection()
                if pg_conn:
                    with pg_conn.cursor() as cursor:
                        cursor.execute(f"UPDATE users.trades_0001 SET {order_id_field} = %s WHERE id = %s", (order_id, id))
                        pg_conn.commit()
                        log(f"{log_type} ORDER_ID STORED SUCCESSFULLY")
                        if ticket_id:
                            log_event(ticket_id, f"MANAGER: {log_type} ORDER_ID STORED IN DATABASE: {order_id}")
                    pg_conn.close()
                else:
                    log(f"FAILED TO STORE {log_type} ORDER_ID - NO DATABASE CONNECTION")
                    if ticket_id:
                        log_event(ticket_id, f"MANAGER: FAILED TO STORE {log_type} ORDER_ID - NO DATABASE CONNECTION")
            except Exception as e:
                log(f"ERROR STORING {log_type} ORDER_ID: {e}")
                if ticket_id:
                    log_event(ticket_id, f"MANAGER: ERROR STORING {log_type} ORDER_ID: {e}")
        
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
            
            # Update notes with error message
            note_text = f"Auto Stop Fail - {error_message}"
            pg_conn = get_postgresql_connection()
            if pg_conn:
                try:
                    with pg_conn.cursor() as cursor:
                        cursor.execute("UPDATE users.trades_0001 SET notes = %s WHERE id = %s", (note_text, id))
                        pg_conn.commit()
                        log(f"UPDATED NOTES: {note_text}")
                    pg_conn.close()
                except Exception as e:
                    log(f"ERROR UPDATING NOTES: {e}")
                    if pg_conn:
                        pg_conn.close()
            
            # Notify active trade supervisor about close failure
            notify_active_trade_supervisor_direct(id, ticket_id, "close_failed")
            
            return {"message": "Close order failed - marked as close_failed", "id": id}
        
        # Check if it's an insufficient volume or insufficient balance error for OPEN orders
        elif "insufficient_resting_volume" in error_message.lower() or "insufficient balance" in error_message.lower():
            error_type = "INSUFFICIENT VOLUME" if "insufficient_resting_volume" in error_message.lower() else "INSUFFICIENT BALANCE"
            log(f"{error_type} ERROR - DELETING PENDING TRADE")
            if ticket_id:
                log_event(ticket_id, f"MANAGER: {error_type} - DELETING PENDING TRADE")
            
            # Get monitor identifier BEFORE deleting the trade
            monitor_identifier = None
            pg_conn = get_postgresql_connection()
            if pg_conn:
                with pg_conn.cursor() as cursor:
                    cursor.execute("SELECT monitor FROM users.trades_0001 WHERE id = %s", (id,))
                    row = cursor.fetchone()
                    if row and row[0]:
                        monitor_identifier = row[0]
                pg_conn.close()
            
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
                        # Pass monitor identifier to avoid querying deleted trade
                        if monitor_identifier:
                            notify_active_trade_supervisor_direct_with_monitor(id, ticket_id, "deleted", monitor_identifier)
                        else:
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
        
        # Handle closing trades (when orders database is updated)
        if db_name == "orders":
            pg_conn = get_postgresql_connection()
            if pg_conn:
                with pg_conn.cursor() as cursor:
                    cursor.execute("SELECT id, ticket_id FROM users.trades_0001 WHERE status = 'closing'")
                    closing_trades = cursor.fetchall()
            else:
                closing_trades = []
            
            if closing_trades:
                log(f"[🔔 ORDERS UPDATED] Found {len(closing_trades)} closing trades to confirm")
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
                        log(f"[🔔 ORDERS UPDATED] Confirming close for trade {id}")
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
        
        # Step 2: Check for open, closing, and close_failed trades to mark as expired
        pg_conn = get_postgresql_connection()
        if pg_conn:
            with pg_conn.cursor() as cursor:
                cursor.execute("SELECT id, ticker, symbol FROM users.trades_0001 WHERE status IN ('open', 'closing', 'close_failed')")
                active_trades = cursor.fetchall()
        else:
            active_trades = []
        
        if not active_trades:
            return
        
        now_est = datetime.now(ZoneInfo("America/New_York"))
        closed_at = now_est.strftime("%H:%M:%S")
        
        # Get symbol-specific closing prices for each trade
        symbol_prices = {}
        for trade_id, ticker, symbol in active_trades:
            if symbol not in symbol_prices:
                try:
                    # Get price from symbol-specific price log
                    pg_conn = get_postgresql_connection()
                    if pg_conn:
                        with pg_conn.cursor() as cursor:
                            cursor.execute(f"SELECT price FROM live_data.live_price_log_1s_{symbol.lower()} ORDER BY timestamp DESC LIMIT 1")
                            result = cursor.fetchone()
                            if result and result[0] is not None:
                                symbol_prices[symbol] = float(result[0])
                            else:
                                symbol_prices[symbol] = None
                        pg_conn.close()
                    else:
                        symbol_prices[symbol] = None
                except Exception as e:
                    symbol_prices[symbol] = None
        
        # Update PostgreSQL - handle each trade individually with its symbol-specific closing price
        try:
            pg_conn = get_postgresql_connection()
            if pg_conn:
                with pg_conn.cursor() as cursor:
                    for trade_id, ticker, symbol in active_trades:
                        symbol_close = symbol_prices.get(symbol)
                        
                        # Get high_price and low_price from active_trades before it's removed
                        high_price, low_price = get_high_low_prices_from_active_trades(trade_id)
                        
                        cursor.execute("""
                            UPDATE users.trades_0001 
                            SET status = 'expired', 
                                closed_at = %s, 
                                symbol_close = %s,
                                close_method = 'expired',
                                high_price = %s,
                                low_price = %s
                            WHERE id = %s AND status IN ('open', 'closing', 'close_failed')
                        """, (closed_at, symbol_close, high_price, low_price, trade_id))
                    pg_conn.commit()
                    print(f"💾 Expired trades update written to PostgreSQL users.trades_0001 for {len(active_trades)} trades (open, closing, and close_failed)")
                pg_conn.close()
            else:
                print(f"⚠️ Skipping PostgreSQL expired trades update - no connection available")
        except Exception as pg_err:
            print(f"❌ Failed to update expired trades in PostgreSQL: {pg_err}")
        
        notify_frontend_trade_change()
        
        for trade_id, ticker, symbol in active_trades:
            notify_active_trade_supervisor_direct(trade_id, str(ticker), "expired")
        
        expired_tickers = [trade[1] for trade in active_trades]
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
                    
                    # For settlements, process each trade individually to calculate correct PnL
                    pg_conn_trades = get_postgresql_connection()
                    if pg_conn_trades:
                        with pg_conn_trades.cursor() as cursor_trades:
                            # Get ALL trades for this ticker, not just the first one
                            cursor_trades.execute("SELECT id, buy_price, position, fees, bankroll FROM users.trades_0001 WHERE ticker = %s AND status = 'expired'", (ticker,))
                            trade_rows = cursor_trades.fetchall()
                    else:
                        trade_rows = []
                    
                    # Process each trade individually
                    for trade_row in trade_rows:
                        trade_id, buy_price, position, existing_fees, bankroll = trade_row
                        pnl = None
                        ret_pct = None
                        
                        if buy_price is not None and sell_price is not None and position is not None:
                            buy_value = buy_price * position
                            sell_value = sell_price * position
                            # Use existing fees from trade record (no additional settlement fees)
                            total_fees_paid = existing_fees if existing_fees is not None else 0.0
                            pnl = round(sell_value - buy_value - total_fees_paid, 2)
                            
                            # Calculate ret_pct for this specific trade
                            if bankroll is not None and bankroll > 0:  # Prevent division by zero
                                # PnL is in dollars, bankroll is in cents
                                # Formula: (pnl / (bankroll/100.0)) * 100
                                ret_pct = round((pnl / (bankroll / 100.0)) * 100, 5)
                                print(f"💾 Calculated ret_pct for trade {trade_id}: {ret_pct}% (PnL: {pnl}, Bankroll: {bankroll})")
                            else:
                                print(f"⚠️ Bankroll is zero or None for trade {trade_id}, cannot calculate ret_pct")
                        
                        # Update this specific trade
                        # Note: high_price and low_price are already set during expiration, preserve them
                        try:
                            pg_conn_update = get_postgresql_connection()
                            if pg_conn_update:
                                with pg_conn_update.cursor() as cursor_update:
                                    cursor_update.execute("""
                                        UPDATE users.trades_0001 
                                        SET status = 'closed',
                                            sell_price = %s,
                                            win_loss = %s,
                                            pnl = %s,
                                            ret_pct = %s
                                        WHERE id = %s AND status = 'expired'
                                    """, (sell_price, 'W' if sell_price > 0 else 'L', pnl, ret_pct, trade_id))
                                    pg_conn_update.commit()
                                    print(f"💾 Settlement update for trade {trade_id}: PnL={pnl}, ret_pct={ret_pct}")
                                    
                                    # Update win_streak for the monitor
                                    update_monitor_win_streak(trade_id)
                                    
                                pg_conn_update.close()
                            else:
                                print(f"⚠️ Skipping PostgreSQL settlement update for trade {trade_id} - no connection available")
                        except Exception as pg_err:
                            print(f"❌ Failed to update settlement trade {trade_id} in PostgreSQL: {pg_err}")
                    
                    if pg_conn_trades:
                        pg_conn_trades.close()
                    
                    notify_frontend_trade_change()
                    
                    # Notify monitor_manager about trades closed by this settlement
                    notify_monitor_manager_trades_closed_by_ticker(ticker, 'closed')
                    
                    found_tickers.add(ticker)
                    
            if len(found_tickers) < len(expired_tickers):
                time.sleep(2)
            else:
                break
            
        except Exception as e:
            time.sleep(2)

def check_expired_trades_for_settlements():
    """Check every 10 minutes for expired trades that now have settlements available"""
    try:
        pg_conn = get_postgresql_connection()
        if not pg_conn:
            return
        
        # Get all expired trades
        with pg_conn.cursor() as cursor:
            cursor.execute("SELECT ticker FROM users.trades_0001 WHERE status = 'expired'")
            expired_trades = cursor.fetchall()
        
        pg_conn.close()
        
        if not expired_trades:
            return
        
        expired_tickers = [trade[0] for trade in expired_trades]
        log(f"[5-MIN CHECK] Found {len(expired_tickers)} expired trades, checking for settlements")
        
        # Run settlement polling for expired trades
        poll_settlements_for_matches(expired_tickers)
        
    except Exception as e:
        log(f"[5-MIN CHECK] Error: {e}")

def notify_monitor_manager_trade_closed(trade_id: int, status: str) -> None:
    """Notify monitor_manager when a trade is closed to update monitor statistics"""
    try:
        import requests
        from backend.core.port_config import get_port
        
        # Get the monitor_manager port
        monitor_manager_port = get_port("monitor_manager")
        
        # Get the monitor identifier for this trade
        pg_conn = get_postgresql_connection()
        if pg_conn:
            with pg_conn.cursor() as cursor:
                cursor.execute("SELECT monitor FROM users.trades_0001 WHERE id = %s", (trade_id,))
                monitor_row = cursor.fetchone()
                monitor = monitor_row[0] if monitor_row else None
            pg_conn.close()
        else:
            monitor = None
        
        if monitor:
            # Send notification to monitor_manager
            notification_url = f"http://localhost:{monitor_manager_port}/api/trade_status_update"
            payload = {
                "trade_id": trade_id,
                "status": status,
                "monitor": monitor
            }
            
            response = requests.post(notification_url, json=payload, timeout=5)
            if response.status_code == 200:
                log(f"✅ Notified monitor_manager about closed trade {trade_id} for monitor {monitor}")
            else:
                log(f"⚠️ monitor_manager notification failed for trade {trade_id}: {response.status_code}")
        else:
            log(f"⚠️ No monitor found for trade {trade_id}, skipping monitor_manager notification")
            
    except Exception as e:
        # Don't fail the trade close if monitor notification fails
        log(f"⚠️ Error notifying monitor_manager about trade {trade_id}: {e}")

def notify_monitor_manager_trades_closed_by_ticker(ticker: str, status: str) -> None:
    """Notify monitor_manager about trades closed by ticker (for settlements/expired trades)"""
    try:
        import requests
        from backend.core.port_config import get_port
        
        # Get the monitor_manager port
        monitor_manager_port = get_port("monitor_manager")
        
        # Get all trades for this ticker and their monitor identifiers
        pg_conn = get_postgresql_connection()
        if pg_conn:
            with pg_conn.cursor() as cursor:
                cursor.execute("SELECT id, monitor FROM users.trades_0001 WHERE ticker = %s AND status = 'closed'", (ticker,))
                trades = cursor.fetchall()
            pg_conn.close()
        else:
            trades = []
        
        if trades:
            # Group trades by monitor to send one notification per monitor
            monitors = set()
            for trade_id, monitor in trades:
                if monitor:
                    monitors.add(monitor)
            
            # Send notification to monitor_manager for each affected monitor
            for monitor in monitors:
                try:
                    notification_url = f"http://localhost:{monitor_manager_port}/api/trade_status_update"
                    payload = {
                        "trade_id": None,  # No specific trade ID for bulk updates
                        "status": status,
                        "monitor": monitor,
                        "bulk_update": True,
                        "ticker": ticker
                    }
                    
                    response = requests.post(notification_url, json=payload, timeout=5)
                    if response.status_code == 200:
                        log(f"✅ Notified monitor_manager about bulk trade closure for ticker {ticker}, monitor {monitor}")
                    else:
                        log(f"⚠️ monitor_manager bulk notification failed for ticker {ticker}, monitor {monitor}: {response.status_code}")
                except Exception as e:
                    log(f"⚠️ Error notifying monitor_manager about bulk trade closure for ticker {ticker}, monitor {monitor}: {e}")
        else:
            log(f"⚠️ No closed trades found for ticker {ticker}, skipping monitor_manager notification")
            
    except Exception as e:
        # Don't fail the settlement if monitor notification fails
        log(f"⚠️ Error notifying monitor_manager about bulk trade closure for ticker {ticker}: {e}")

# ---------- APScheduler Setup ----------------------------------------------------

_scheduler = BackgroundScheduler(timezone=ZoneInfo("America/New_York"))
_scheduler.add_job(check_expired_trades, CronTrigger(minute=0, second=0), max_instances=1, coalesce=True)
_scheduler.add_job(check_expired_trades_for_settlements, CronTrigger(minute="*/5", second=0), max_instances=1, coalesce=True)

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


