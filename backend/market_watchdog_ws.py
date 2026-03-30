#!/usr/bin/env python3
"""
Kalshi 15m: REST only at each quarter-hour rollover (wipe → event JSON → seed DB).
All other time: WebSocket ``ticker`` updates only (same table columns as REST snapshot on seed).

Hourly: after REST event discovery, markets are capped to an ATM-centered window
(``MARKET_WATCHDOG_WS_HOURLY_ATM_STRIKES_EACH_SIDE`` per side, default 20) before
seed + WS subscribe so DB/CPU track ~41 strikes per symbol instead of the full Kalshi ladder.

Rollover sets ``rolling`` so the WS thread skips DB writes until seed + new subscribe are done.

HTTP 429 on Kalshi is **REST quota**, not WebSocket. If we see it while only running this pipeline,
treat it as our bug: parallel REST during rollover, tight refetch loops, or another client sharing
the same public API route. Public GETs from this repo process are serialized in
``backend.market_watchdog._kalshi_public_get``.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import logging
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import psycopg2.pool
import websockets
from websockets.exceptions import ConnectionClosed, WebSocketException

from backend.core.kalshi_market_normalize import (
    strike_from_kalshi_15m_rest_market,
    ticker_msg_to_row_values,
)
from backend.core.kalshi_ws_auth import kalshi_ws_connect_headers
from backend.core.config.database import get_postgresql_connection
from backend.market_watchdog import (
    DB_CONFIG,
    EST,
    EXCHANGE_KALSHI,
    KALSHI_15M_SYMBOLS,
    HEARTBEAT_INTERVAL_SEC,
    connect_database,
    fetch_event_json,
    fetch_kalshi_15m_symbols_ordered_from_db,
    get_current_event_ticker,
    get_current_event_ticker_15m,
    next_15m_close_est,
)

WS_URL = "wss://api.elections.kalshi.com/trade-api/ws/v2"
WS_TABLE = "live_data.market_kalshi_15m"
WS_TABLE_HOURLY = "live_data.market_kalshi_hourly"
KALSHI_HOURLY_SYMBOLS = ("BTC", "ETH")
DEFAULT_HOUR_ROLLOVER_SKEW_SEC = 0
DEFAULT_WS_PING_INTERVAL_SEC = 25
DEFAULT_WS_TRANSPORT_BEAT_SEC = 25

DEFAULT_QUARTER_ROLLOVER_SKEW_SEC = 0
DEFAULT_DB_CONNECT_RETRY_SEC = 90.0
DEFAULT_WS_FLOW_VERIFY_SEC = 120.0
# Hourly books are wide; Kalshi often sends no ticker for illiquid strikes — do not require every ticker.
DEFAULT_HOURLY_WS_VERIFY_SEC = 240.0
DEFAULT_HOURLY_TICK_VERIFY_FRAC = 0.10
DEFAULT_HOURLY_TICK_VERIFY_MIN = 20
DEFAULT_CYCLE_RETRY_SEC = 10.0
DEFAULT_DB_POOL_MAX_CONN = 16
DEFAULT_DISCOVERY_SLEEP_SEC = 2.0
# Upper bound for how long we will keep polling REST during a single 15m rollover discovery
# (prevents runaway 429s / infinite loops).
DEFAULT_DISCOVERY_MAX_WAIT_SEC = 120.0
# Default 1: resolve symbols one-at-a-time over REST so rollover never bursts parallel GETs.
# Override with MARKET_WATCHDOG_WS_ROLLOVER_REST_WORKERS=2..8 only if you accept 429 risk.
DEFAULT_ROLLOVER_REST_MAX_WORKERS = 1
# Hourly: keep only strikes within N steps of spot on the sorted ladder (seed + WS subscribe + DB rows).
# Set MARKET_WATCHDOG_WS_HOURLY_ATM_STRIKES_EACH_SIDE=0 to disable (full Kalshi event list).
DEFAULT_HOURLY_ATM_STRIKES_EACH_SIDE = 20

_POOL_LOCK = threading.Lock()
_DB_POOL: psycopg2.pool.ThreadedConnectionPool | None = None

def _ticker_upsert_sql(table_ref: str) -> str:
    return f"""
INSERT INTO {table_ref} AS ws
    (symbol, exchange, event_ticker, market_ticker, market, strike,
     yes_bid_dollars, yes_ask_dollars, no_bid_dollars, no_ask_dollars, last_price_dollars,
     volume_fp, open_interest_fp, updated_at)
VALUES
    (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
ON CONFLICT (exchange, symbol, event_ticker, market_ticker) DO UPDATE SET
    market = EXCLUDED.market,
    strike = COALESCE(EXCLUDED.strike, ws.strike),
    yes_bid_dollars = EXCLUDED.yes_bid_dollars,
    yes_ask_dollars = EXCLUDED.yes_ask_dollars,
    no_bid_dollars = EXCLUDED.no_bid_dollars,
    no_ask_dollars = EXCLUDED.no_ask_dollars,
    last_price_dollars = EXCLUDED.last_price_dollars,
    volume_fp = EXCLUDED.volume_fp,
    open_interest_fp = EXCLUDED.open_interest_fp,
    updated_at = NOW()
"""


_TICKER_UPSERT_SQL_ACTIVE = _ticker_upsert_sql(WS_TABLE)
_WS_TRANSPORT_CTX: dict[str, object] = {
    "exchange": "kalshi",
    "market": "15m",
    "symbols": (),
}


def _configure_logging():
    log = logging.getLogger("market_watchdog_ws")
    if log.handlers:
        return log

    class ESTFormatter(logging.Formatter):
        def formatTime(self, record, datefmt=None):
            dt = datetime.fromtimestamp(record.created, tz=ZoneInfo("America/New_York"))
            if datefmt:
                return dt.strftime(datefmt)
            s = dt.strftime("%Y-%m-%dT%H:%M:%S")
            z = dt.strftime("%z")
            return s + (z[:3] + ":" + z[3:] if len(z) >= 5 else z)

    class FlushHandler(logging.StreamHandler):
        def emit(self, record):
            super().emit(record)
            self.flush()

    h = FlushHandler(sys.stdout)
    h.setFormatter(ESTFormatter("%(asctime)s %(levelname)s [%(name)s] %(message)s"))
    log.addHandler(h)
    log.setLevel(logging.INFO)
    return log


logger = _configure_logging()


def _init_db_pool(maxconn: int) -> bool:
    global _DB_POOL
    maxconn = max(2, min(64, int(maxconn)))
    minconn = max(1, min(4, maxconn // 4 or 1))
    with _POOL_LOCK:
        if _DB_POOL is not None:
            return True
        try:
            _DB_POOL = psycopg2.pool.ThreadedConnectionPool(minconn, maxconn, **DB_CONFIG)
            logger.info("db ThreadedConnectionPool min=%s max=%s", minconn, maxconn)
            return True
        except Exception:
            logger.exception("db pool init failed; will use connect_database per call")
            _DB_POOL = None
            return False


def _close_db_pool() -> None:
    global _DB_POOL
    with _POOL_LOCK:
        p = _DB_POOL
        _DB_POOL = None
    if p is not None:
        try:
            p.closeall()
            logger.info("db pool closed")
        except Exception as e:
            logger.warning("db pool closeall: %s", e)


def _borrow_conn_retry(label: str, max_wait_sec: float):
    deadline = time.monotonic() + max_wait_sec
    delay = 0.5
    while time.monotonic() < deadline:
        p = _DB_POOL
        if p is not None:
            try:
                return p.getconn()
            except Exception as e:
                logger.warning("%s pool getconn failed: %s", label, e)
        else:
            conn = connect_database()
            if conn:
                return conn
        remain = deadline - time.monotonic()
        sleep_s = min(delay, max(0.05, remain))
        logger.warning(
            "%s: db borrow failed, retry in %.1fs (%.0fs left)",
            label,
            sleep_s,
            max(0.0, remain),
        )
        time.sleep(sleep_s)
        delay = min(delay * 1.6, 10.0)
    logger.error("%s: could not borrow db connection after %.0fs", label, max_wait_sec)
    return None


def _return_conn(conn) -> None:
    if conn is None:
        return
    p = _DB_POOL
    if p is not None:
        try:
            p.putconn(conn)
        except Exception as e:
            logger.warning("putconn failed, closing: %s", e)
            try:
                conn.close()
            except Exception:
                pass
    else:
        try:
            conn.close()
        except Exception:
            pass


def _normalize_row_for_canonical_15m(row: tuple) -> tuple:
    sym, br, ev, mt, mv, strike, yb, ya, nb, na, lp, vf, oif = row
    return (sym, br, ev, mt, mv, strike, yb, ya, nb, na, lp, vf, oif)


def ensure_ws_15m_table(conn) -> None:
    cur = conn.cursor()
    cur.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {WS_TABLE} (
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
    )
    conn.commit()


def ensure_ws_hourly_table(conn) -> None:
    cur = conn.cursor()
    cur.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {WS_TABLE_HOURLY} (
            id SERIAL PRIMARY KEY,
            symbol VARCHAR(10) NOT NULL,
            exchange VARCHAR(20) NOT NULL,
            event_ticker VARCHAR(50) NOT NULL,
            market_ticker VARCHAR(100) NOT NULL,
            market TEXT DEFAULT 'hourly',
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
            CONSTRAINT market_kalshi_hourly_ex_sym_evt_mkt_uniq
                UNIQUE (exchange, symbol, event_ticker, market_ticker)
        );
        """
    )
    conn.commit()


# --- REST (rollover only) ---


def _nonempty_str(v: object) -> bool:
    if v is None:
        return False
    s = str(v).strip()
    return bool(s)


def _markets_all_have_usable_strike_inputs(event_data: dict) -> bool:
    """
    Rollover readiness gate.

    Hard requirement for a usable strike table:
      - explicit `floor_strike` for every market row
      - `yes_ask_dollars`
      - `yes_bid_dollars`

    If strike metadata is temporarily missing for a symbol on the new event, that symbol
    stays pending until it has full data.
    """
    markets = event_data.get("markets") or []
    if not markets:
        return False
    for m in markets:
        if not isinstance(m, dict):
            return False
        if m.get("floor_strike") is None:
            return False
        if not _nonempty_str(m.get("yes_ask_dollars")):
            return False
        if not _nonempty_str(m.get("yes_bid_dollars")):
            return False
    return True


def _refetch_event_until_markets_usable(
    event_ticker: str,
    *,
    max_wait_sec: float,
    sleep_sec: float,
) -> dict:
    deadline = time.monotonic() + max_wait_sec
    attempt = 0
    last_log = 0.0
    while time.monotonic() < deadline:
        ed = fetch_event_json(event_ticker)
        if ed and ed.get("markets") and len(ed["markets"]) > 0 and _markets_all_have_usable_strike_inputs(ed):
            return ed
        attempt += 1
        now = time.monotonic()
        if now - last_log >= 30.0:
            logger.info(
                "waiting for usable strike inputs on all markets event=%s REST attempts=%s",
                event_ticker,
                attempt,
            )
            last_log = now
        time.sleep(sleep_sec)
    # Return last attempt result if present; otherwise an empty dict to signal failure.
    return fetch_event_json(event_ticker) or {}


def _resolve_one_symbol_until_ready(
    sym: str,
    last_failed: dict,
    *,
    max_wait_sec: float,
    sleep_sec: float,
) -> tuple[str, tuple[str | None, dict]]:
    sym_u = sym.upper()
    deadline = time.monotonic() + max_wait_sec
    attempt = 0
    while time.monotonic() < deadline:
        et, ed = get_current_event_ticker_15m(sym_u, last_failed)
        attempt += 1
        if et and ed and ed.get("markets") and len(ed["markets"]) > 0:
            if not _markets_all_have_usable_strike_inputs(ed):
                remaining = max(0.0, deadline - time.monotonic())
                ed = _refetch_event_until_markets_usable(
                    et, max_wait_sec=remaining, sleep_sec=sleep_sec
                )
            if _markets_all_have_usable_strike_inputs(ed):
                logger.info(
                    "[%s] resolved event=%s markets=%s (usable strike inputs complete)",
                    sym_u,
                    et,
                    len(ed.get("markets") or []),
                )
                return sym_u, (et, ed)
        time.sleep(sleep_sec)

    logger.warning(
        "[%s] rollover discovery timed out after %.0fs; returning incomplete event/markets",
        sym_u,
        max_wait_sec,
    )
    return sym_u, (None, {})


def _rollover_rest_max_workers(symbol_count: int) -> int:
    raw = os.environ.get("MARKET_WATCHDOG_WS_ROLLOVER_REST_WORKERS", "").strip()
    if not raw:
        cap = DEFAULT_ROLLOVER_REST_MAX_WORKERS
    else:
        try:
            cap = int(raw)
        except ValueError:
            cap = DEFAULT_ROLLOVER_REST_MAX_WORKERS
    n = max(1, symbol_count)
    return max(1, min(cap, 8, n))


def _discover_all(
    symbols: tuple[str, ...],
    last_failed: dict,
    *,
    max_wait_sec: float,
    sleep_sec: float,
) -> dict[str, tuple[str | None, dict]]:
    resolved: dict[str, tuple[str, dict]] = {}
    workers = _rollover_rest_max_workers(len(symbols))
    if len(symbols) > 1 and workers > 1:
        logger.warning(
            "rollover REST discovery using %s parallel workers (set MARKET_WATCHDOG_WS_ROLLOVER_REST_WORKERS=1 to avoid Kalshi REST bursts)",
            workers,
        )
    with ThreadPoolExecutor(max_workers=workers) as pool:
        fmap = {
            pool.submit(
                _resolve_one_symbol_until_ready,
                s,
                last_failed,
                max_wait_sec=max_wait_sec,
                sleep_sec=sleep_sec,
            ): s.upper()
            for s in symbols
        }
        for fut in as_completed(fmap):
            sym_u, pair = fut.result()
            resolved[sym_u] = pair
    return resolved


def _expected_row_count(resolved: dict[str, tuple[str, dict]]) -> int:
    n = 0
    for _, (_, ed) in resolved.items():
        for market in ed.get("markets") or []:
            mt = market.get("ticker") or market.get("market_ticker") or ""
            if mt:
                n += 1
    return n


def _numeric_strike_from_rest_market(market: dict) -> float | None:
    s = strike_from_kalshi_15m_rest_market(market)
    if not s:
        return None
    try:
        return float(str(s).replace("$", "").replace(",", "").strip())
    except ValueError:
        return None


def _hourly_spot_price(sym_u: str) -> float | None:
    """Align with strike pipeline: live_symbol_status, then 1s price log."""
    sym_u = sym_u.upper().strip()
    conn = get_postgresql_connection()
    if not conn:
        return None
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT COALESCE(one_minute_avg, price)
            FROM live_data.live_symbol_status
            WHERE symbol = %s
            LIMIT 1
            """,
            (sym_u,),
        )
        row = cur.fetchone()
        if row and row[0] is not None:
            return float(row[0])
        pt = {"BTC": "live_price_log_1s_btc", "ETH": "live_price_log_1s_eth"}.get(sym_u)
        if pt:
            cur.execute(
                f"SELECT price FROM live_data.{pt} ORDER BY timestamp DESC LIMIT 1"
            )
            row2 = cur.fetchone()
            if row2 and row2[0] is not None:
                return float(row2[0])
    except Exception:
        logger.debug("hourly spot price lookup failed for %s", sym_u, exc_info=True)
    finally:
        conn.close()
    return None


def _filter_hourly_markets_atm_window(
    markets: list,
    symbol: str,
    *,
    strikes_each_side: int,
) -> list:
    """
    Keep at most (2 * strikes_each_side + 1) markets: ``strikes_each_side`` ladder steps
    below and above the strike closest to spot (sorted by Kalshi strike).
    """
    if not markets or strikes_each_side <= 0:
        return list(markets)
    sym_u = str(symbol).upper().strip()
    pairs: list[tuple[float, dict]] = []
    for m in markets:
        fs = _numeric_strike_from_rest_market(m)
        if fs is not None:
            pairs.append((fs, m))
    if not pairs:
        logger.warning(
            "hourly ATM cap: no parseable strikes for %s; keeping all %s markets",
            sym_u,
            len(markets),
        )
        return list(markets)
    pairs.sort(key=lambda x: x[0])
    strikes = [p[0] for p in pairs]
    spot = _hourly_spot_price(sym_u)
    if spot is None:
        spot = strikes[len(strikes) // 2]
        logger.warning(
            "hourly ATM cap: no spot for %s; using median strike %.2f for window",
            sym_u,
            spot,
        )
    best_i = min(range(len(strikes)), key=lambda i: abs(strikes[i] - spot))
    lo = max(0, best_i - strikes_each_side)
    hi = min(len(pairs) - 1, best_i + strikes_each_side)
    kept = pairs[lo : hi + 1]
    out = [m for _, m in kept]
    logger.info(
        "hourly ATM cap %s: markets %s -> %s (spot=%.2f idx=%s slice [%s,%s] side=%s)",
        sym_u,
        len(markets),
        len(out),
        spot,
        best_i,
        lo,
        hi,
        strikes_each_side,
    )
    return out


def _apply_hourly_atm_market_cap(
    ready: dict[str, tuple[str | None, dict]],
) -> dict[str, tuple[str | None, dict]]:
    raw = os.getenv(
        "MARKET_WATCHDOG_WS_HOURLY_ATM_STRIKES_EACH_SIDE",
        str(DEFAULT_HOURLY_ATM_STRIKES_EACH_SIDE),
    ).strip()
    try:
        n = int(raw)
    except ValueError:
        n = DEFAULT_HOURLY_ATM_STRIKES_EACH_SIDE
    if n <= 0:
        return ready
    out: dict[str, tuple[str | None, dict]] = {}
    for sym, pair in ready.items():
        et, ed = pair
        mk = list(ed.get("markets") or [])
        if not mk:
            out[sym] = pair
            continue
        filtered = _filter_hourly_markets_atm_window(mk, sym, strikes_each_side=n)
        if not filtered:
            logger.warning(
                "hourly ATM filter empty for %s; using full %s markets", sym, len(mk)
            )
            out[sym] = pair
            continue
        new_ed = dict(ed)
        new_ed["markets"] = filtered
        out[sym] = (et, new_ed)
    return out


def _seed_from_event_json(
    conn,
    exchange_key: str,
    resolved: dict[str, tuple[str, dict]],
    *,
    table_ref: str,
    market_label: str,
    do_commit: bool = True,
) -> bool:
    br = exchange_key.lower().strip()
    ml = market_label.strip().lower()
    cur = conn.cursor()
    try:
        for sym, (event_ticker, ed) in resolved.items():
            if not event_ticker or not ed:
                continue
            sup = sym.upper()
            for market in ed.get("markets") or []:
                mt = market.get("ticker") or market.get("market_ticker") or ""
                if not mt:
                    continue
                strike = strike_from_kalshi_15m_rest_market(market)
                synthetic = {
                    "market_ticker": mt,
                    "yes_bid_dollars": market.get("yes_bid_dollars"),
                    "yes_ask_dollars": market.get("yes_ask_dollars"),
                    "price_dollars": market.get("last_price_dollars"),
                    "volume_fp": market.get("volume_fp"),
                    "open_interest_fp": market.get("open_interest_fp"),
                }
                row = ticker_msg_to_row_values(
                    synthetic,
                    symbol=sup,
                    event_ticker=event_ticker,
                    exchange=exchange_key,
                    market_interval=ml,
                )
                _s, _b, _et, _mt, _mv, _ts, yb, ya, nb, na, lp, vf, oif = _normalize_row_for_canonical_15m(row)
                cur.execute(
                    f"""
                    INSERT INTO {table_ref} AS ws
                    (symbol, exchange, event_ticker, market_ticker, market, strike,
                     yes_bid_dollars, yes_ask_dollars, no_bid_dollars, no_ask_dollars,
                     last_price_dollars, volume_fp, open_interest_fp, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
                    ON CONFLICT (exchange, symbol, event_ticker, market_ticker) DO UPDATE SET
                        market = EXCLUDED.market,
                        strike = COALESCE(EXCLUDED.strike, ws.strike),
                        yes_bid_dollars = COALESCE(EXCLUDED.yes_bid_dollars, ws.yes_bid_dollars),
                        yes_ask_dollars = COALESCE(EXCLUDED.yes_ask_dollars, ws.yes_ask_dollars),
                        no_bid_dollars = COALESCE(EXCLUDED.no_bid_dollars, ws.no_bid_dollars),
                        no_ask_dollars = COALESCE(EXCLUDED.no_ask_dollars, ws.no_ask_dollars),
                        last_price_dollars = COALESCE(EXCLUDED.last_price_dollars, ws.last_price_dollars),
                        volume_fp = COALESCE(EXCLUDED.volume_fp, ws.volume_fp),
                        open_interest_fp = COALESCE(EXCLUDED.open_interest_fp, ws.open_interest_fp),
                        updated_at = NOW()
                    """,
                    (sup, br, event_ticker, mt, ml, strike, yb, ya, nb, na, lp, vf, oif),
                )
        if do_commit:
            conn.commit()
        return True
    except Exception:
        logger.exception("seed_from_event_json failed")
        conn.rollback()
        return False


def _delete_all_rows(conn, table_ref: str) -> int:
    cur = conn.cursor()
    cur.execute(f"DELETE FROM {table_ref}")
    n = cur.rowcount
    conn.commit()
    return n


def _delete_rows_for_symbols(conn, table_ref: str, exchange_key: str, symbols: tuple[str, ...]) -> int:
    cur = conn.cursor()
    cur.execute(
        f"""
        DELETE FROM {table_ref}
        WHERE exchange = %s AND UPPER(TRIM(symbol::text)) = ANY(%s)
        """,
        (exchange_key.lower(), [s.upper() for s in symbols]),
    )
    n = cur.rowcount
    conn.commit()
    return n


def _verify_count(conn, table_ref: str, exchange_key: str, symbols: tuple[str, ...], expected: int) -> bool:
    if expected <= 0:
        return False
    cur = conn.cursor()
    cur.execute(
        f"""
        SELECT COUNT(*) FROM {table_ref}
        WHERE exchange = %s AND symbol = ANY(%s)
        """,
        (exchange_key, list(symbols)),
    )
    actual = cur.fetchone()[0]
    if actual != expected:
        logger.error(
            "row count mismatch: expected %s seed rows, found %s (exchange=%s)",
            expected,
            actual,
            exchange_key,
        )
        return False
    return True


# --- WS + shared state ---


def _touch_ws_transport_liveness() -> None:
    """Update ws_transport_ok_at for each in-scope symbol (RFC ping / recv / heartbeat)."""
    ex = str(_WS_TRANSPORT_CTX.get("exchange") or "kalshi").lower().strip()
    mk = str(_WS_TRANSPORT_CTX.get("market") or "15m").lower().strip()
    syms = _WS_TRANSPORT_CTX.get("symbols") or ()
    if not syms:
        return
    conn = _borrow_conn_retry("ws_transport_touch", max_wait_sec=8.0)
    if not conn:
        return
    try:
        cur = conn.cursor()
        for sym in syms:
            sym_u = str(sym).upper().strip()
            cur.execute(
                """
                INSERT INTO live_data.strike_pipeline_health
                    (exchange, market, symbol, pipeline_healthy, pipeline_health_reason,
                     pipeline_health_checked_at, pipeline_health_max_age_sec, ws_transport_ok_at, updated_at)
                VALUES (%s, %s, %s, false, 'ws_pending_strike_eval', NOW(), 900, NOW(), NOW())
                ON CONFLICT (exchange, market, symbol) DO UPDATE SET
                    ws_transport_ok_at = NOW(),
                    updated_at = NOW()
                """,
                (ex, mk, sym_u),
            )
        conn.commit()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        logger.debug("ws transport touch failed", exc_info=True)
    finally:
        _return_conn(conn)


def _upsert_ticker_row(row: tuple) -> None:
    conn = _borrow_conn_retry("ws_upsert", max_wait_sec=30.0)
    if not conn:
        return
    try:
        cur = conn.cursor()
        cur.execute(_TICKER_UPSERT_SQL_ACTIVE, _normalize_row_for_canonical_15m(row))
        conn.commit()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        logger.exception("ws ticker upsert failed")
    finally:
        _return_conn(conn)


@dataclass
class SubState:
    """Subscription list + generation bump on replace. ``rolling`` blocks WS DB writes during REST rollover."""

    _lock: threading.Lock = field(default_factory=threading.Lock)
    generation: int = 0
    ticker_meta: dict[str, tuple[str, str]] = field(default_factory=dict)
    all_tickers: list[str] = field(default_factory=list)
    _ticker_rx: dict[str, float] = field(default_factory=dict, repr=False)
    rolling: threading.Event = field(default_factory=threading.Event)

    def replace(self, meta: dict[str, tuple[str, str]], tickers: list[str]) -> None:
        with self._lock:
            self.ticker_meta = dict(meta)
            self.all_tickers = list(tickers)
            self._ticker_rx.clear()
            self.generation += 1

    def snapshot(self) -> tuple[int, dict[str, tuple[str, str]], list[str]]:
        with self._lock:
            return self.generation, dict(self.ticker_meta), list(self.all_tickers)

    def record_tick(self, market_ticker: str) -> None:
        with self._lock:
            self._ticker_rx[market_ticker] = time.monotonic()

    def all_tickers_heard(self, expected: list[str]) -> bool:
        if not expected:
            return False
        with self._lock:
            return all(mt in self._ticker_rx for mt in expected)


def _build_meta(
    symbols: tuple[str, ...],
    previous_event: dict[str, str | None],
    last_markets: dict[str, list | None],
) -> tuple[dict[str, tuple[str, str]], list[str]]:
    meta: dict[str, tuple[str, str]] = {}
    ordered: list[str] = []
    for sym in symbols:
        ev = previous_event.get(sym)
        markets = last_markets.get(sym)
        if not ev or not markets:
            continue
        for m in markets:
            mt = m.get("ticker") or m.get("market_ticker") or ""
            if not mt:
                continue
            meta[mt] = (sym.upper(), ev)
            ordered.append(mt)
    seen: set[str] = set()
    uniq: list[str] = []
    for mt in ordered:
        if mt not in seen:
            seen.add(mt)
            uniq.append(mt)
    return meta, uniq


def _sleep_until_next_quarter(skew_sec: int) -> float:
    close = next_15m_close_est()
    wake = close + timedelta(seconds=skew_sec)
    now = datetime.now(EST)
    return max(0.0, (wake - now).total_seconds())


def next_hour_close_est():
    """Next hour boundary in America/New_York (top of the upcoming hour)."""
    now = datetime.now(EST)
    return now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)


def _sleep_until_next_hour(skew_sec: int) -> float:
    wake = next_hour_close_est() + timedelta(seconds=skew_sec)
    now = datetime.now(EST)
    return max(0.0, (wake - now).total_seconds())


def _resolve_one_hourly_symbol(
    sym: str,
    *,
    max_wait_sec: float,
    sleep_sec: float,
) -> tuple[str, tuple[str | None, dict]]:
    sym_u = sym.upper()
    deadline = time.monotonic() + max_wait_sec
    while time.monotonic() < deadline:
        et, ed = get_current_event_ticker(sym_u, "hourly")
        if et and ed and (ed.get("markets") or []):
            logger.info("[%s] hourly resolved event=%s markets=%s", sym_u, et, len(ed.get("markets") or []))
            return sym_u, (et, ed)
        time.sleep(sleep_sec)
    logger.warning("[%s] hourly discovery timed out after %.0fs", sym_u, max_wait_sec)
    return sym_u, (None, {})


def _discover_hourly_all(
    symbols: tuple[str, ...],
    *,
    max_wait_sec: float,
    sleep_sec: float,
) -> dict[str, tuple[str | None, dict]]:
    resolved: dict[str, tuple[str | None, dict]] = {}
    workers = _rollover_rest_max_workers(len(symbols))
    if len(symbols) > 1 and workers > 1:
        logger.warning(
            "hourly rollover REST using %s parallel workers (set MARKET_WATCHDOG_WS_ROLLOVER_REST_WORKERS=1 to reduce bursts)",
            workers,
        )
    with ThreadPoolExecutor(max_workers=workers) as pool:
        fmap = {
            pool.submit(
                _resolve_one_hourly_symbol,
                s,
                max_wait_sec=max_wait_sec,
                sleep_sec=sleep_sec,
            ): s.upper()
            for s in symbols
        }
        for fut in as_completed(fmap):
            sym_u, pair = fut.result()
            resolved[sym_u] = pair
    return resolved


def _run_rollover(
    symbols: tuple[str, ...],
    exchange_key: str,
    sub: SubState,
    last_failed: dict,
    previous_event: dict[str, str | None],
    last_markets: dict[str, list | None],
    db_retry_sec: float,
    *,
    table_ref: str,
    market_label: str,
    delete_mode: str,
    discover_fn,
) -> bool:
    """
    REST discovery first, then wipe + seed in one DB transaction (no empty-table window).

    delete_mode: ``all`` (15m) or ``scoped`` (hourly symbols only).
    discover_fn: ``(symbols, last_failed) -> resolved dict`` for 15m, or hourly variant
    (caller wraps to match signature).
    """
    sub.rolling.set()
    try:
        # Discover before any DELETE so we never commit an empty table if discovery fails.
        resolved = discover_fn(symbols, last_failed)
        ready: dict[str, tuple[str | None, dict]] = {
            sym: pair
            for sym, pair in resolved.items()
            if pair and pair[0] and pair[1] and (pair[1].get("markets") or [])
        }
        if market_label.strip().lower() == "hourly":
            ready = _apply_hourly_atm_market_cap(ready)
        expected = _expected_row_count(ready)
        if expected <= 0:
            logger.warning(
                "rollover discovery returned zero seed rows; table not modified"
            )
            return False
        sym_set = {str(s).upper() for s in symbols}
        ready_set = set(ready.keys())
        if ready_set < sym_set:
            pending = sorted(sym_set - ready_set)
            logger.warning(
                "rollover partial: ready=%s pending=%s; not deleting or seeding (retry later)",
                ",".join(sorted(ready_set)),
                ",".join(pending),
            )
            return False

        sub.replace({}, [])

        conn = _borrow_conn_retry("rollover_atomic", db_retry_sec)
        if not conn:
            return False
        old_ac = getattr(conn, "autocommit", False)
        try:
            if old_ac:
                conn.autocommit = False
            cur = conn.cursor()
            if delete_mode == "scoped":
                cur.execute(
                    f"""
                    DELETE FROM {table_ref}
                    WHERE exchange = %s AND UPPER(TRIM(symbol::text)) = ANY(%s)
                    """,
                    (exchange_key.lower(), [str(s).upper() for s in symbols]),
                )
            else:
                cur.execute(f"DELETE FROM {table_ref}")
            cleared = cur.rowcount
            logger.info(
                "DELETE FROM %s rows=%s mode=%s (same txn as seed)",
                table_ref,
                cleared,
                delete_mode,
            )

            if not _seed_from_event_json(
                conn,
                exchange_key,
                ready,
                table_ref=table_ref,
                market_label=market_label,
                do_commit=False,
            ):
                conn.rollback()
                sub.replace({}, [])
                return False
            if not _verify_count(
                conn, table_ref, exchange_key, tuple(sorted(ready.keys())), expected
            ):
                conn.rollback()
                sub.replace({}, [])
                return False
            conn.commit()
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
            logger.exception("rollover atomic delete+seed failed")
            sub.replace({}, [])
            return False
        finally:
            if old_ac:
                try:
                    conn.autocommit = True
                except Exception:
                    pass
            _return_conn(conn)

        for sym in sorted(ready.keys()):
            et, ed = ready.get(sym, (None, {}))
            if et and ed and ed.get("markets"):
                previous_event[sym] = et
                last_markets[sym] = ed["markets"]

        meta, tickers = _build_meta(symbols, previous_event, last_markets)
        sub.replace(meta, tickers)
        ok = len(tickers) > 0
        logger.info(
            "rollover %s symbols=%s rows=%s ws_tickers=%s",
            "OK" if ok else "INCOMPLETE",
            len(symbols),
            expected,
            len(tickers),
        )
        return ok
    except Exception:
        logger.exception("rollover crashed")
        return False
    finally:
        sub.rolling.clear()


def _wait_first_tick(
    sub: SubState,
    tickers: list[str],
    max_wait_sec: float,
    *,
    hourly_relaxed: bool = False,
) -> bool:
    """After rollover subscribe, confirm WS is delivering tickers.

    15m: require at least one ticker message per subscribed market_ticker.

    Hourly (relaxed): require a fraction / minimum count — many strikes never tick unless traded.
    Set ``MARKET_WATCHDOG_WS_HOURLY_TICK_VERIFY_STRICT=1`` to require all tickers (15m-style).
    """
    if not tickers:
        return False
    n = len(tickers)
    strict_hourly = hourly_relaxed and os.getenv(
        "MARKET_WATCHDOG_WS_HOURLY_TICK_VERIFY_STRICT", ""
    ).strip().lower() in ("1", "true", "yes")
    if hourly_relaxed and not strict_hourly:
        frac = float(os.getenv("MARKET_WATCHDOG_WS_HOURLY_TICK_VERIFY_FRAC", str(DEFAULT_HOURLY_TICK_VERIFY_FRAC)))
        min_abs = int(os.getenv("MARKET_WATCHDOG_WS_HOURLY_TICK_VERIFY_MIN", str(DEFAULT_HOURLY_TICK_VERIFY_MIN)))
        frac = max(0.01, min(1.0, frac))
        min_abs = max(1, min_abs)
        need = min(n, max(min_abs, int(n * frac)))
    else:
        need = n

    deadline = time.monotonic() + max_wait_sec
    while time.monotonic() < deadline:
        with sub._lock:
            heard = sum(1 for mt in tickers if mt in sub._ticker_rx)
        if heard >= need:
            if need < n:
                logger.info(
                    "ws hourly tick verify ok heard=%s/%s need=%s (relaxed; %s unique tickers)",
                    heard,
                    n,
                    need,
                    n,
                )
            else:
                logger.info("ws first tick on all %s market_tickers", n)
            return True
        time.sleep(0.35)
    with sub._lock:
        have = set(sub._ticker_rx)
    missing = [mt for mt in tickers if mt not in have]
    logger.error(
        "ws verify timeout need=%s heard=%s silent=%s sample=%s",
        need,
        n - len(missing),
        len(missing),
        missing[:25],
    )
    return False


def _main_loop(
    symbols: tuple[str, ...],
    exchange_key: str,
    sub: SubState,
    stop: threading.Event,
    *,
    quarter_skew_sec: int,
    db_retry_sec: float,
    ws_verify_sec: float,
    cycle_retry_sec: float,
) -> None:
    prev_ev: dict[str, str | None] = {s: None for s in symbols}
    last_m: dict[str, list | None] = {s: None for s in symbols}
    last_failed: dict = {}
    last_hb = time.time()

    while not stop.is_set():
        # Capture the upcoming ET quarter **before** rollover work: if discovery + first WS tick
        # straddles that instant (common after MASTER_RESTART near :00/:15/:30/:45), the seeded
        # event can lag Kalshi until the *following* quarter unless we roll again immediately.
        quarter_close_target = next_15m_close_est()
        ok = _run_rollover(
            symbols,
            exchange_key,
            sub,
            last_failed,
            prev_ev,
            last_m,
            db_retry_sec,
            table_ref=WS_TABLE,
            market_label="15m",
            delete_mode="all",
            discover_fn=lambda sy, lf: _discover_all(
                sy,
                lf,
                max_wait_sec=DEFAULT_DISCOVERY_MAX_WAIT_SEC,
                sleep_sec=DEFAULT_DISCOVERY_SLEEP_SEC,
            ),
        )
        _, _, tickers_now = sub.snapshot()

        if ok:
            if not _wait_first_tick(sub, tickers_now, ws_verify_sec):
                ok = False
            elif datetime.now(EST) >= quarter_close_target:
                logger.info(
                    "crossed ET quarter-hour during first-tick wait (>= %s); re-running rollover",
                    quarter_close_target.strftime("%H:%M:%S"),
                )
                ok = _run_rollover(
                    symbols,
                    exchange_key,
                    sub,
                    last_failed,
                    prev_ev,
                    last_m,
                    db_retry_sec,
                    table_ref=WS_TABLE,
                    market_label="15m",
                    delete_mode="all",
                    discover_fn=lambda sy, lf: _discover_all(
                        sy,
                        lf,
                        max_wait_sec=DEFAULT_DISCOVERY_MAX_WAIT_SEC,
                        sleep_sec=DEFAULT_DISCOVERY_SLEEP_SEC,
                    ),
                )
                if ok:
                    _, _, tickers_now = sub.snapshot()
                    if not _wait_first_tick(sub, tickers_now, ws_verify_sec):
                        ok = False

        if time.time() - last_hb >= HEARTBEAT_INTERVAL_SEC:
            logger.info(
                "heartbeat ok=%s tickers=%s symbols=%s",
                ok,
                len(tickers_now),
                sum(1 for s in symbols if prev_ev.get(s)),
            )
            last_hb = time.time()

        if not ok:
            logger.warning("rollover incomplete; retry in %ss", cycle_retry_sec)
            if stop.wait(cycle_retry_sec):
                break
            continue

        wait = _sleep_until_next_quarter(quarter_skew_sec)
        nxt = next_15m_close_est() + timedelta(seconds=quarter_skew_sec)
        logger.info("ws-only until next rollover ~%s ET (%.0fs)", nxt.strftime("%H:%M:%S"), wait)
        if stop.wait(wait):
            break


def _main_loop_hourly(
    symbols: tuple[str, ...],
    exchange_key: str,
    sub: SubState,
    stop: threading.Event,
    *,
    hour_skew_sec: int,
    db_retry_sec: float,
    ws_verify_sec: float,
    cycle_retry_sec: float,
) -> None:
    prev_ev: dict[str, str | None] = {s: None for s in symbols}
    last_m: dict[str, list | None] = {s: None for s in symbols}
    last_failed: dict = {}
    last_hb = time.time()

    while not stop.is_set():
        hour_close_target = next_hour_close_est()
        ok = _run_rollover(
            symbols,
            exchange_key,
            sub,
            last_failed,
            prev_ev,
            last_m,
            db_retry_sec,
            table_ref=WS_TABLE_HOURLY,
            market_label="hourly",
            delete_mode="scoped",
            discover_fn=lambda sy, lf: _discover_hourly_all(
                sy,
                max_wait_sec=DEFAULT_DISCOVERY_MAX_WAIT_SEC,
                sleep_sec=DEFAULT_DISCOVERY_SLEEP_SEC,
            ),
        )
        _, _, tickers_now = sub.snapshot()

        if ok:
            if not _wait_first_tick(sub, tickers_now, ws_verify_sec, hourly_relaxed=True):
                ok = False
            elif datetime.now(EST) >= hour_close_target:
                logger.info(
                    "crossed ET hour boundary during first-tick wait (>= %s); re-running rollover",
                    hour_close_target.strftime("%H:%M:%S"),
                )
                ok = _run_rollover(
                    symbols,
                    exchange_key,
                    sub,
                    last_failed,
                    prev_ev,
                    last_m,
                    db_retry_sec,
                    table_ref=WS_TABLE_HOURLY,
                    market_label="hourly",
                    delete_mode="scoped",
                    discover_fn=lambda sy, lf: _discover_hourly_all(
                        sy,
                        max_wait_sec=DEFAULT_DISCOVERY_MAX_WAIT_SEC,
                        sleep_sec=DEFAULT_DISCOVERY_SLEEP_SEC,
                    ),
                )
                if ok:
                    _, _, tickers_now = sub.snapshot()
                    if not _wait_first_tick(sub, tickers_now, ws_verify_sec, hourly_relaxed=True):
                        ok = False

        if time.time() - last_hb >= HEARTBEAT_INTERVAL_SEC:
            logger.info(
                "hourly heartbeat ok=%s tickers=%s symbols=%s",
                ok,
                len(tickers_now),
                sum(1 for s in symbols if prev_ev.get(s)),
            )
            last_hb = time.time()

        if not ok:
            logger.warning("hourly rollover incomplete; retry in %ss", cycle_retry_sec)
            if stop.wait(cycle_retry_sec):
                break
            continue

        wait = _sleep_until_next_hour(hour_skew_sec)
        nxt = next_hour_close_est() + timedelta(seconds=hour_skew_sec)
        logger.info("hourly ws-only until next rollover ~%s ET (%.0fs)", nxt.strftime("%H:%M:%S"), wait)
        if stop.wait(wait):
            break


async def _ws_loop(exchange_key: str, sub: SubState, stop: threading.Event) -> None:
    ping_iv = max(10, int(os.getenv("KALSHI_WS_PING_INTERVAL_SEC", str(DEFAULT_WS_PING_INTERVAL_SEC))))
    beat_sec = max(5, int(os.getenv("KALSHI_WS_TRANSPORT_BEAT_SEC", str(DEFAULT_WS_TRANSPORT_BEAT_SEC))))
    market_iv = str(_WS_TRANSPORT_CTX.get("market") or "15m").strip().lower()

    while not stop.is_set():
        gen, meta, tickers = sub.snapshot()
        if not tickers:
            await asyncio.sleep(0.25)
            continue

        headers = await asyncio.to_thread(kalshi_ws_connect_headers)
        cmd_id = 1
        try:
            async with websockets.connect(
                WS_URL,
                additional_headers=headers,
                ping_interval=float(ping_iv),
                ping_timeout=70,
                close_timeout=10,
                max_size=2**22,
            ) as ws:
                cmd_id += 1
                logger.info(
                    "ws subscribe gen=%s exchange=%s n_tickers=%s sample_start=%s sample_end=%s ping_iv=%ss",
                    gen,
                    exchange_key,
                    len(tickers),
                    ",".join(tickers[:3]),
                    ",".join(tickers[-3:]),
                    ping_iv,
                )
                await ws.send(
                    json.dumps(
                        {
                            "id": cmd_id,
                            "cmd": "subscribe",
                            "params": {"channels": ["ticker"], "market_tickers": tickers},
                        }
                    )
                )
                raw = await asyncio.wait_for(ws.recv(), timeout=20.0)
                ack = json.loads(raw)
                if ack.get("type") != "subscribed":
                    logger.warning("subscribe ack unexpected: %s", ack)
                    await asyncio.sleep(2.0)
                    continue
                logger.info("ws subscribed sid=%s n=%s", ack.get("sid"), len(tickers))
                my_gen, _, _ = sub.snapshot()
                await asyncio.to_thread(_touch_ws_transport_liveness)

                async def _transport_beat_loop() -> None:
                    while not stop.is_set():
                        await asyncio.sleep(float(beat_sec))
                        if sub.snapshot()[0] != my_gen:
                            return
                        await asyncio.to_thread(_touch_ws_transport_liveness)

                beat_task = asyncio.create_task(_transport_beat_loop())
                try:
                    while not stop.is_set():
                        try:
                            raw = await asyncio.wait_for(ws.recv(), timeout=75.0)
                        except asyncio.TimeoutError:
                            if sub.snapshot()[0] != my_gen:
                                break
                            await asyncio.to_thread(_touch_ws_transport_liveness)
                            continue

                        gen2, meta2, _ = sub.snapshot()
                        if gen2 != my_gen:
                            logger.info("ws gen %s -> %s reconnect", my_gen, gen2)
                            break

                        try:
                            data = json.loads(raw)
                        except json.JSONDecodeError:
                            continue
                        if data.get("type") not in ("ticker", "ticker_v2"):
                            continue
                        msg = data.get("msg") or {}
                        mt = msg.get("market_ticker")
                        if not mt:
                            continue
                        pair = meta2.get(mt)
                        if not pair:
                            continue
                        sub.record_tick(mt)
                        sym_u, ev = pair
                        try:
                            row = ticker_msg_to_row_values(
                                msg,
                                symbol=sym_u,
                                event_ticker=ev,
                                exchange=exchange_key,
                                market_interval=market_iv,
                            )
                        except ValueError:
                            continue
                        if sub.rolling.is_set():
                            continue
                        await asyncio.to_thread(_upsert_ticker_row, row)
                        await asyncio.to_thread(_touch_ws_transport_liveness)
                finally:
                    beat_task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await beat_task

        except (ConnectionClosed, WebSocketException, OSError) as e:
            logger.warning("ws session ended: %s", e)
        except Exception:
            logger.exception("ws error")
        await asyncio.sleep(1.0)


def _ws_thread_main(exchange_key: str, sub: SubState, stop: threading.Event) -> None:
    asyncio.run(_ws_loop(exchange_key, sub, stop))


def run(
    exchange_key: str,
    symbols: tuple[str, ...],
    *,
    market_kind: str = "15m",
    quarter_rollover_skew_sec: int = DEFAULT_QUARTER_ROLLOVER_SKEW_SEC,
    hour_rollover_skew_sec: int = DEFAULT_HOUR_ROLLOVER_SKEW_SEC,
    db_connect_retry_sec: float = DEFAULT_DB_CONNECT_RETRY_SEC,
    ws_flow_verify_sec: float = DEFAULT_WS_FLOW_VERIFY_SEC,
    cycle_retry_sec: float = DEFAULT_CYCLE_RETRY_SEC,
    db_pool_max_conn: int = DEFAULT_DB_POOL_MAX_CONN,
) -> None:
    global _TICKER_UPSERT_SQL_ACTIVE, _WS_TRANSPORT_CTX

    normalized = tuple(s.upper() for s in symbols)
    mk = market_kind.strip().lower()
    if mk == "hourly":
        _TICKER_UPSERT_SQL_ACTIVE = _ticker_upsert_sql(WS_TABLE_HOURLY)
    else:
        _TICKER_UPSERT_SQL_ACTIVE = _ticker_upsert_sql(WS_TABLE)
    _WS_TRANSPORT_CTX = {"exchange": exchange_key, "market": mk, "symbols": normalized}

    _init_db_pool(db_pool_max_conn)
    logger.info(
        "market_watchdog_ws exchange=%s market=%s symbols=%s q_skew=%ss h_skew=%ss db_retry=%.0fs verify=%.0fs retry=%.0fs pool=%s",
        exchange_key,
        mk,
        ",".join(normalized),
        quarter_rollover_skew_sec,
        hour_rollover_skew_sec,
        db_connect_retry_sec,
        ws_flow_verify_sec,
        cycle_retry_sec,
        db_pool_max_conn,
    )
    conn = _borrow_conn_retry("ensure_table", min(30.0, db_connect_retry_sec))
    if conn:
        try:
            if mk == "hourly":
                ensure_ws_hourly_table(conn)
            else:
                ensure_ws_15m_table(conn)
        finally:
            _return_conn(conn)
    else:
        logger.warning("could not ensure WS table")

    stop = threading.Event()
    sub = SubState()
    ws_thread = threading.Thread(target=_ws_thread_main, args=(exchange_key, sub, stop), daemon=True)
    ws_thread.start()
    try:
        if mk == "hourly":
            hourly_verify_sec = max(
                float(ws_flow_verify_sec),
                float(os.getenv("MARKET_WATCHDOG_WS_HOURLY_VERIFY_SEC", str(DEFAULT_HOURLY_WS_VERIFY_SEC))),
            )
            _main_loop_hourly(
                normalized,
                exchange_key,
                sub,
                stop,
                hour_skew_sec=max(0, min(3600, int(hour_rollover_skew_sec))),
                db_retry_sec=db_connect_retry_sec,
                ws_verify_sec=hourly_verify_sec,
                cycle_retry_sec=cycle_retry_sec,
            )
        else:
            _main_loop(
                normalized,
                exchange_key,
                sub,
                stop,
                quarter_skew_sec=quarter_rollover_skew_sec,
                db_retry_sec=db_connect_retry_sec,
                ws_verify_sec=ws_flow_verify_sec,
                cycle_retry_sec=cycle_retry_sec,
            )
    except KeyboardInterrupt:
        logger.info("stopped")
    finally:
        stop.set()
        ws_thread.join(timeout=8.0)
        _close_db_pool()


def main() -> None:
    parser = argparse.ArgumentParser(description="Kalshi 15m WebSocket market watchdog.")
    parser.add_argument("--exchange", default=None)
    parser.add_argument("--broker", default=None, dest="legacy_broker")
    parser.add_argument("--market", required=True, choices=("15m", "hourly"))
    parser.add_argument("--symbols", nargs="*", default=None, metavar="SYM")
    parser.add_argument(
        "--skip-symbols",
        nargs="*",
        default=None,
        metavar="SYM",
        help="Optional symbols to exclude from WS subscriptions (simulation/testing).",
    )
    parser.add_argument(
        "--quarter-rollover-skew-sec",
        type=int,
        default=DEFAULT_QUARTER_ROLLOVER_SKEW_SEC,
        metavar="N",
        help=f"Seconds after ET quarter-hour to start rollover (default {DEFAULT_QUARTER_ROLLOVER_SKEW_SEC}).",
    )
    parser.add_argument(
        "--hour-rollover-skew-sec",
        type=int,
        default=DEFAULT_HOUR_ROLLOVER_SKEW_SEC,
        metavar="N",
        help=f"Seconds after ET hour boundary for hourly rollover (default {DEFAULT_HOUR_ROLLOVER_SKEW_SEC}).",
    )
    parser.add_argument("--db-connect-retry-sec", type=float, default=DEFAULT_DB_CONNECT_RETRY_SEC)
    parser.add_argument("--ws-flow-verify-sec", type=float, default=DEFAULT_WS_FLOW_VERIFY_SEC)
    parser.add_argument("--cycle-retry-sec", type=float, default=DEFAULT_CYCLE_RETRY_SEC)
    parser.add_argument("--db-pool-max", type=int, default=DEFAULT_DB_POOL_MAX_CONN, metavar="N")
    args = parser.parse_args()
    venue = (args.exchange or args.legacy_broker or "kalshi").lower().strip()
    if venue != EXCHANGE_KALSHI:
        logger.error("Only kalshi; got %s", venue)
        sys.exit(1)
    skip_from_env = tuple(
        s.strip().upper() for s in str(os.getenv("WS_SKIP_SYMBOLS", "")).split(",") if s.strip()
    )
    skip_from_args = tuple(s.strip().upper() for s in (args.skip_symbols or []) if s.strip())
    skip = tuple(sorted(set(skip_from_env + skip_from_args)))

    if args.market == "hourly":
        if args.symbols:
            sym = tuple(s.strip().upper() for s in args.symbols if s.strip())
        else:
            raw = str(os.getenv("WS_HOURLY_SYMBOLS", "BTC,ETH")).upper()
            sym = tuple(s.strip() for s in raw.split(",") if s.strip())
        if skip:
            logger.warning("WS subscription skip symbols active: %s", ",".join(skip))
            sym = tuple(s for s in sym if s not in skip)
        for s in sym:
            if s not in KALSHI_HOURLY_SYMBOLS:
                logger.error("unsupported hourly symbol %s (allowed %s)", s, ",".join(KALSHI_HOURLY_SYMBOLS))
                sys.exit(1)
        if not sym:
            logger.error("no hourly symbols to subscribe")
            sys.exit(1)
        hskew = max(0, min(3600, int(args.hour_rollover_skew_sec)))
        pool_max = max(2, min(64, int(args.db_pool_max)))
        run(
            venue,
            sym,
            market_kind="hourly",
            hour_rollover_skew_sec=hskew,
            db_connect_retry_sec=max(15.0, float(args.db_connect_retry_sec)),
            ws_flow_verify_sec=max(15.0, float(args.ws_flow_verify_sec)),
            cycle_retry_sec=max(3.0, float(args.cycle_retry_sec)),
            db_pool_max_conn=pool_max,
        )
        return

    if args.symbols:
        sym = tuple(s.strip().upper() for s in args.symbols if s.strip())
        if not sym:
            sym = fetch_kalshi_15m_symbols_ordered_from_db()
    else:
        sym = fetch_kalshi_15m_symbols_ordered_from_db()

    if skip:
        logger.warning("WS subscription skip symbols active: %s", ",".join(skip))
        sym = tuple(s for s in sym if s not in skip)
        if not sym:
            logger.error("all symbols skipped; nothing to subscribe")
            sys.exit(1)

    for s in sym:
        if s not in KALSHI_15M_SYMBOLS:
            logger.error("unsupported symbol %s", s)
            sys.exit(1)

    skew = max(0, min(120, int(args.quarter_rollover_skew_sec)))
    pool_max = max(2, min(64, int(args.db_pool_max)))

    run(
        venue,
        sym,
        market_kind="15m",
        quarter_rollover_skew_sec=skew,
        db_connect_retry_sec=max(15.0, float(args.db_connect_retry_sec)),
        ws_flow_verify_sec=max(15.0, float(args.ws_flow_verify_sec)),
        cycle_retry_sec=max(3.0, float(args.cycle_retry_sec)),
        db_pool_max_conn=pool_max,
    )


if __name__ == "__main__":
    main()
