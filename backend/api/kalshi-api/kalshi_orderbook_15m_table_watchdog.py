#!/usr/bin/env python3
"""
BTC 15m orderbook table watchdog (testing schema).

Purpose:
- Subscribe to Kalshi ``orderbook_delta`` for the current BTC 15m market.
- On the same WebSocket, subscribe to Kalshi ``ticker`` (market ticker) for last price and best quotes
  (see https://docs.kalshi.com/websockets/market-ticker).
- Create one testing table per market ticker.
- Build baseline from ``orderbook_snapshot``; apply ``orderbook_delta`` updates in real time.
- Roll to the next BTC 15m market automatically and continue in a new table.

Note: The ticker WebSocket message does not include ``floor_strike`` or the long market title. For the
UI header line, ``market_title`` is read from ``live_data.strike_table_15m`` (symbol prefix stripped).
One public REST GET ``/markets/{ticker}`` per rollover still supplies ``floor_strike`` for strike display
elsewhere in the UI.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import sys
import time
from decimal import Decimal, InvalidOperation
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from pathlib import Path
from typing import Any, Optional

import psycopg2
import requests
import websockets

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.core.kalshi_ws_auth import kalshi_ws_connect_headers
from backend.core.kalshi_market_normalize import format_floor_strike_usd_comma_cents
from backend.core.time_eastern import merge_psycopg2_connect_kwargs
from backend.core.trading_redis_comms import redis_client_optional

WS_URL = "wss://api.elections.kalshi.com/trade-api/ws/v2"
KALSHI_REST_BASE = "https://api.elections.kalshi.com/trade-api/v2"
KALSHI_REST_HEADERS = {"Accept": "application/json", "User-Agent": "rec-io-orderbook-ui/1.0"}
ROLL_CHECK_SEC = 5.0
REDIS_ORDERBOOK_KEY = "testing:orderbook_ui:current"
REDIS_ORDERBOOK_CHANNEL = "testing:orderbook_ui:updates"
EST = ZoneInfo("America/New_York")


def _open_local_db():
    return psycopg2.connect(
        **merge_psycopg2_connect_kwargs(
            {
                "host": os.getenv("DB_HOST", "localhost"),
                "port": int(os.getenv("DB_PORT", "5432")),
                "dbname": os.getenv("DB_NAME", "rec_io_db"),
                "user": os.getenv("DB_USER", "rec_io_user"),
                "password": os.getenv("DB_PASSWORD", "rec_io_password"),
            }
        )
    )


def _sanitize_ticker_for_table(market_ticker: str) -> str:
    t = re.sub(r"[^A-Za-z0-9_]+", "_", str(market_ticker).strip())
    t = re.sub(r"_+", "_", t).strip("_").lower()
    return t or "unknown"


def _table_name_for_ticker(market_ticker: str) -> str:
    return f"orderbook_live_{_sanitize_ticker_for_table(market_ticker)}"


def _quoted_testing_table(table_name: str) -> str:
    return f'testing."{table_name}"'


def _to_15m_est_boundary(ts_est: datetime) -> datetime:
    base = ts_est.replace(second=0, microsecond=0)
    next_minute = ((base.minute // 15) + 1) * 15
    if next_minute >= 60:
        base = (base + timedelta(hours=1)).replace(minute=0)
    else:
        base = base.replace(minute=next_minute)
    return base


def _ticker_for_boundary_est(boundary_est: datetime) -> str:
    # KXBTC15M-26APR271300-00
    token = boundary_est.strftime("%y%b%d%H%M").upper()
    minute = boundary_est.strftime("%M")
    return f"KXBTC15M-{token}-{minute}"


def bootstrap_ticker_candidates() -> list[str]:
    now_est = datetime.now(EST)
    b = _to_15m_est_boundary(now_est)
    # Try a narrow window around "current" contract to tolerate brief clock/venue skew.
    return [
        _ticker_for_boundary_est(b - timedelta(minutes=15)),
        _ticker_for_boundary_est(b),
        _ticker_for_boundary_est(b + timedelta(minutes=15)),
    ]


def parse_15m_ticker_end_est(market_ticker: str) -> Optional[datetime]:
    m = re.match(r"^KXBTC15M-(\d{2}[A-Z]{3}\d{2}\d{4})-(\d{2})$", str(market_ticker).strip())
    if not m:
        return None
    token = m.group(1)
    try:
        dt = datetime.strptime(token, "%y%b%d%H%M").replace(tzinfo=EST)
        return dt
    except Exception:
        return None


def _fmt_ampm_no_leading_zero(dt: datetime) -> str:
    s = dt.strftime("%I:%M %p")
    if s.startswith("0"):
        s = s[1:]
    return s


def _strip_symbol_prefix_from_market_title(symbol: str, market_title: Optional[str]) -> str:
    """e.g. ``BTC price today at 5:15pm`` -> ``Price today at 5:15pm``."""
    s = (market_title or "").strip()
    if not s:
        return ""
    sym = (symbol or "").strip().upper()
    if sym and len(s) >= len(sym) + 1 and s.upper().startswith(sym + " "):
        rest = s[len(sym) + 1 :].lstrip()
    else:
        rest = s
    if not rest:
        return ""
    return rest[0].upper() + rest[1:] if len(rest) > 1 else rest.upper()


def _fetch_strike_table_market_title_tail(market_ticker: str, symbol: str = "BTC") -> str:
    """Latest ``market_title`` for this Kalshi market ticker from ``live_data.strike_table_15m``, no symbol prefix."""
    sym = (symbol or "").strip().upper()
    mt = str(market_ticker or "").strip()
    if not sym or not mt:
        return ""
    conn = None
    try:
        conn = _open_local_db()
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT market_title FROM live_data.strike_table_15m
                WHERE exchange = 'kalshi' AND symbol = %s AND ticker = %s AND market = '15m'
                  AND market_status = 'active'
                ORDER BY timestamp DESC NULLS LAST
                LIMIT 1
                """,
                (sym, mt),
            )
            row = cur.fetchone()
            if not row or not (row[0] or "").strip():
                cur.execute(
                    """
                    SELECT market_title FROM live_data.strike_table_15m
                    WHERE exchange = 'kalshi' AND symbol = %s AND ticker = %s AND market = '15m'
                    ORDER BY timestamp DESC NULLS LAST
                    LIMIT 1
                    """,
                    (sym, mt),
                )
                row = cur.fetchone()
            if row and row[0]:
                return _strip_symbol_prefix_from_market_title(sym, str(row[0]).strip())
    except Exception:
        logging.getLogger("orderbook_15m_table_watchdog").debug(
            "strike_table_15m market_title lookup failed for %s", mt, exc_info=True
        )
    finally:
        if conn is not None:
            conn.close()
    return ""


def _market_window_label_eastern(market_ticker: str) -> str:
    """15m window label in America/New_York (EST/EDT)."""
    end_est = parse_15m_ticker_end_est(market_ticker)
    if not end_est:
        return ""
    start_est = end_est - timedelta(minutes=15)
    a = start_est.astimezone(EST)
    b = end_est.astimezone(EST)
    tz = a.tzname() or "ET"
    return f"{a.strftime('%B')} {a.day}, {_fmt_ampm_no_leading_zero(a)}–{_fmt_ampm_no_leading_zero(b)} {tz}"


def _load_market_rest_header(market_ticker: str) -> dict[str, Any]:
    """
    Kalshi market ticker WS (see docs) does not include floor_strike or long-form title.
    Header primary line uses ``market_title`` from ``live_data.strike_table_15m`` (symbol stripped).
    One REST read per contract rollover supplies floor_strike for strike display in the book UI.
    """
    out: dict[str, Any] = {
        "kicker": "Crypto · 15min",
        "headline": "",
        "window": _market_window_label_eastern(market_ticker),
        "strike": "",
    }
    title_tail = _fetch_strike_table_market_title_tail(market_ticker, "BTC")
    if title_tail:
        out["headline"] = f"BTC 15 min • {title_tail}"
    else:
        out["headline"] = "BTC 15 min"
    try:
        from urllib.parse import quote

        path = quote(str(market_ticker).strip(), safe="")
        r = requests.get(
            f"{KALSHI_REST_BASE}/markets/{path}",
            headers=KALSHI_REST_HEADERS,
            timeout=10,
        )
        r.raise_for_status()
        m = (r.json() or {}).get("market") or {}
        fs = m.get("floor_strike")
        strike_txt = format_floor_strike_usd_comma_cents(fs) if fs is not None else ""
        if not strike_txt:
            yst = str(m.get("yes_sub_title") or "").strip()
            if yst.lower().startswith("target price:"):
                tail = yst.split(":", 1)[-1].strip().lstrip("$").replace(",", "")
                if tail:
                    strike_txt = format_floor_strike_usd_comma_cents(tail)
        if strike_txt:
            out["strike"] = strike_txt
        if m.get("title"):
            out["title"] = str(m.get("title")).strip()
    except Exception:
        pass
    if not out["headline"]:
        out["headline"] = "BTC 15 min"
    return out


def ensure_market_table(table_name: str) -> None:
    conn = _open_local_db()
    try:
        with conn.cursor() as cur:
            cur.execute("CREATE SCHEMA IF NOT EXISTS testing")
            cur.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {_quoted_testing_table(table_name)} (
                    side TEXT NOT NULL,
                    price_dollars NUMERIC(18,6) NOT NULL,
                    size_fp NUMERIC(18,2) NOT NULL,
                    seq BIGINT,
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    PRIMARY KEY (side, price_dollars)
                )
                """
            )
        conn.commit()
    finally:
        conn.close()


def _to_decimal(value: Any) -> Decimal:
    if value is None:
        raise InvalidOperation("None")
    return Decimal(str(value).strip())


def apply_snapshot(table_name: str, snapshot_msg: dict[str, Any], seq: Optional[int]) -> int:
    """
    Rebuild local orderbook table from snapshot baseline.
    """
    levels: list[tuple[str, Decimal, Decimal]] = []
    for side_key, side_name in (("yes_dollars_fp", "yes"), ("no_dollars_fp", "no")):
        arr = snapshot_msg.get(side_key) or []
        if not isinstance(arr, list):
            continue
        for level in arr:
            if not isinstance(level, list) or len(level) < 2:
                continue
            try:
                price = _to_decimal(level[0])
                size = _to_decimal(level[1])
            except Exception:
                continue
            levels.append((side_name, price, size))

    conn = _open_local_db()
    try:
        with conn.cursor() as cur:
            cur.execute(f"DELETE FROM {_quoted_testing_table(table_name)}")
            if levels:
                cur.executemany(
                    f"""
                    INSERT INTO {_quoted_testing_table(table_name)}
                    (side, price_dollars, size_fp, seq, updated_at)
                    VALUES (%s, %s, %s, %s, NOW())
                    """,
                    [(s, p, sz, seq) for (s, p, sz) in levels],
                )
        conn.commit()
        return len(levels)
    finally:
        conn.close()


def apply_delta(table_name: str, delta_msg: dict[str, Any], seq: Optional[int]) -> None:
    side = str(delta_msg.get("side") or "").strip().lower()
    if side not in ("yes", "no"):
        return
    try:
        price = _to_decimal(delta_msg.get("price_dollars"))
        delta = _to_decimal(delta_msg.get("delta_fp"))
    except Exception:
        return

    conn = _open_local_db()
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                INSERT INTO {_quoted_testing_table(table_name)}
                (side, price_dollars, size_fp, seq, updated_at)
                VALUES (%s, %s, %s, %s, NOW())
                ON CONFLICT (side, price_dollars)
                DO UPDATE SET
                    size_fp = {_quoted_testing_table(table_name)}.size_fp + EXCLUDED.size_fp,
                    seq = EXCLUDED.seq,
                    updated_at = NOW()
                """,
                (side, price, delta, seq),
            )
            cur.execute(
                f"""
                DELETE FROM {_quoted_testing_table(table_name)}
                WHERE side = %s AND price_dollars = %s AND size_fp <= 0
                """,
                (side, price),
            )
        conn.commit()
    finally:
        conn.close()


def _d(v: Any) -> Decimal:
    return Decimal(str(v))


def _fmt(v: Decimal, q: str = "0.0000") -> str:
    return str(v.quantize(Decimal(q)))


def _book_rows(levels: dict[Decimal, Decimal], *, reverse: bool, limit: int = 15) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for price in sorted(levels.keys(), reverse=reverse)[:limit]:
        size = levels[price]
        if size <= 0:
            continue
        out.append(
            {
                "price": _fmt(price),
                "size_fp": _fmt(size, "0.01"),
                "total_dollars": _fmt(price * size),
            }
        )
    return out


def _book_rows_near_touch(
    levels: dict[Decimal, Decimal], *, is_ask: bool, limit: Optional[int] = None
) -> list[dict[str, str]]:
    """
    Return levels nearest the spread (Kalshi-style ordering).
    - Asks: pick lowest prices (best asks), display high->low.
    - Bids: pick highest prices (best bids), display high->low so best bid sits at the gap.
    """
    prices = sorted([p for p, sz in levels.items() if sz > 0])
    if not prices:
        return []
    if is_ask:
        best = prices[:limit] if limit is not None else prices
        display = list(reversed(best))
    else:
        best = prices[-limit:] if limit is not None else prices
        display = list(reversed(best))
    out: list[dict[str, str]] = []
    for price in display:
        size = levels[price]
        out.append(
            {
                "price": _fmt(price),
                "size_fp": _fmt(size, "0.01"),
                "total_dollars": _fmt(price * size),
            }
        )
    return out


def _transform_complement_levels(levels: dict[Decimal, Decimal]) -> dict[Decimal, Decimal]:
    # Complementary quote transform: YES bid at p == NO ask at (1-p), and vice versa.
    transformed: dict[Decimal, Decimal] = {}
    for p, sz in levels.items():
        cp = Decimal("1") - p
        transformed[cp] = transformed.get(cp, Decimal("0")) + sz
    return transformed


class OrderbookTableWatchdog:
    def __init__(self) -> None:
        self.ws: Optional[websockets.WebSocketClientProtocol] = None
        self.command_id = 1
        self.current_ticker: Optional[str] = None
        self.current_table: Optional[str] = None
        self.current_sid: Optional[int] = None
        self.current_end_est: Optional[datetime] = None
        self.yes_levels: dict[Decimal, Decimal] = {}
        self.no_levels: dict[Decimal, Decimal] = {}
        self.bootstrap_candidates: list[str] = []
        self.bootstrap_index: int = -1
        self.ticker_fields: dict[str, Any] = {}
        self.market_header_meta: dict[str, Any] = {}
        self.log = logging.getLogger("orderbook_15m_table_watchdog")

    async def connect(self) -> None:
        self.ws = await websockets.connect(
            WS_URL,
            additional_headers=kalshi_ws_connect_headers(),
            ping_interval=20,
            ping_timeout=20,
            max_size=8_000_000,
        )
        self.log.info("connected websocket")

    async def _send(self, payload: dict[str, Any]) -> None:
        if not self.ws:
            raise RuntimeError("websocket not connected")
        await self.ws.send(json.dumps(payload))
        self.command_id += 1

    async def subscribe(self, market_ticker: str) -> None:
        table_name = _table_name_for_ticker(market_ticker)
        ensure_market_table(table_name)

        # Use explicit subscribe on rollover to avoid any ambiguity in update_subscription
        # payload semantics. We only ingest rows for current_ticker/current_table below.
        await self._send(
            {
                "id": self.command_id,
                "cmd": "subscribe",
                "params": {
                    "channels": ["orderbook_delta"],
                    "market_ticker": market_ticker,
                },
            }
        )
        await self._send(
            {
                "id": self.command_id,
                "cmd": "subscribe",
                "params": {
                    "channels": ["ticker"],
                    "market_tickers": [market_ticker],
                },
            }
        )

        self.current_ticker = market_ticker
        self.current_table = table_name
        self.current_end_est = parse_15m_ticker_end_est(market_ticker)
        self.yes_levels = {}
        self.no_levels = {}
        self.ticker_fields = {}
        self.market_header_meta = await asyncio.to_thread(_load_market_rest_header, market_ticker)
        self.log.info(
            "subscribed orderbook+ticker ticker=%s table=testing.%s",
            market_ticker,
            table_name,
        )

    def _ingest_ticker_msg(self, msg: dict[str, Any]) -> None:
        if not isinstance(msg, dict):
            return
        keep = (
            "market_ticker",
            "market_id",
            "price_dollars",
            "yes_bid_dollars",
            "yes_ask_dollars",
            "no_bid_dollars",
            "no_ask_dollars",
            "yes_bid_size_fp",
            "yes_ask_size_fp",
            "last_trade_size_fp",
            "volume_fp",
            "open_interest_fp",
            "dollar_volume",
            "dollar_open_interest",
            "ts_ms",
        )
        self.ticker_fields = {k: msg[k] for k in keep if k in msg}

    async def _subscribe_next_bootstrap_candidate(self) -> bool:
        if self.bootstrap_index + 1 >= len(self.bootstrap_candidates):
            return False
        self.bootstrap_index += 1
        await self.subscribe(self.bootstrap_candidates[self.bootstrap_index])
        return True

    def _publish_redis_ui(self, seq: Optional[int]) -> None:
        r = redis_client_optional()
        if r is None or not self.current_ticker:
            return
        try:
            # Websocket levels are side bids. Ask ladders are complementary.
            # Show only near-touch levels to mirror Kalshi viewport.
            yes_bids = _book_rows_near_touch(self.yes_levels, is_ask=False)
            no_bids = _book_rows_near_touch(self.no_levels, is_ask=False)
            yes_asks = _book_rows_near_touch(
                _transform_complement_levels(self.no_levels), is_ask=True
            )
            no_asks = _book_rows_near_touch(
                _transform_complement_levels(self.yes_levels), is_ask=True
            )
            last_yes = self.ticker_fields.get("price_dollars")
            yes_cents = ""
            no_cents = ""
            if last_yes is not None and str(last_yes).strip() != "":
                try:
                    d_yes = Decimal(str(last_yes).strip())
                    qy = (d_yes * Decimal("100")).quantize(Decimal("0.01"))
                    sy = str(qy)
                    if "." in sy:
                        sy = sy.rstrip("0").rstrip(".")
                    yes_cents = f"{sy}¢"
                    d_no = (Decimal("1") - d_yes).quantize(Decimal("0.0001"))
                    qn = (d_no * Decimal("100")).quantize(Decimal("0.01"))
                    sn = str(qn)
                    if "." in sn:
                        sn = sn.rstrip("0").rstrip(".")
                    no_cents = f"{sn}¢"
                except Exception:
                    yes_cents = ""
                    no_cents = ""
            payload = {
                "market_ticker": self.current_ticker,
                "header": {
                    "kicker": self.market_header_meta.get("kicker", "Crypto · 15min"),
                    "headline": self.market_header_meta.get("headline", ""),
                    "window": self.market_header_meta.get("window", ""),
                    "strike": self.market_header_meta.get("strike", ""),
                    "subtitle": self.market_header_meta.get("title", ""),
                },
                "last_trade": {"yes_cents": yes_cents, "no_cents": no_cents},
                "ticker_ws": dict(self.ticker_fields),
                "trade_yes": {
                    "asks": yes_asks,
                    "bids": yes_bids,
                },
                "trade_no": {
                    "asks": no_asks,
                    "bids": no_bids,
                },
            }
            raw = json.dumps(payload, default=str)
            r.set(REDIS_ORDERBOOK_KEY, raw)
            r.publish(REDIS_ORDERBOOK_CHANNEL, raw)
        except Exception as e:
            self.log.debug("redis ui publish skipped: %s", e)

    async def maybe_rollover(self) -> None:
        if not self.current_ticker or not self.current_end_est:
            return
        now_est = datetime.now(EST)
        if now_est < self.current_end_est:
            return
        next_ticker = _ticker_for_boundary_est(self.current_end_est + timedelta(minutes=15))
        if next_ticker != self.current_ticker:
            self.log.info("rollover old=%s new=%s", self.current_ticker, next_ticker)
            await self.subscribe(next_ticker)

    async def run(self) -> None:
        await self.connect()
        self.bootstrap_candidates = bootstrap_ticker_candidates()
        self.bootstrap_index = -1
        # Websocket-only bootstrap: try derived candidates until first non-empty snapshot.
        await self._subscribe_next_bootstrap_candidate()
        self.log.info("bootstrap candidates=%s", ",".join(self.bootstrap_candidates))

        last_roll_check = 0.0
        while True:
            if not self.ws:
                raise RuntimeError("websocket disconnected")
            raw = await self.ws.recv()
            now = time.time()
            if now - last_roll_check >= ROLL_CHECK_SEC:
                await self.maybe_rollover()
                last_roll_check = now

            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if not isinstance(data, dict):
                continue

            msg_type = data.get("type")
            if msg_type == "subscribed":
                msg = data.get("msg") or {}
                if isinstance(msg, dict) and msg.get("sid") is not None:
                    try:
                        self.current_sid = int(msg["sid"])
                    except Exception:
                        self.current_sid = None
                continue

            msg = data.get("msg") or {}
            mt = str(msg.get("market_ticker") or "").strip()

            if msg_type == "ticker" and mt and self.current_ticker and mt == self.current_ticker:
                self._ingest_ticker_msg(msg if isinstance(msg, dict) else {})
                self._publish_redis_ui(data.get("seq"))
                continue

            if not mt or not self.current_ticker or mt != self.current_ticker or not self.current_table:
                continue
            seq = data.get("seq")

            if msg_type == "orderbook_snapshot":
                n = apply_snapshot(self.current_table, msg, seq)
                self.yes_levels = {}
                self.no_levels = {}
                for level in msg.get("yes_dollars_fp") or []:
                    if isinstance(level, list) and len(level) >= 2:
                        try:
                            self.yes_levels[_d(level[0])] = _d(level[1])
                        except Exception:
                            continue
                for level in msg.get("no_dollars_fp") or []:
                    if isinstance(level, list) and len(level) >= 2:
                        try:
                            self.no_levels[_d(level[0])] = _d(level[1])
                        except Exception:
                            continue
                self._publish_redis_ui(seq)
                self.log.info("snapshot applied ticker=%s levels=%s seq=%s", mt, n, seq)
                if n == 0:
                    switched = await self._subscribe_next_bootstrap_candidate()
                    if switched:
                        self.log.info(
                            "empty snapshot for %s; trying bootstrap candidate %s",
                            mt,
                            self.current_ticker,
                        )
            elif msg_type == "orderbook_delta":
                apply_delta(self.current_table, msg, seq)
                side = str(msg.get("side") or "").lower().strip()
                try:
                    price = _d(msg.get("price_dollars"))
                    delta = _d(msg.get("delta_fp"))
                except Exception:
                    continue
                book = self.yes_levels if side == "yes" else self.no_levels if side == "no" else None
                if book is None:
                    continue
                new_sz = book.get(price, Decimal("0")) + delta
                if new_sz <= 0:
                    book.pop(price, None)
                else:
                    book[price] = new_sz
                self._publish_redis_ui(seq)


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )
    watcher = OrderbookTableWatchdog()
    while True:
        try:
            asyncio.run(watcher.run())
            return 0
        except KeyboardInterrupt:
            return 0
        except Exception as e:
            logging.getLogger("orderbook_15m_table_watchdog").warning(
                "run error: %s (retry in 3s)", e
            )
            time.sleep(3)


if __name__ == "__main__":
    raise SystemExit(main())

