#!/usr/bin/env python3
"""
Kalshi 15m: REST only at each quarter-hour rollover (wipe → event JSON → seed DB).
All other time: WebSocket ``ticker`` updates only (same table columns as REST snapshot on seed).

Rollover sets ``rolling`` so the WS thread skips DB writes until seed + new subscribe are done.
"""

from __future__ import annotations

import argparse
import asyncio
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
from backend.market_watchdog import (
    DB_CONFIG,
    EST,
    EXCHANGE_KALSHI,
    KALSHI_15M_SYMBOLS,
    HEARTBEAT_INTERVAL_SEC,
    connect_database,
    fetch_event_json,
    fetch_kalshi_15m_symbols_ordered_from_db,
    get_current_event_ticker_15m,
    next_15m_close_est,
)

WS_URL = "wss://api.elections.kalshi.com/trade-api/ws/v2"
WS_TABLE = "live_data.market_kalshi_15m"

DEFAULT_QUARTER_ROLLOVER_SKEW_SEC = 0
DEFAULT_DB_CONNECT_RETRY_SEC = 90.0
DEFAULT_WS_FLOW_VERIFY_SEC = 120.0
DEFAULT_CYCLE_RETRY_SEC = 10.0
DEFAULT_DB_POOL_MAX_CONN = 16

_POOL_LOCK = threading.Lock()
_DB_POOL: psycopg2.pool.ThreadedConnectionPool | None = None

TICKER_UPSERT_SQL = f"""
INSERT INTO {WS_TABLE} AS ws
    (symbol, exchange, event_ticker, market_ticker, market, strike,
     yes_bid_dollars, yes_ask_dollars, no_bid_dollars, no_ask_dollars, last_price_dollars,
     volume_fp, open_interest, updated_at)
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
    open_interest = EXCLUDED.open_interest,
    updated_at = NOW()
"""


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


def _fixed_point_text_to_int(v):
    if v is None:
        return None
    s = str(v).strip()
    if not s:
        return None
    try:
        return int(float(s))
    except Exception:
        return None


def _normalize_row_for_canonical_15m(row: tuple) -> tuple:
    sym, br, ev, mt, mv, strike, yb, ya, nb, na, lp, vf, oif = row
    return (sym, br, ev, mt, mv, strike, yb, ya, nb, na, lp, _fixed_point_text_to_int(vf), _fixed_point_text_to_int(oif))


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
            yes_bid INTEGER,
            yes_ask INTEGER,
            no_bid INTEGER,
            no_ask INTEGER,
            last_price INTEGER,
            yes_bid_dollars TEXT,
            yes_ask_dollars TEXT,
            no_bid_dollars TEXT,
            no_ask_dollars TEXT,
            last_price_dollars TEXT,
            volume_fp INTEGER,
            volume_24h_fp INTEGER,
            open_interest INTEGER,
            liquidity INTEGER,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
            updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
            CONSTRAINT market_kalshi_15m_exchange_symbol_event_market_unique
                UNIQUE (exchange, symbol, event_ticker, market_ticker)
        );
        """
    )
    conn.commit()


# --- REST (rollover only) ---


def _floor_strike_raw(market: dict):
    fs = market.get("floor_strike")
    if fs is None:
        fs = market.get("floorStrike")
    return fs


def _markets_all_have_valid_floor_strike(event_data: dict) -> bool:
    markets = event_data.get("markets") or []
    if not markets:
        return False
    for m in markets:
        if not isinstance(m, dict):
            return False
        fs = _floor_strike_raw(m)
        if fs is None:
            return False
        if isinstance(fs, str) and not str(fs).strip():
            return False
    return True


def _refetch_event_until_floor_strikes(event_ticker: str) -> dict:
    attempt = 0
    last_log = 0.0
    while True:
        ed = fetch_event_json(event_ticker)
        if ed and ed.get("markets") and len(ed["markets"]) > 0 and _markets_all_have_valid_floor_strike(
            ed
        ):
            return ed
        attempt += 1
        now = time.monotonic()
        if now - last_log >= 30.0:
            logger.info(
                "waiting for floor_strike on all markets event=%s REST attempts=%s",
                event_ticker,
                attempt,
            )
            last_log = now
        time.sleep(2.0)


def _resolve_one_symbol_until_ready(sym: str, last_failed: dict) -> tuple[str, tuple[str, dict]]:
    sym_u = sym.upper()
    pause = 2.0
    while True:
        et, ed = get_current_event_ticker_15m(sym_u, last_failed)
        if et and ed and ed.get("markets") and len(ed["markets"]) > 0:
            if not _markets_all_have_valid_floor_strike(ed):
                ed = _refetch_event_until_floor_strikes(et)
            logger.info(
                "[%s] resolved event=%s markets=%s (floor_strike complete)",
                sym_u,
                et,
                len(ed["markets"]),
            )
            return sym_u, (et, ed)
        time.sleep(pause)


def _discover_all(symbols: tuple[str, ...], last_failed: dict) -> dict[str, tuple[str, dict]]:
    resolved: dict[str, tuple[str, dict]] = {}
    workers = max(1, min(len(symbols), 8))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        fmap = {
            pool.submit(_resolve_one_symbol_until_ready, s, last_failed): s.upper() for s in symbols
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


def _seed_from_event_json(conn, exchange_key: str, resolved: dict[str, tuple[str, dict]]) -> bool:
    br = exchange_key.lower().strip()
    cur = conn.cursor()
    try:
        for sym, (event_ticker, ed) in resolved.items():
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
                )
                _s, _b, _et, _mt, _mv, _ts, yb, ya, nb, na, lp, vf, oif = _normalize_row_for_canonical_15m(row)
                cur.execute(
                    f"""
                    INSERT INTO {WS_TABLE} AS ws
                    (symbol, exchange, event_ticker, market_ticker, market, strike,
                     yes_bid_dollars, yes_ask_dollars, no_bid_dollars, no_ask_dollars,
                     last_price_dollars, volume_fp, open_interest, updated_at)
                    VALUES (%s, %s, %s, %s, '15m', %s, %s, %s, %s, %s, %s, %s, %s, NOW())
                    ON CONFLICT (exchange, symbol, event_ticker, market_ticker) DO UPDATE SET
                        market = EXCLUDED.market,
                        strike = COALESCE(EXCLUDED.strike, ws.strike),
                        yes_bid_dollars = COALESCE(EXCLUDED.yes_bid_dollars, ws.yes_bid_dollars),
                        yes_ask_dollars = COALESCE(EXCLUDED.yes_ask_dollars, ws.yes_ask_dollars),
                        no_bid_dollars = COALESCE(EXCLUDED.no_bid_dollars, ws.no_bid_dollars),
                        no_ask_dollars = COALESCE(EXCLUDED.no_ask_dollars, ws.no_ask_dollars),
                        last_price_dollars = COALESCE(EXCLUDED.last_price_dollars, ws.last_price_dollars),
                        volume_fp = COALESCE(EXCLUDED.volume_fp, ws.volume_fp),
                        open_interest = COALESCE(EXCLUDED.open_interest, ws.open_interest),
                        updated_at = NOW()
                    """,
                    (sup, br, event_ticker, mt, strike, yb, ya, nb, na, lp, vf, oif),
                )
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


def _upsert_ticker_row(row: tuple) -> None:
    conn = _borrow_conn_retry("ws_upsert", max_wait_sec=30.0)
    if not conn:
        return
    try:
        cur = conn.cursor()
        cur.execute(TICKER_UPSERT_SQL, _normalize_row_for_canonical_15m(row))
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


def _run_rollover(
    symbols: tuple[str, ...],
    exchange_key: str,
    sub: SubState,
    last_failed: dict,
    previous_event: dict[str, str | None],
    last_markets: dict[str, list | None],
    db_retry_sec: float,
) -> bool:
    """
    Wipe DB → parallel REST until floor_strike complete → seed from event JSON → subscribe WS.
    """
    table_ref = WS_TABLE
    sub.rolling.set()
    wiped = False
    try:
        conn = _borrow_conn_retry("rollover_delete", db_retry_sec)
        if not conn:
            return False
        try:
            cleared = _delete_all_rows(conn, table_ref)
            wiped = True
            logger.info("DELETE FROM %s rows=%s", table_ref, cleared)
        finally:
            _return_conn(conn)

        sub.replace({}, [])

        resolved = _discover_all(symbols, last_failed)
        expected = _expected_row_count(resolved)

        conn2 = _borrow_conn_retry("rollover_seed", db_retry_sec)
        if not conn2:
            sub.replace({}, [])
            return False
        try:
            if not _seed_from_event_json(conn2, exchange_key, resolved):
                sub.replace({}, [])
                return False
            if not _verify_count(conn2, table_ref, exchange_key, symbols, expected):
                sub.replace({}, [])
                return False
        finally:
            _return_conn(conn2)

        for sym in symbols:
            et, ed = resolved[sym]
            previous_event[sym] = et
            last_markets[sym] = ed["markets"]

        meta, tickers = _build_meta(symbols, previous_event, last_markets)
        sub.replace(meta, tickers)
        logger.info("rollover OK symbols=%s rows=%s ws_tickers=%s", len(symbols), expected, len(tickers))
        return True
    except Exception:
        logger.exception("rollover crashed")
        if wiped:
            try:
                sub.replace({}, [])
            except Exception:
                pass
        return False
    finally:
        sub.rolling.clear()


def _wait_first_tick(sub: SubState, tickers: list[str], max_wait_sec: float) -> bool:
    if not tickers:
        return False
    deadline = time.monotonic() + max_wait_sec
    while time.monotonic() < deadline:
        if sub.all_tickers_heard(tickers):
            logger.info("ws first tick on all %s market_tickers", len(tickers))
            return True
        time.sleep(0.35)
    with sub._lock:
        have = set(sub._ticker_rx)
    missing = [mt for mt in tickers if mt not in have]
    logger.error("ws verify timeout silent=%s sample=%s", len(missing), missing[:25])
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
        ok = _run_rollover(
            symbols, exchange_key, sub, last_failed, prev_ev, last_m, db_retry_sec
        )
        _, _, tickers_now = sub.snapshot()

        if ok:
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


async def _ws_loop(exchange_key: str, sub: SubState, stop: threading.Event) -> None:
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
                ping_interval=None,
                ping_timeout=60,
                close_timeout=10,
                max_size=2**22,
            ) as ws:
                cmd_id += 1
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

                while not stop.is_set():
                    try:
                        raw = await asyncio.wait_for(ws.recv(), timeout=75.0)
                    except asyncio.TimeoutError:
                        if sub.snapshot()[0] != my_gen:
                            break
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
                            msg, symbol=sym_u, event_ticker=ev, exchange=exchange_key
                        )
                    except ValueError:
                        continue
                    if sub.rolling.is_set():
                        continue
                    await asyncio.to_thread(_upsert_ticker_row, row)

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
    quarter_rollover_skew_sec: int = DEFAULT_QUARTER_ROLLOVER_SKEW_SEC,
    db_connect_retry_sec: float = DEFAULT_DB_CONNECT_RETRY_SEC,
    ws_flow_verify_sec: float = DEFAULT_WS_FLOW_VERIFY_SEC,
    cycle_retry_sec: float = DEFAULT_CYCLE_RETRY_SEC,
    db_pool_max_conn: int = DEFAULT_DB_POOL_MAX_CONN,
) -> None:
    normalized = tuple(s.upper() for s in symbols)
    _init_db_pool(db_pool_max_conn)
    logger.info(
        "market_watchdog_ws exchange=%s symbols=%s skew=%ss db_retry=%.0fs verify=%.0fs retry=%.0fs pool=%s",
        exchange_key,
        ",".join(normalized),
        quarter_rollover_skew_sec,
        db_connect_retry_sec,
        ws_flow_verify_sec,
        cycle_retry_sec,
        db_pool_max_conn,
    )
    conn = _borrow_conn_retry("ensure_table", min(30.0, db_connect_retry_sec))
    if conn:
        try:
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
    parser.add_argument("--db-connect-retry-sec", type=float, default=DEFAULT_DB_CONNECT_RETRY_SEC)
    parser.add_argument("--ws-flow-verify-sec", type=float, default=DEFAULT_WS_FLOW_VERIFY_SEC)
    parser.add_argument("--cycle-retry-sec", type=float, default=DEFAULT_CYCLE_RETRY_SEC)
    parser.add_argument("--db-pool-max", type=int, default=DEFAULT_DB_POOL_MAX_CONN, metavar="N")
    args = parser.parse_args()
    venue = (args.exchange or args.legacy_broker or "kalshi").lower().strip()
    if venue != EXCHANGE_KALSHI:
        logger.error("Only kalshi; got %s", venue)
        sys.exit(1)
    if args.market != "15m":
        logger.error("Only 15m")
        sys.exit(1)

    if args.symbols:
        sym = tuple(s.strip().upper() for s in args.symbols if s.strip())
        if not sym:
            sym = fetch_kalshi_15m_symbols_ordered_from_db()
    else:
        sym = fetch_kalshi_15m_symbols_ordered_from_db()

    skip_from_env = tuple(
        s.strip().upper() for s in str(os.getenv("WS_SKIP_SYMBOLS", "")).split(",") if s.strip()
    )
    skip_from_args = tuple(s.strip().upper() for s in (args.skip_symbols or []) if s.strip())
    skip = tuple(sorted(set(skip_from_env + skip_from_args)))
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
        quarter_rollover_skew_sec=skew,
        db_connect_retry_sec=max(15.0, float(args.db_connect_retry_sec)),
        ws_flow_verify_sec=max(15.0, float(args.ws_flow_verify_sec)),
        cycle_retry_sec=max(3.0, float(args.cycle_retry_sec)),
        db_pool_max_conn=pool_max,
    )


if __name__ == "__main__":
    main()
