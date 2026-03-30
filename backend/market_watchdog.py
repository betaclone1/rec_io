#!/usr/bin/env python3
"""
Multi-symbol market watchdog (execution exchange + interval). v1: Kalshi 15m only → live_data.market_kalshi_15m.

Rows include `exchange` (e.g. kalshi) after `symbol` so additional venues can share the same table later.

By default, which symbols are polled and in what order matches `live_data.symbols_list` (`ORDER BY id`),
intersected with the Kalshi 15m symbol set. Pass `--symbols` to override.

Legacy kalshi_market_watchdog.py and per-symbol tables stay in place until pipeline cutover.
"""

import argparse
import json
import logging
import os
import sys
import threading
import time
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

import psycopg2
import pytz
import requests
from psycopg2.extras import RealDictCursor

_script_dir = os.path.dirname(os.path.abspath(__file__))
_project_root = os.path.dirname(_script_dir)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

BASE_URL = "https://api.elections.kalshi.com/trade-api/v2"
API_HEADERS = {
    "Accept": "application/json",
    "User-Agent": "KalshiWatcher/1.0",
}
EST = pytz.timezone("America/New_York")

KALSHI_15M_SYMBOLS = frozenset({"BTC", "ETH", "SOL", "XRP"})
EXCHANGE_KALSHI = "kalshi"
UNIFIED_TABLE = "live_data.market_kalshi_15m"
HEARTBEAT_INTERVAL_SEC = 300
# Target wall-clock period for one full pass over all symbols (remainder sleep after work; matches per-process ~1s cadence).
POLL_INTERVAL_SECONDS = 1
DEFAULT_HTTP_429_FALLBACK_SLEEP_SEC = 5.0
MAX_HTTP_429_SLEEP_SEC = 60.0

# Public trade-api v2 REST is a separate quota from WebSocket. Rollover + polling in one process
# must not stampede; 429 almost always means our REST concurrency or shared-IP traffic is wrong.
_KALSHI_TRADE_API_REST_LOCK = threading.Lock()

DB_CONFIG = {
    "host": os.getenv("POSTGRES_HOST", "localhost"),
    "port": os.getenv("POSTGRES_PORT", "5432"),
    "database": os.getenv("POSTGRES_DB", "rec_io_db"),
    "user": os.getenv("POSTGRES_USER", "rec_io_user"),
    "password": os.getenv("POSTGRES_PASSWORD", "rec_io_password"),
}


def format_15m_strike_from_api_floor_strike(floor_strike) -> str:
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


def _http_429_sleep_seconds(resp: requests.Response) -> float:
    """
    Sleep duration for HTTP 429 based on `Retry-After`, with safe fallback caps.
    """
    try:
        ra = resp.headers.get("Retry-After")
        if not ra:
            return DEFAULT_HTTP_429_FALLBACK_SLEEP_SEC
        # Most common: Retry-After is a number of seconds.
        if str(ra).strip().isdigit():
            sec = float(ra)
            return min(MAX_HTTP_429_SLEEP_SEC, max(0.0, sec))
        # Otherwise: HTTP date. We won't parse it robustly; just fallback.
        return DEFAULT_HTTP_429_FALLBACK_SLEEP_SEC
    except Exception:
        return DEFAULT_HTTP_429_FALLBACK_SLEEP_SEC


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
    log = logging.getLogger("market_watchdog")
    if log.handlers:
        return log
    handler = _FlushingStreamHandler(sys.stdout)
    handler.setLevel(logging.DEBUG)
    handler.setFormatter(_est_formatter())
    log.addHandler(handler)
    log.setLevel(logging.INFO)
    return log


logger = _configure_logging()


def _kalshi_public_get(url: str, params=None):
    """
    Single-flight GET to Kalshi public trade API (v2).

    HTTP 429 is logged at ERROR: it is never "expected" for our usage pattern — it means we are
    misusing REST (parallel bursts, tight loops, or another client on the same IP/route).
    Sleep while holding the lock so other threads cannot immediately amplify the limiter.
    """
    with _KALSHI_TRADE_API_REST_LOCK:
        try:
            resp = requests.get(url, params=params, headers=API_HEADERS, timeout=10)
        except Exception:
            logger.exception("Kalshi GET exception url=%s", url)
            raise
        if resp.status_code == 429:
            wait = _http_429_sleep_seconds(resp)
            ra = resp.headers.get("Retry-After")
            logger.error(
                "Kalshi HTTP 429 rate limited (serious / execution issue). url=%s retry_after=%r "
                "sleep=%.1fs — WebSocket subscriptions do not use this quota; check parallel REST, "
                "rollover worker count, or other processes sharing this route.",
                url,
                ra,
                wait,
            )
            time.sleep(wait)
            return None
        return resp


def _iso_now_est():
    return datetime.now(ZoneInfo("America/New_York")).isoformat(timespec="seconds")


class OutageTracker:
    """Per-symbol outage tracking for consolidated watchdog."""

    def __init__(self, exchange: str, market_interval: str, symbol: str):
        self.exchange = exchange
        self.market_interval = market_interval
        self.symbol = symbol.upper()
        self.in_outage = False
        self.started_at = None
        self.last_failure_reason = None
        self.fail_count = 0
        slug = f"{exchange}_{market_interval}_{self.symbol.lower()}"
        self.status_path = Path("logs") / f"market_watchdog_status_{slug}.json"
        self.outage_path = Path("logs") / f"market_watchdog_outages_{slug}.jsonl"
        self.status_path.parent.mkdir(parents=True, exist_ok=True)
        self._write_status(state="healthy")

    def _write_status(self, state, extra=None):
        payload = {
            "service": "market_watchdog",
            "exchange": self.exchange,
            "market": self.market_interval,
            "symbol": self.symbol,
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
            logger.warning(
                "DATA OUTAGE STARTED [%s %s %s] (%s): %s",
                self.exchange,
                self.market_interval,
                self.symbol,
                now.isoformat(timespec="seconds"),
                reason,
            )
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
                "DATA OUTAGE ENDED [%s %s %s] (%s): duration=%ss fail_count=%s recovered_event=%s",
                self.exchange,
                self.market_interval,
                self.symbol,
                now.isoformat(timespec="seconds"),
                duration_sec,
                self.fail_count,
                event_ticker,
            )
            self._append_outage_event(
                {
                    "service": "market_watchdog",
                    "exchange": self.exchange,
                    "market": self.market_interval,
                    "symbol": self.symbol,
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
    if legacy_cents is not None:
        return legacy_cents
    if dollars_val is not None and str(dollars_val).strip() != "":
        try:
            return int(round(float(dollars_val) * 100))
        except (TypeError, ValueError):
            pass
    return 0


def _fixed_point_text(value, default="0.00"):
    if value is None or value == "":
        return default
    try:
        return f"{float(value):.2f}"
    except (TypeError, ValueError):
        return default


def connect_database():
    try:
        return psycopg2.connect(**DB_CONFIG)
    except Exception as e:
        logger.error("Database connection failed: %s", e)
        return None


DEFAULT_KALSHI_15M_SYMBOL_ORDER = ("BTC", "ETH", "SOL", "XRP")


def fetch_kalshi_15m_symbols_ordered_from_db() -> tuple[str, ...]:
    """
    Kalshi 15m symbols in the same order as live_data.symbols_list (by id).
    Only includes symbols in KALSHI_15M_SYMBOLS; duplicates in the list are skipped (first wins).
    """
    conn = connect_database()
    if not conn:
        logger.warning(
            "Could not load symbols_list (no DB); using default order %s",
            DEFAULT_KALSHI_15M_SYMBOL_ORDER,
        )
        return DEFAULT_KALSHI_15M_SYMBOL_ORDER
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT symbol FROM live_data.symbols_list
            WHERE symbol IS NOT NULL AND trim(symbol) <> ''
            ORDER BY id
            """
        )
        seen: set[str] = set()
        ordered: list[str] = []
        for (raw,) in cursor.fetchall():
            u = raw.strip().upper()
            if u in KALSHI_15M_SYMBOLS and u not in seen:
                seen.add(u)
                ordered.append(u)
        conn.close()
        if not ordered:
            logger.warning(
                "symbols_list has no Kalshi 15m symbols; using default order %s",
                DEFAULT_KALSHI_15M_SYMBOL_ORDER,
            )
            return DEFAULT_KALSHI_15M_SYMBOL_ORDER
        return tuple(ordered)
    except Exception as e:
        logger.warning(
            "symbols_list read failed (%s); using default order %s",
            e,
            DEFAULT_KALSHI_15M_SYMBOL_ORDER,
        )
        try:
            conn.close()
        except Exception:
            pass
        return DEFAULT_KALSHI_15M_SYMBOL_ORDER


def ensure_unified_15m_table(connection):
    """CREATE IF NOT EXISTS (matches post-migration shape with exchange column)."""
    sql = """
    CREATE TABLE IF NOT EXISTS live_data.market_kalshi_15m (
        id SERIAL PRIMARY KEY,
        symbol VARCHAR(10) NOT NULL,
        exchange VARCHAR(20) NOT NULL,
        event_ticker VARCHAR(50) NOT NULL,
        market_ticker VARCHAR(100) NOT NULL,
        market TEXT DEFAULT '15m',
        strike VARCHAR(20),
        yes_bid_dollars TEXT,
        yes_ask_dollars TEXT,
        no_bid_dollars TEXT,
        no_ask_dollars TEXT,
        last_price_dollars TEXT,
        volume_fp TEXT,
        open_interest_fp TEXT,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
        updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
        CONSTRAINT market_kalshi_15m_exchange_symbol_event_market_unique
            UNIQUE (exchange, symbol, event_ticker, market_ticker)
    );
    """
    cur = connection.cursor()
    cur.execute(sql)
    try:
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS market_kalshi_15m_exchange_symbol_idx
                ON live_data.market_kalshi_15m USING btree (exchange, symbol);
            """
        )
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS market_kalshi_15m_exchange_symbol_event_idx
                ON live_data.market_kalshi_15m USING btree (exchange, symbol, event_ticker);
            """
        )
    except Exception:
        pass
    connection.commit()


def get_open_trade_tickers_for_symbol(connection, table_name: str, symbol_upper: str, exchange: str):
    try:
        cursor = connection.cursor()
        cursor.execute(
            """
            SELECT DISTINCT ticker FROM users.trades_0001
            WHERE status IN ('pending', 'open') AND symbol = %s AND ticker IS NOT NULL
            """,
            (symbol_upper,),
        )
        open_tickers = {row[0] for row in cursor.fetchall()}
        if not open_tickers:
            return set()
        cursor.execute(
            f"""
            SELECT market_ticker FROM {table_name}
            WHERE market_ticker IN %s AND symbol = %s AND exchange = %s
            """,
            (tuple(open_tickers), symbol_upper, exchange),
        )
        return {row[0] for row in cursor.fetchall()}
    except Exception as e:
        logger.warning("get_open_trade_tickers_for_symbol failed: %s", e)
        return set()


def fetch_rows_for_tickers(connection, table_name: str, symbol_upper: str, exchange: str, tickers):
    if not tickers:
        return []
    try:
        cursor = connection.cursor(cursor_factory=RealDictCursor)
        cursor.execute(
            f"""
            SELECT * FROM {table_name}
            WHERE market_ticker IN %s AND symbol = %s AND exchange = %s
            """,
            (tuple(tickers), symbol_upper, exchange),
        )
        return cursor.fetchall()
    except Exception as e:
        logger.warning("fetch_rows_for_tickers failed: %s", e)
        return []


def reinsert_preserved_rows(connection, table_name: str, rows):
    if not rows:
        return
    cols = [k for k in rows[0].keys() if k != "id"]
    cols_str = ", ".join(cols)
    placeholders = ", ".join(["%s"] * len(cols))
    sql = f"INSERT INTO {table_name} ({cols_str}) VALUES ({placeholders})"
    cursor = connection.cursor()
    for row in rows:
        vals = [row[c] for c in cols]
        cursor.execute(sql, vals)


def next_15m_close_est():
    now = datetime.now(EST)
    base = now.replace(second=0, microsecond=0)
    minute = now.minute
    next_15 = ((minute // 15) + 1) * 15
    if next_15 >= 60:
        return base.replace(minute=0) + timedelta(hours=1)
    return base.replace(minute=next_15)


def fetch_event_json(event_ticker: str):
    url = f"{BASE_URL}/events/{event_ticker}"
    try:
        response = _kalshi_public_get(url)
        if response is None:
            return None
        response.raise_for_status()
        data = response.json()
        if "error" in data:
            logger.warning("API returned error for ticker %s: %s", event_ticker, data["error"])
            return None
        return data
    except Exception as e:
        logger.warning("Exception fetching event JSON: %s", e)
        return None


def get_current_event_ticker_15m(symbol: str, last_failed_by_symbol: dict):
    """Resolve active 15m Kalshi event for symbol; last_failed_by_symbol tracks log dedupe per symbol."""
    sym_u = symbol.upper()
    close_time = next_15m_close_est()
    close_utc = close_time.astimezone(pytz.UTC)
    target_ts = close_utc.strftime("%Y-%m-%dT%H:%M")

    try:
        list_url = f"{BASE_URL}/events"
        resp = _kalshi_public_get(list_url, params={"series_ticker": f"KX{sym_u}15M"})
        if resp is None:
            if last_failed_by_symbol.get(sym_u) != target_ts:
                last_failed_by_symbol[sym_u] = target_ts
            return None, None
        if not resp.ok:
            if last_failed_by_symbol.get(sym_u) != target_ts:
                logger.warning("15m list failed [%s]: %s", sym_u, resp.status_code)
                last_failed_by_symbol[sym_u] = target_ts
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
                    last_failed_by_symbol[sym_u] = None
                    return event_ticker, data
                break
    except Exception as e:
        logger.warning("15m resolve error [%s]: %s", sym_u, e)
    if last_failed_by_symbol.get(sym_u) != target_ts:
        logger.debug(
            "No 15m event for [%s] window closing %s EST",
            sym_u,
            close_time.strftime("%H:%M"),
        )
        last_failed_by_symbol[sym_u] = target_ts
    return None, None


_hourly_event_resolve_last_failed: dict[str, str | None] = {}


def get_current_event_ticker(symbol: str, interval: str = "hourly"):
    """
    Resolve Kalshi hourly crypto event (BTC/ETH) by constructing the period event ticker for the
    upcoming hour (America/New_York wall clock) and fetching ``/events/{ticker}``.

    The 15m WebSocket rollover path uses :func:`get_current_event_ticker_15m` with a
    ``last_failed_by_symbol`` dict instead.

    Same ticker construction as ``kalshi_market_watchdog.get_current_event_ticker``; uses this
    module's serialized :func:`fetch_event_json` so REST stays quota-safe alongside rollover.
    """
    sym_u = (symbol or "").strip().upper()
    iv = (interval or "hourly").strip().lower()
    if iv == "15m":
        raise ValueError(
            "use get_current_event_ticker_15m(symbol, last_failed_by_symbol) for the 15m WS path"
        )
    if iv != "hourly":
        logger.warning("get_current_event_ticker: unsupported interval %r", interval)
        return None, None

    symbol_config = {
        "BTC": "KXBTCD",
        "ETH": "KXETHD",
    }
    prefix = symbol_config.get(sym_u)
    if not prefix:
        logger.error("Unsupported symbol for hourly Kalshi discovery: %s", symbol)
        return None, None

    now = datetime.now(EST)
    test_time = now + timedelta(hours=1)
    year_str = test_time.strftime("%y")
    month_str = test_time.strftime("%b").upper()
    day_str = test_time.strftime("%d")
    hour_str = test_time.strftime("%H")
    current_ticker = f"{prefix}-{year_str}{month_str}{day_str}{hour_str}"

    data = fetch_event_json(current_ticker)
    if data and "markets" in data:
        _hourly_event_resolve_last_failed[sym_u] = None
        return current_ticker, data

    prev = _hourly_event_resolve_last_failed.get(sym_u)
    if prev != current_ticker:
        logger.warning("Failed to fetch hourly event data for %s", current_ticker)
        _hourly_event_resolve_last_failed[sym_u] = current_ticker
    return None, None


def save_kalshi_15m_unified(
    event_ticker: str, markets_data: list, symbol_upper: str, exchange: str
) -> bool:
    connection = connect_database()
    if not connection:
        return False
    try:
        cursor = connection.cursor()
        sym = symbol_upper.upper()
        br = exchange.lower().strip()
        market_val = "15m"
        for market in markets_data:
            try:
                market_ticker = market.get("ticker", "")
                subtitle = market.get("subtitle", "")
                strike = subtitle.split(" or above")[0].strip() if " or above" in subtitle else ""
                if market.get("floor_strike") is not None:
                    strike = format_15m_strike_from_api_floor_strike(market.get("floor_strike"))

                yes_bid_dollars = market.get("yes_bid_dollars")
                yes_ask_dollars = market.get("yes_ask_dollars")
                no_bid_dollars = market.get("no_bid_dollars")
                no_ask_dollars = market.get("no_ask_dollars")
                last_price_dollars = market.get("last_price_dollars")
                volume_fp = _fixed_point_text(
                    market.get("volume_fp"),
                    default=_fixed_point_text(market.get("volume", "0.00")),
                )
                open_interest_fp = _fixed_point_text(
                    market.get("open_interest_fp", market.get("open_interest", "0.00"))
                )

                cursor.execute(
                    f"""
                    INSERT INTO {UNIFIED_TABLE}
                    (symbol, exchange, event_ticker, market_ticker, market, strike,
                     yes_bid_dollars, yes_ask_dollars, no_bid_dollars, no_ask_dollars, last_price_dollars,
                     volume_fp, open_interest_fp, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
                    ON CONFLICT (exchange, symbol, event_ticker, market_ticker) DO UPDATE SET
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
                        sym,
                        br,
                        event_ticker,
                        market_ticker,
                        market_val,
                        strike,
                        yes_bid_dollars,
                        yes_ask_dollars,
                        no_bid_dollars,
                        no_ask_dollars,
                        last_price_dollars,
                        volume_fp,
                        open_interest_fp,
                    ),
                )
            except Exception as e:
                logger.warning(
                    "Error processing market [%s] %s: %s",
                    sym,
                    market.get("ticker", "unknown"),
                    e,
                )
                continue
        connection.commit()
        connection.close()
        logger.debug("Saved %s markets to PostgreSQL for %s %s", len(markets_data), sym, event_ticker)
        return True
    except Exception as e:
        logger.error("Error saving to PostgreSQL: %s", e)
        if connection:
            connection.rollback()
            connection.close()
        return False


def get_one_minute_avg_at_time(connection, symbol_upper: str, opening_time_est):
    table = f"live_data.live_price_log_1s_{symbol_upper.lower()}"
    opening_str = opening_time_est.strftime("%Y-%m-%dT%H:%M:%S")
    try:
        cursor = connection.cursor()
        cursor.execute(
            f"""
            SELECT one_minute_avg FROM {table}
            WHERE timestamp::timestamp >= %s::timestamp - interval '2 minutes'
              AND timestamp::timestamp <= %s::timestamp + interval '2 minutes'
            ORDER BY ABS(EXTRACT(EPOCH FROM (timestamp::timestamp - %s::timestamp)))
            LIMIT 1
            """,
            (opening_str, opening_str, opening_str),
        )
        row = cursor.fetchone()
        return float(row[0]) if row and row[0] is not None else None
    except Exception as e:
        logger.debug("get_one_minute_avg_at_time: %s", e)
        return None


def backfill_15m_strike_unified(symbol_upper: str, event_ticker: str, exchange: str) -> bool:
    connection = connect_database()
    if not connection:
        return False
    sym = symbol_upper.upper()
    br = exchange.lower().strip()
    try:
        cursor = connection.cursor()
        cursor.execute(
            f"""
            SELECT 1 FROM {UNIFIED_TABLE}
            WHERE event_ticker = %s AND symbol = %s AND exchange = %s
              AND strike IS NOT NULL
              AND trim(strike) <> ''
            LIMIT 1
            """,
            (event_ticker, sym, br),
        )
        if cursor.fetchone():
            logger.debug(
                "15m backfill skipped: strike already set for %s event %s",
                sym,
                event_ticker,
            )
            connection.close()
            return False

        close_time = next_15m_close_est()
        opening_time = close_time - timedelta(minutes=15)
        one_min_avg = get_one_minute_avg_at_time(connection, sym, opening_time)
        if one_min_avg is None:
            logger.debug(
                "No one_minute_avg at opening %s EST for %s",
                opening_time.strftime("%H:%M"),
                sym,
            )
            connection.close()
            return False
        strike_str = f"${one_min_avg:,.2f}"
        cursor.execute(
            f"""
            UPDATE {UNIFIED_TABLE} SET strike = %s, updated_at = NOW()
            WHERE event_ticker = %s AND symbol = %s AND exchange = %s
            """,
            (strike_str, event_ticker, sym, br),
        )
        connection.commit()
        logger.debug(
            "15m strike set [%s] to %s (1m avg at %s EST)",
            sym,
            strike_str,
            opening_time.strftime("%H:%M"),
        )
        connection.close()
        return True
    except Exception as e:
        logger.warning("backfill_15m_strike [%s]: %s", sym, e)
        if connection:
            connection.rollback()
            connection.close()
        return False


def run_kalshi_15m(symbols: tuple[str, ...], exchange: str):
    for s in symbols:
        if s.upper() not in KALSHI_15M_SYMBOLS:
            logger.error("Kalshi 15m does not support symbol %s (allowed: %s)", s, sorted(KALSHI_15M_SYMBOLS))
            sys.exit(1)

    normalized = tuple(s.upper() for s in symbols)
    exchange_key = exchange.lower().strip()
    logger.info(
        "Starting market_watchdog exchange=%s market=15m symbols=%s",
        exchange_key,
        ",".join(normalized),
    )

    conn0 = connect_database()
    if conn0:
        ensure_unified_15m_table(conn0)
        conn0.close()

    previous_event = {s: None for s in normalized}
    last_failed_by_symbol = {}
    outage_by_symbol = {s: OutageTracker(exchange_key, "15m", s) for s in normalized}
    last_heartbeat = time.time()

    while True:
        loop_started = time.time()
        try:
            for sym in normalized:
                event_ticker, event_data = get_current_event_ticker_15m(sym, last_failed_by_symbol)
                preserved_rows = []
                table_ref = UNIFIED_TABLE
                if event_ticker and event_data and "markets" in event_data:
                    prev = previous_event[sym]
                    if prev and prev != event_ticker:
                        logger.info(
                            "[%s] Market rotated: %s -> %s (%s tickers)",
                            sym,
                            prev,
                            event_ticker,
                            len(event_data.get("markets", [])),
                        )
                        connection = connect_database()
                        if connection:
                            preserve_tickers = get_open_trade_tickers_for_symbol(
                                connection, table_ref, sym, exchange_key
                            )
                            if preserve_tickers:
                                preserved_rows = fetch_rows_for_tickers(
                                    connection, table_ref, sym, exchange_key, preserve_tickers
                                )
                            cur = connection.cursor()
                            cur.execute(
                                f"DELETE FROM {table_ref} WHERE symbol = %s AND exchange = %s",
                                (sym, exchange_key),
                            )
                            connection.commit()
                            connection.close()

                    filtered_markets = event_data["markets"]
                    success = save_kalshi_15m_unified(event_ticker, filtered_markets, sym, exchange_key)
                    if not success:
                        logger.error("[%s] Failed to save data for %s", sym, event_ticker)
                        outage_by_symbol[sym].mark_failure(f"save_failed event={event_ticker}")
                    else:
                        if prev is None or prev != event_ticker:
                            backfill_15m_strike_unified(sym, event_ticker, exchange_key)
                    if preserved_rows:
                        conn2 = connect_database()
                        if conn2:
                            try:
                                reinsert_preserved_rows(conn2, table_ref, preserved_rows)
                                conn2.commit()
                                logger.info(
                                    "[%s] Preserved %d rows for open trades across rotation",
                                    sym,
                                    len(preserved_rows),
                                )
                            finally:
                                conn2.close()
                    if success:
                        outage_by_symbol[sym].mark_success(event_ticker)
                    previous_event[sym] = event_ticker
                else:
                    logger.debug("[%s] No active event - continuing", sym)
                    outage_by_symbol[sym].mark_failure("event_resolution_failed")

            if time.time() - last_heartbeat >= HEARTBEAT_INTERVAL_SEC:
                logger.info("heartbeat")
                last_heartbeat = time.time()
            slip = POLL_INTERVAL_SECONDS - (time.time() - loop_started)
            if slip > 0:
                time.sleep(slip)
        except KeyboardInterrupt:
            logger.debug("market_watchdog stopped")
            break
        except Exception as e:
            logger.error("Unexpected error: %s", e, exc_info=True)
            time.sleep(POLL_INTERVAL_SECONDS)


def main():
    parser = argparse.ArgumentParser(description="Multi-symbol market watchdog (exchange + market).")
    parser.add_argument(
        "--exchange",
        default=None,
        help="Execution venue (v1: kalshi). Default kalshi if neither --exchange nor --broker set.",
    )
    parser.add_argument(
        "--broker",
        default=None,
        dest="legacy_broker",
        help="Deprecated: same as --exchange",
    )
    parser.add_argument(
        "--market",
        required=True,
        choices=("15m", "hourly"),
        help="Market interval (v1 implements kalshi+15m only)",
    )
    parser.add_argument(
        "--symbols",
        nargs="*",
        default=None,
        metavar="SYM",
        help=(
            "Symbols to poll, in this order. If omitted, order and membership follow "
            "live_data.symbols_list (by id), restricted to Kalshi 15m symbols."
        ),
    )
    args = parser.parse_args()
    venue = (args.exchange or args.legacy_broker or "kalshi").lower().strip()
    if venue != EXCHANGE_KALSHI:
        logger.error("Only exchange kalshi is implemented; got %s", venue)
        sys.exit(1)
    if args.market != "15m":
        logger.error("Only --market 15m is implemented; got %s", args.market)
        sys.exit(1)
    if args.symbols:
        symbols_to_run = tuple(s.strip().upper() for s in args.symbols if s.strip())
        if not symbols_to_run:
            symbols_to_run = fetch_kalshi_15m_symbols_ordered_from_db()
    else:
        symbols_to_run = fetch_kalshi_15m_symbols_ordered_from_db()
    run_kalshi_15m(symbols_to_run, venue)


if __name__ == "__main__":
    main()
