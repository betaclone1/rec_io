#!/usr/bin/env python3

import sys
import os
import argparse
import logging

# Ensure project root is on path (derive from this file: backend/kalshi_market_watchdog.py -> parent)
_script_dir = os.path.dirname(os.path.abspath(__file__))
_project_root = os.path.dirname(_script_dir)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

import requests
import json
import time
import os
from pathlib import Path
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import pytz
import psycopg2
from psycopg2.extras import RealDictCursor
from decimal import Decimal

# Config
BASE_URL = "https://api.elections.kalshi.com/trade-api/v2"
API_HEADERS = {
    "Accept": "application/json",
    "User-Agent": "KalshiWatcher/1.0"
}

EST = pytz.timezone("America/New_York")


def format_15m_strike_from_api_floor_strike(floor_strike) -> str:
    """
    Build the `strike` column from Kalshi's market `floor_strike` for 15m events.
    Subtitles are often empty for XRP/SOL; `floor_strike` is authoritative. Uses Decimal(str(...))
    to avoid float noise while matching the JSON numeric the API returns.
    """
    if floor_strike is None:
        return ""
    try:
        d = Decimal(str(floor_strike))
    except Exception:
        return ""
    if d == d.to_integral_value():
        v = int(d)
        if abs(v) >= 1000:
            return f"${v:,}"
        return f"${v}"
    s = format(d.normalize(), "f")
    return f"${s}"


def _est_formatter():
    class ESTFormatter(logging.Formatter):
        def formatTime(self, record, datefmt=None):
            dt = datetime.fromtimestamp(record.created, tz=ZoneInfo("America/New_York"))
            if datefmt:
                return dt.strftime(datefmt)
            s = dt.strftime("%Y-%m-%dT%H:%M:%S")
            z = dt.strftime("%z")
            return s + (z[:3] + ":" + z[3:] if len(z) >= 5 else z)
    return ESTFormatter(fmt="%(asctime)s %(levelname)s [%(name)s] %(message)s")


class _FlushingStreamHandler(logging.StreamHandler):
    def emit(self, record):
        super().emit(record)
        self.flush()


def _configure_logging():
    log = logging.getLogger("kalshi_market_watchdog")
    if log.handlers:
        return log
    handler = _FlushingStreamHandler(sys.stdout)
    handler.setLevel(logging.DEBUG)
    handler.setFormatter(_est_formatter())
    log.addHandler(handler)
    log.setLevel(logging.INFO)
    return log


logger = _configure_logging()
HEARTBEAT_INTERVAL_SEC = 300


def _iso_now_est():
    return datetime.now(ZoneInfo("America/New_York")).isoformat(timespec="seconds")


class OutageTracker:
    """Track functional market-data outages with low log volume."""

    def __init__(self, symbol, interval):
        self.symbol = symbol.lower()
        self.interval = interval
        self.in_outage = False
        self.started_at = None
        self.last_failure_reason = None
        self.fail_count = 0
        self.status_path = Path("logs") / f"kalshi_market_watchdog_status_{interval}_{self.symbol}.json"
        self.outage_path = Path("logs") / f"kalshi_market_watchdog_outages_{interval}_{self.symbol}.jsonl"
        self._ensure_log_dir()
        self._write_status(state="healthy")

    def _ensure_log_dir(self):
        self.status_path.parent.mkdir(parents=True, exist_ok=True)

    def _write_status(self, state, extra=None):
        payload = {
            "service": "kalshi_market_watchdog",
            "symbol": self.symbol.upper(),
            "interval": self.interval,
            "state": state,
            "updated_at": _iso_now_est(),
        }
        if extra:
            payload.update(extra)
        self.status_path.write_text(json.dumps(payload), encoding="utf-8")

    def _append_outage_event(self, payload):
        with self.outage_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(payload) + "\n")

    def mark_failure(self, reason):
        now = datetime.now(ZoneInfo("America/New_York"))
        if not self.in_outage:
            self.in_outage = True
            self.started_at = now
            self.fail_count = 1
            self.last_failure_reason = reason
            logger.warning("DATA OUTAGE STARTED (%s): %s", now.isoformat(timespec="seconds"), reason)
            self._write_status(
                state="outage",
                extra={
                    "outage_started_at": now.isoformat(timespec="seconds"),
                    "fail_count": self.fail_count,
                    "last_failure_reason": self.last_failure_reason,
                },
            )
            return

        self.fail_count += 1
        self.last_failure_reason = reason
        self._write_status(
            state="outage",
            extra={
                "outage_started_at": self.started_at.isoformat(timespec="seconds"),
                "fail_count": self.fail_count,
                "last_failure_reason": self.last_failure_reason,
            },
        )

    def mark_success(self, event_ticker):
        now = datetime.now(ZoneInfo("America/New_York"))
        if self.in_outage and self.started_at:
            duration_sec = int((now - self.started_at).total_seconds())
            logger.warning(
                "DATA OUTAGE ENDED (%s): duration=%ss fail_count=%s recovered_event=%s",
                now.isoformat(timespec="seconds"),
                duration_sec,
                self.fail_count,
                event_ticker,
            )
            self._append_outage_event(
                {
                    "service": "kalshi_market_watchdog",
                    "symbol": self.symbol.upper(),
                    "interval": self.interval,
                    "outage_started_at": self.started_at.isoformat(timespec="seconds"),
                    "outage_ended_at": now.isoformat(timespec="seconds"),
                    "duration_seconds": duration_sec,
                    "fail_count": self.fail_count,
                    "last_failure_reason": self.last_failure_reason,
                    "recovered_event_ticker": event_ticker,
                }
            )
            self.in_outage = False
            self.started_at = None
            self.fail_count = 0
            self.last_failure_reason = None
        self._write_status(state="healthy", extra={"last_success_event_ticker": event_ticker})


def _market_cents_from_dollars(dollars_val, legacy_cents):
    """Kalshi fixed-point: after March 12 2026 legacy cents removed; derive from _dollars when missing."""
    if legacy_cents is not None:
        return legacy_cents
    if dollars_val is not None and str(dollars_val).strip() != "":
        try:
            return int(round(float(dollars_val) * 100))
        except (TypeError, ValueError):
            pass
    return 0


def _kalshi_fp_text(value):
    """Kalshi API fixed-point string for DB TEXT columns (2dp), hourly pipeline."""
    if value is None or value == "":
        return None
    try:
        return f"{float(str(value).strip()):.2f}"
    except (TypeError, ValueError):
        return None


def _int_from_fixed_point(value, default=0):
    """
    Convert Kalshi fixed-point strings (e.g. '56658.00') to integer counts.
    Falls back to default on any parse error.
    """
    if value is None or value == "":
        return default
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return default


# Database configuration
DB_CONFIG = {
    'host': os.getenv('POSTGRES_HOST', 'localhost'),
    'port': os.getenv('POSTGRES_PORT', '5432'),
    'database': os.getenv('POSTGRES_DB', 'rec_io_db'),
    'user': os.getenv('POSTGRES_USER', 'rec_io_user'),
    'password': os.getenv('POSTGRES_PASSWORD', 'rec_io_password')
}

# Global variables
last_failed_ticker = None  # Global tracker
SYMBOL = None  # Will be set from command line argument
INTERVAL = "hourly"  # "hourly" or "15m"

def get_watchdog_port():
    return 5432  # Default PostgreSQL port

def connect_database():
    """Connect to PostgreSQL database"""
    try:
        connection = psycopg2.connect(**DB_CONFIG)
        return connection
    except Exception as e:
        logger.error("Database connection failed: %s", e)
        return None

def get_open_trade_tickers_for_table(connection, table_name, symbol):
    """Return set of tickers that are both (open/pending trades for symbol) and (exist in table)."""
    try:
        cursor = connection.cursor()
        cursor.execute(
            """
            SELECT DISTINCT ticker FROM users.trades_0001
            WHERE status IN ('pending', 'open') AND symbol = %s AND ticker IS NOT NULL
            """,
            (symbol,),
        )
        open_tickers = {row[0] for row in cursor.fetchall()}
        if not open_tickers:
            return set()
        cursor.execute(
            f"SELECT market_ticker FROM {table_name} WHERE market_ticker IN %s",
            (tuple(open_tickers),),
        )
        return {row[0] for row in cursor.fetchall()}
    except Exception as e:
        logger.warning("get_open_trade_tickers_for_table failed: %s", e)
        return set()


def fetch_rows_for_tickers(connection, table_name, tickers):
    """Return list of row dicts for the given market_tickers (for re-insert after rotation)."""
    if not tickers:
        return []
    try:
        cursor = connection.cursor(cursor_factory=RealDictCursor)
        cursor.execute(
            f"SELECT * FROM {table_name} WHERE market_ticker IN %s",
            (tuple(tickers),),
        )
        return cursor.fetchall()
    except Exception as e:
        logger.warning("fetch_rows_for_tickers failed: %s", e)
        return []


def reinsert_preserved_rows(connection, table_name, rows):
    """Re-insert rows (list of dicts) into table; used to keep open-trade markets visible after TRUNCATE."""
    if not rows:
        return
    # Insert all columns except id (let SERIAL assign)
    cols = [k for k in rows[0].keys() if k != "id"]
    cols_str = ", ".join(cols)
    placeholders = ", ".join(["%s"] * len(cols))
    sql = f"INSERT INTO {table_name} ({cols_str}) VALUES ({placeholders})"
    try:
        cursor = connection.cursor()
        for row in rows:
            vals = [row[c] for c in cols]
            cursor.execute(sql, vals)
    except Exception as e:
        logger.warning("reinsert_preserved_rows failed: %s", e)
        raise


def create_market_kalshi_table(connection, symbol, interval="hourly"):
    """Create the market_kalshi_{interval}_{symbol} table if it doesn't exist"""
    try:
        cursor = connection.cursor()
        
        # Legacy per-symbol table names. Production hourly ladder uses unified live_data.market_kalshi_hourly (WS).
        table_name = f"market_kalshi_{interval}_{symbol.lower()}"
        market_val = "hourly" if interval == "hourly" else "15m"
        sym_u = symbol.upper()
        ex_default = "kalshi"
        if interval == "hourly":
            # Same column set and uniqueness as live_data.market_kalshi_15m (migration 20260331_1530).
            create_table_sql = f"""
        CREATE TABLE IF NOT EXISTS live_data.{table_name} (
            id SERIAL PRIMARY KEY,
            symbol VARCHAR(10) NOT NULL DEFAULT '{sym_u}',
            exchange VARCHAR(20) NOT NULL DEFAULT '{ex_default}',
            event_ticker VARCHAR(50) NOT NULL,
            market_ticker VARCHAR(100) NOT NULL,
            market TEXT DEFAULT '{market_val}',
            strike VARCHAR(20),
            volume_fp TEXT,
            open_interest_fp TEXT,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
            updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
            yes_bid_dollars TEXT,
            yes_ask_dollars TEXT,
            no_bid_dollars TEXT,
            no_ask_dollars TEXT,
            last_price_dollars TEXT
        );
        """
        else:
            create_table_sql = f"""
        CREATE TABLE IF NOT EXISTS live_data.{table_name} (
            id SERIAL PRIMARY KEY,
            event_ticker VARCHAR(50) NOT NULL,
            market_ticker VARCHAR(100) NOT NULL,
            market TEXT DEFAULT '{market_val}',
            strike VARCHAR(20),
            yes_bid_dollars TEXT,
            yes_ask_dollars TEXT,
            no_bid_dollars TEXT,
            no_ask_dollars TEXT,
            last_price_dollars TEXT,
            volume_fp TEXT,
            open_interest_fp TEXT,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
            updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
        );
        """

        cursor.execute(create_table_sql)

        if interval == "hourly":
            uq = f"{table_name}_ex_sym_evt_mkt_uniq"
            try:
                cursor.execute(f"""
                    ALTER TABLE live_data.{table_name}
                    ADD CONSTRAINT {uq}
                    UNIQUE (exchange, symbol, event_ticker, market_ticker)
                """)
            except Exception:
                pass
            try:
                cursor.execute(f"""
                    CREATE INDEX IF NOT EXISTS {table_name}_exchange_symbol_idx
                    ON live_data.{table_name} (exchange, symbol)
                """)
                cursor.execute(f"""
                    CREATE INDEX IF NOT EXISTS {table_name}_exchange_symbol_event_idx
                    ON live_data.{table_name} (exchange, symbol, event_ticker)
                """)
            except Exception:
                pass
        else:
            try:
                constraint_name = f"{table_name}_event_market_unique"
                cursor.execute(f"""
                    ALTER TABLE live_data.{table_name}
                    ADD CONSTRAINT {constraint_name}
                    UNIQUE (event_ticker, market_ticker)
                """)
            except Exception:
                pass
        
        connection.commit()
        logger.debug("Market Kalshi %s (%s) table ready", symbol.upper(), interval)
    except Exception as e:
        logger.error("Failed to create table: %s", e)
        connection.rollback()

def get_current_price(symbol):
    """Get current {symbol} price from the price log"""
    try:
        connection = connect_database()
        if not connection:
            return None
            
        cursor = connection.cursor()
        table_name = f"live_price_log_1s_{symbol.lower()}"
        cursor.execute(f"""
            SELECT price FROM live_data.{table_name} 
            ORDER BY timestamp DESC LIMIT 1
        """)
        result = cursor.fetchone()
        connection.close()
        
        if result:
            return result[0]
        return None
        
    except Exception as e:
        logger.warning("Error getting %s price: %s", symbol.upper(), e)
        return None

def next_15m_close_est():
    """Return the next 15m boundary in EST (close time of current window). E.g. 17:07 -> 17:15."""
    now = datetime.now(EST)
    base = now.replace(second=0, microsecond=0)
    minute = now.minute
    next_15 = ((minute // 15) + 1) * 15
    if next_15 >= 60:
        return base.replace(minute=0) + timedelta(hours=1)
    return base.replace(minute=next_15)


def get_current_event_ticker_15m(symbol):
    """Get current 15m event: resolve by listing events and matching strike_date to our next 15m close (UTC).
    Kalshi ticker format: KX{symbol}15M-{DDMMMYY}{HHMM} (date may follow API convention). Market = event_ticker + '-' + MM.
    """
    global last_failed_ticker
    close_time = next_15m_close_est()
    close_utc = close_time.astimezone(pytz.UTC)
    target_ts = close_utc.strftime("%Y-%m-%dT%H:%M")  # e.g. 2026-02-27T22:15

    try:
        list_url = f"{BASE_URL}/events"
        resp = requests.get(list_url, params={"series_ticker": f"KX{symbol}15M"}, headers=API_HEADERS, timeout=10)
        if not resp.ok:
            if last_failed_ticker != target_ts:
                logger.warning("15m list failed: %s", resp.status_code)
                last_failed_ticker = target_ts
            return None, None
        payload = resp.json()
        for e in payload.get("events", []):
            sd = e.get("strike_date") or ""
            if sd.startswith(target_ts) or target_ts in sd:
                event_ticker = e.get("event_ticker")
                if not event_ticker:
                    continue
                data = fetch_event_json(event_ticker)
                if data and "markets" in data:
                    last_failed_ticker = None
                    return event_ticker, data
                break
    except Exception as e:
        logger.warning("15m resolve error: %s", e)
    if last_failed_ticker != target_ts:
        logger.debug("No 15m event for window closing %s EST", close_time.strftime("%H:%M"))
        last_failed_ticker = target_ts
    return None, None


def get_current_event_ticker(symbol, interval="hourly"):
    global last_failed_ticker
    if interval == "15m":
        return get_current_event_ticker_15m(symbol)
    now = datetime.now(EST)

    # Define symbol-specific ticker prefixes and formats
    symbol_config = {
        'BTC': {'prefix': 'KXBTCD', 'format': 'crypto'},
        'ETH': {'prefix': 'KXETHD', 'format': 'crypto'},
        'INX': {'prefix': 'KXINXU', 'format': 'financial'},
        'SPX': {'prefix': 'KXINXU', 'format': 'financial'},  # SPX maps to INX tickers
        'NDX': {'prefix': 'KXNASDAQ100U', 'format': 'financial'},  # NDX maps to NASDAQ100 tickers
        'NASDAQ100': {'prefix': 'KXNASDAQ100U', 'format': 'financial'}
    }
    
    if symbol.upper() not in symbol_config:
        logger.error("Unsupported symbol: %s", symbol)
        return None, None
    
    config = symbol_config[symbol.upper()]
    ticker_prefix = config['prefix']
    format_type = config['format']
    
    # Construct current hour ticker based on format
    test_time = now + timedelta(hours=1)
    year_str = test_time.strftime("%y")
    month_str = test_time.strftime("%b").upper()
    day_str = test_time.strftime("%d")
    hour_str = test_time.strftime("%H")
    
    if format_type == 'crypto':
        # Crypto format: KXBTCD-25SEP1013
        current_ticker = f"{ticker_prefix}-{year_str}{month_str}{day_str}{hour_str}"
    else:
        # Financial format: KXINXU-25SEP11H1400
        current_ticker = f"{ticker_prefix}-{year_str}{month_str}{day_str}H{hour_str}00"

    # Try to fetch the current market data
    data = fetch_event_json(current_ticker)
    if data and "markets" in data:
        # Reset failed ticker tracker on success
        last_failed_ticker = None
        return current_ticker, data
    else:
        # Log the failure but don't try alternative markets
        if last_failed_ticker != current_ticker:
            logger.warning("Failed to fetch market data for %s", current_ticker)
            last_failed_ticker = current_ticker
        return None, None

def get_current_symbol_price(symbol):
    """Get current price for the symbol from live price tables"""
    try:
        connection = connect_database()
        if not connection:
            return None
            
        cursor = connection.cursor()
        
        # Map symbol to price table
        price_tables = {
            'BTC': 'live_price_log_1s_btc',
            'ETH': 'live_price_log_1s_eth',
            'SOL': 'live_price_log_1s_sol',
            'XRP': 'live_price_log_1s_xrp',
            'SPX': 'live_price_log_1s_spx',
            'NDX': 'live_price_log_1s_ndx'
        }
        
        table_name = price_tables.get(symbol.upper())
        if not table_name:
            connection.close()
            return None
            
        cursor.execute(f"SELECT price FROM live_data.{table_name} ORDER BY timestamp DESC LIMIT 1")
        result = cursor.fetchone()
        connection.close()
        
        if result:
            return float(result[0])
        return None
        
    except Exception as e:
        logger.warning("Error getting current price for %s: %s", symbol, e)
        return None

def filter_markets_by_price_range(markets_data, symbol, strike_count=75):
    """Filter markets to keep only the closest strikes to current price"""
    try:
        current_price = get_current_symbol_price(symbol)
        if not current_price:
            logger.warning("No current price for %s, returning all markets", symbol)
            return markets_data
        
        # Extract strike prices and sort by distance from current price
        markets_with_distance = []
        for market in markets_data:
            subtitle = market.get("subtitle", "")
            strike_str = subtitle.split(" or above")[0].strip() if "or above" in subtitle else ""
            
            try:
                # Parse strike price (remove $ and commas)
                strike_price = float(strike_str.replace("$", "").replace(",", ""))
                distance = abs(strike_price - current_price)
                markets_with_distance.append((market, strike_price, distance))
            except (ValueError, AttributeError):
                # Skip markets with unparseable strikes
                continue
        
        # Sort by distance from current price and take the closest ones
        markets_with_distance.sort(key=lambda x: x[2])  # Sort by distance
        closest_markets = markets_with_distance[:strike_count]
        
        # Extract just the market data
        filtered_markets = [market_data[0] for market_data in closest_markets]
        
        strike_range = ""
        if closest_markets:
            min_strike = min(m[1] for m in closest_markets)
            max_strike = max(m[1] for m in closest_markets)
            strike_range = f"${min_strike:,.0f} - ${max_strike:,.0f}"
        
        logger.debug(
            "Filtered %s markets to %s strikes around $%s (range: %s)",
            len(markets_data), len(filtered_markets), f"{current_price:,.2f}", strike_range,
        )
        
        return filtered_markets
        
    except Exception as e:
        logger.warning("Error filtering markets: %s", e)
        return markets_data  # Return all markets if filtering fails

def fetch_event_json(event_ticker):
    url = f"{BASE_URL}/events/{event_ticker}"
    try:
        response = requests.get(url, headers=API_HEADERS, timeout=10)
        response.raise_for_status()
        data = response.json()
        if "error" in data:
            logger.warning("API returned error for ticker %s: %s", event_ticker, data["error"])
            return None
        return data
    except Exception as e:
        logger.warning("Exception fetching event JSON: %s", e)
        return None

def save_market_data_to_postgresql(event_ticker, markets_data, symbol, interval="hourly"):
    """Save market data to PostgreSQL market_kalshi_{interval}_{symbol} table"""
    try:
        connection = connect_database()
        if not connection:
            return False
            
        cursor = connection.cursor()
        table_name = f"market_kalshi_{interval}_{symbol.lower()}"
        sym_u = symbol.upper()
        ex_key = "kalshi"

        # Insert/update market data using ON CONFLICT
        for market in markets_data:
            try:
                # Extract market data
                market_ticker = market.get("ticker", "")
                
                # Extract strike from subtitle (e.g., "$104,250 or above" -> "$104,250")
                subtitle = market.get("subtitle", "")
                strike = subtitle.split(" or above")[0].strip() if "or above" in subtitle else ""
                # 15m: Kalshi exposes authoritative `floor_strike`; subtitle is often empty (e.g. XRP).
                if interval == "15m" and market.get("floor_strike") is not None:
                    strike = format_15m_strike_from_api_floor_strike(market.get("floor_strike"))
                
                # Format strike consistently for financial symbols (SPX, NDX, INX)
                if symbol.upper() in ['SPX', 'NDX', 'INX'] and strike:
                    try:
                        # Remove any existing $ and decimals, then reformat
                        clean_strike = strike.replace("$", "").replace(",", "")
                        strike_value = int(float(clean_strike))
                        strike = f"${strike_value:,}"
                    except (ValueError, TypeError):
                        pass  # Keep original strike if parsing fails
                
                yes_bid_dollars = market.get("yes_bid_dollars")
                yes_ask_dollars = market.get("yes_ask_dollars")
                no_bid_dollars = market.get("no_bid_dollars")
                no_ask_dollars = market.get("no_ask_dollars")
                last_price_dollars = market.get("last_price_dollars")
                market_val = "hourly" if interval == "hourly" else "15m"
                volume_fp_text = _kalshi_fp_text(market.get("volume_fp"))
                open_interest_fp_text = _kalshi_fp_text(market.get("open_interest_fp"))
                if interval == "hourly":
                    cursor.execute(
                        f"""
                        INSERT INTO live_data.{table_name}
                        (symbol, exchange, event_ticker, market_ticker, market, strike,
                         volume_fp, open_interest_fp,
                         yes_bid_dollars, yes_ask_dollars, no_bid_dollars, no_ask_dollars, last_price_dollars,
                         updated_at)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
                        ON CONFLICT (exchange, symbol, event_ticker, market_ticker) DO UPDATE SET
                            market = EXCLUDED.market,
                            strike = EXCLUDED.strike,
                            volume_fp = EXCLUDED.volume_fp,
                            open_interest_fp = EXCLUDED.open_interest_fp,
                            yes_bid_dollars = EXCLUDED.yes_bid_dollars,
                            yes_ask_dollars = EXCLUDED.yes_ask_dollars,
                            no_bid_dollars = EXCLUDED.no_bid_dollars,
                            no_ask_dollars = EXCLUDED.no_ask_dollars,
                            last_price_dollars = EXCLUDED.last_price_dollars,
                            updated_at = NOW()
                    """,
                        (
                            sym_u,
                            ex_key,
                            event_ticker,
                            market_ticker,
                            market_val,
                            strike,
                            volume_fp_text,
                            open_interest_fp_text,
                            yes_bid_dollars,
                            yes_ask_dollars,
                            no_bid_dollars,
                            no_ask_dollars,
                            last_price_dollars,
                        ),
                    )
                else:
                    cursor.execute(
                        f"""
                        INSERT INTO live_data.{table_name}
                        (event_ticker, market_ticker, market, strike,
                         yes_bid_dollars, yes_ask_dollars, no_bid_dollars, no_ask_dollars, last_price_dollars,
                         volume_fp, open_interest_fp, updated_at)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
                        ON CONFLICT (event_ticker, market_ticker) DO UPDATE SET
                            market = EXCLUDED.market,
                            strike = EXCLUDED.strike,
                            yes_bid_dollars = EXCLUDED.yes_bid_dollars,
                            yes_ask_dollars = EXCLUDED.yes_ask_dollars,
                            no_bid_dollars = EXCLUDED.no_bid_dollars,
                            no_ask_dollars = EXCLUDED.no_ask_dollars,
                            last_price_dollars = EXCLUDED.last_price_dollars,
                            volume_fp = EXCLUDED.volume_fp,
                            open_interest_fp = EXCLUDED.open_interest_fp,
                            updated_at = NOW()
                    """,
                        (
                            event_ticker,
                            market_ticker,
                            market_val,
                            strike,
                            yes_bid_dollars,
                            yes_ask_dollars,
                            no_bid_dollars,
                            no_ask_dollars,
                            last_price_dollars,
                            volume_fp_text,
                            open_interest_fp_text,
                        ),
                    )
                
            except Exception as e:
                logger.warning("Error processing market %s: %s", market.get("ticker", "unknown"), e)
                continue
        connection.commit()
        connection.close()
        logger.debug("Saved %s markets to PostgreSQL for %s", len(markets_data), event_ticker)
        return True
    except Exception as e:
        logger.error("Error saving to PostgreSQL: %s", e)
        if connection:
            connection.rollback()
            connection.close()
        return False


def get_one_minute_avg_at_time(connection, symbol, opening_time_est):
    """Get one_minute_avg from live_price_log_1s_{symbol} for the row closest to opening_time_est."""
    table = f"live_data.live_price_log_1s_{symbol.lower()}"
    # timestamp is text e.g. 2026-02-27T17:05:14; opening_time_est is datetime in EST
    opening_str = opening_time_est.strftime("%Y-%m-%dT%H:%M:%S")
    try:
        cursor = connection.cursor()
        cursor.execute(f"""
            SELECT one_minute_avg FROM {table}
            WHERE timestamp::timestamp >= %s::timestamp - interval '2 minutes'
              AND timestamp::timestamp <= %s::timestamp + interval '2 minutes'
            ORDER BY ABS(EXTRACT(EPOCH FROM (timestamp::timestamp - %s::timestamp)))
            LIMIT 1
        """, (opening_str, opening_str, opening_str))
        row = cursor.fetchone()
        return float(row[0]) if row and row[0] is not None else None
    except Exception as e:
        logger.debug("get_one_minute_avg_at_time: %s", e)
        return None


def backfill_15m_strike_from_price_log(symbol, event_ticker):
    """Set strike on market_kalshi_15m_{symbol} from one_minute_avg at market opening time. Call after saving 15m data."""
    connection = connect_database()
    if not connection:
        return False
    try:
        table = f"live_data.market_kalshi_15m_{symbol.lower()}"
        cursor = connection.cursor()
        cursor.execute(
            f"""
            SELECT 1 FROM {table}
            WHERE event_ticker = %s
              AND strike IS NOT NULL
              AND trim(strike) <> ''
            LIMIT 1
            """,
            (event_ticker,),
        )
        if cursor.fetchone():
            logger.debug(
                "15m backfill skipped: strike already set from API/subtitle for event %s",
                event_ticker,
            )
            connection.close()
            return False

        close_time = next_15m_close_est()
        opening_time = close_time - timedelta(minutes=15)
        one_min_avg = get_one_minute_avg_at_time(connection, symbol, opening_time)
        if one_min_avg is None:
            logger.debug("No one_minute_avg at opening %s EST for %s", opening_time.strftime("%H:%M"), symbol)
            connection.close()
            return False
        strike_str = f"${one_min_avg:,.2f}"
        cursor.execute(f"""
            UPDATE {table} SET strike = %s, updated_at = NOW() WHERE event_ticker = %s
        """, (strike_str, event_ticker))
        connection.commit()
        logger.debug("15m strike set to %s (1m avg at %s EST)", strike_str, opening_time.strftime("%H:%M"))
        connection.close()
        return True
    except Exception as e:
        logger.warning("backfill_15m_strike: %s", e)
        if connection:
            connection.rollback()
            connection.close()
        return False


def main():
    global SYMBOL, INTERVAL
    
    # Parse command line arguments
    parser = argparse.ArgumentParser(description='Kalshi Market Watchdog for Symbol')
    parser.add_argument('symbol', help='Symbol to monitor (e.g., BTC, ETH)')
    parser.add_argument('--interval', choices=['hourly', '15m'], default='hourly',
                        help='Market interval: hourly (default) or 15m (BTC, ETH, SOL, XRP)')
    args = parser.parse_args()
    
    SYMBOL = args.symbol.upper()
    INTERVAL = args.interval
    
    if INTERVAL == "15m" and SYMBOL not in ("BTC", "ETH", "SOL", "XRP"):
        logger.error("15m interval only supports BTC, ETH, SOL, XRP, got %s", SYMBOL)
        sys.exit(1)
    logger.debug("Starting Kalshi API Market %s Watchdog (%s)", SYMBOL, INTERVAL)
    connection = connect_database()
    if connection:
        create_market_kalshi_table(connection, SYMBOL, INTERVAL)
        connection.close()
    previous_event_ticker = None
    last_heartbeat = time.time()
    outage_tracker = OutageTracker(SYMBOL, INTERVAL)
    while True:
        try:
            event_ticker, event_data = get_current_event_ticker(SYMBOL, INTERVAL)
            preserved_rows = []
            if event_ticker and event_data and "markets" in event_data:
                if previous_event_ticker and previous_event_ticker != event_ticker:
                    logger.info(
                        "Market rotated: %s → %s (%s tickers)",
                        previous_event_ticker, event_ticker, len(event_data.get("markets", [])),
                    )
                    logger.debug("Cleaning up old market data")
                    table_name = f"live_data.market_kalshi_{INTERVAL}_{SYMBOL.lower()}"
                    connection = connect_database()
                    preserved_rows = []
                    if connection:
                        preserve_tickers = get_open_trade_tickers_for_table(connection, table_name, SYMBOL)
                        if preserve_tickers:
                            preserved_rows = fetch_rows_for_tickers(connection, table_name, preserve_tickers)
                        cursor = connection.cursor()
                        cursor.execute(f"TRUNCATE TABLE {table_name}")
                        connection.commit()
                        connection.close()
                        logger.debug("Cleaned up old market data")
                logger.debug("Processing event: %s", event_ticker)
                if INTERVAL == "15m":
                    filtered_markets = event_data["markets"]
                else:
                    filtered_markets = filter_markets_by_price_range(event_data["markets"], SYMBOL, 75)
                success = save_market_data_to_postgresql(event_ticker, filtered_markets, SYMBOL, INTERVAL)
                if not success:
                    logger.error("Failed to save data for %s", event_ticker)
                    outage_tracker.mark_failure(f"save_failed event={event_ticker}")
                elif INTERVAL == "15m" and (previous_event_ticker is None or previous_event_ticker != event_ticker):
                    backfill_15m_strike_from_price_log(SYMBOL, event_ticker)
                if preserved_rows:
                    conn2 = connect_database()
                    if conn2:
                        try:
                            reinsert_preserved_rows(conn2, table_name, preserved_rows)
                            conn2.commit()
                            logger.info("Preserved %d rows for open trades across rotation", len(preserved_rows))
                        finally:
                            conn2.close()
                if success:
                    outage_tracker.mark_success(event_ticker)
                previous_event_ticker = event_ticker
            else:
                logger.debug("No active event found - continuing with last known market")
                outage_tracker.mark_failure("event_resolution_failed")
            if time.time() - last_heartbeat >= HEARTBEAT_INTERVAL_SEC:
                logger.info("heartbeat")
                last_heartbeat = time.time()
            time.sleep(POLL_INTERVAL_SECONDS)
        except KeyboardInterrupt:
            logger.debug("Kalshi API Market %s Watchdog stopped", SYMBOL)
            break
        except Exception as e:
            logger.error("Unexpected error: %s", e, exc_info=True)
            time.sleep(POLL_INTERVAL_SECONDS)

if __name__ == "__main__":
    POLL_INTERVAL_SECONDS = 1
    main()
