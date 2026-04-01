import psycopg2
from datetime import datetime
from zoneinfo import ZoneInfo
import os

from backend.core.time_eastern import merge_psycopg2_connect_kwargs

def get_postgresql_connection():
    """Get PostgreSQL connection for trade logging"""
    try:
        return psycopg2.connect(
            **merge_psycopg2_connect_kwargs(
                {
                    "host": "localhost",
                    "database": "rec_io_db",
                    "user": "rec_io_user",
                    "password": "rec_io_password",
                }
            )
        )
    except Exception as e:
        print(f"Failed to connect to PostgreSQL: {e}")
        return None

def log_trade_event(ticket_id: str, message: str, service: str = "unknown", user_id: str = "user_0001"):
    """
    Log trade events to PostgreSQL users.trade_logs_0001 table
    
    Args:
        ticket_id: The ticket ID for the trade
        message: The log message
        service: The service name (e.g., 'trade_manager', 'trade_executor', 'main')
        user_id: The user ID (defaults to 'user_0001')
    """
    try:
        # Get timestamp in Eastern timezone
        timestamp = datetime.now(ZoneInfo("America/New_York"))
        
        # Connect to PostgreSQL
        conn = get_postgresql_connection()
        if not conn:
            print(f"Failed to log trade event: {message}")
            return
        
        with conn.cursor() as cursor:
            cursor.execute("""
                INSERT INTO users.trade_logs_0001 
                (ticket_id, message, timestamp, service, user_id)
                VALUES (%s, %s, %s, %s, %s)
            """, (ticket_id, message, timestamp, service, user_id))
            conn.commit()
        
        conn.close()
        
        # Also print to console for immediate visibility
        formatted_time = timestamp.strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{formatted_time}] {service.upper()} Ticket {ticket_id[-5:]}: {message}")
        
    except Exception as e:
        print(f"Error logging trade event: {e}")

def get_trade_logs(ticket_id: str = None, service: str = None, limit: int = 100, user_id: str = "user_0001"):
    """
    Retrieve trade logs from PostgreSQL
    
    Args:
        ticket_id: Filter by specific ticket ID
        service: Filter by service name
        limit: Maximum number of logs to return
        user_id: The user ID to filter by
    
    Returns:
        List of log entries
    """
    try:
        conn = get_postgresql_connection()
        if not conn:
            return []
        
        query = "SELECT ticket_id, message, timestamp, service FROM users.trade_logs_0001 WHERE user_id = %s"
        params = [user_id]
        
        if ticket_id:
            query += " AND ticket_id = %s"
            params.append(ticket_id)
        
        if service:
            query += " AND service = %s"
            params.append(service)
        
        query += " ORDER BY timestamp DESC LIMIT %s"
        params.append(limit)
        
        with conn.cursor() as cursor:
            cursor.execute(query, params)
            results = cursor.fetchall()
            
        conn.close()
        
        return [
            {
                "ticket_id": row[0],
                "message": row[1],
                "timestamp": row[2].isoformat() if row[2] else None,
                "service": row[3]
            }
            for row in results
        ]
        
    except Exception as e:
        print(f"Error retrieving trade logs: {e}")
        return []
