"""Dedicated Kalshi crypto 15m orderbook live feed.

Owns the hot Redis book for non-lean 15m markets. Architecture matches the
blank-slate lab: one WS ``orderbook_delta`` channel → apply in RAM → publish.
Redis flush is latest-wins on a side thread so the WS loop never waits on I/O.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import threading
import time
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from backend.core.market_watchdog.venues.kalshi.schedule import (
    SERIES_15M_BY_SYMBOL,
    clock_current_15m_ticker,
    clock_next_15m_ticker,
    is_lean_market_symbol,
    series_15m,
)
from backend.core.trade_monitor_orderbook_keys import trade_monitor_orderbook_redis_key

log = logging.getLogger("kalshi_ob_live")

WS_URL = os.getenv("KALSHI_WS_URL", "wss://external-api-ws.kalshi.com/trade-api/ws/v2")
WS_SIGN_PATH = "/trade-api/ws/v2"
LIVE_STATE_CHANNEL = os.getenv("LIVE_STATE_UPDATED_CHANNEL", "rec_io:live_state:updated")


def ob_live_owner_enabled() -> bool:
    """When true, watchdog must not subscribe crypto/full 15m orderbooks."""
    raw = os.getenv("REC_KALSHI_OB_LIVE_OWNER", "1").strip().lower()
    return raw not in ("0", "false", "no", "off")


def owned_15m_symbols() -> List[str]:
    """Non-lean symbols this process owns (full orderbook 15m)."""
    out: List[str] = []
    for sym in SERIES_15M_BY_SYMBOL:
        if is_lean_market_symbol(sym):
            continue
        out.append(sym)
    return out


def _now_ms() -> int:
    return int(time.time() * 1000)


def _dec(v: Any) -> Decimal:
    return Decimal(str(v).strip())


def _opt_int(v: Any) -> Optional[int]:
    if v is None:
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _px_key(raw: Any) -> str:
    return str(_dec(raw).quantize(Decimal("0.000001")))


@dataclass
class Book:
    symbol: str
    series: str
    ticker: str = ""
    pending_ticker: str = ""
    yes: Dict[str, str] = field(default_factory=dict)
    no: Dict[str, str] = field(default_factory=dict)
    last_seq: Optional[int] = None
    valid: bool = False
    venue_ts_ms: Optional[int] = None
    sending_ts_ms: Optional[int] = None
    t_ws_recv_ms: Optional[int] = None
    t_apply_ms: Optional[int] = None
    clock: Any = None
    updates: int = 0


class LatestWinsRedisPublisher:
    """Side thread: publish only the newest book state per ticker."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._pending: Dict[str, dict[str, Any]] = {}
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread = threading.Thread(
            target=self._run, name="kalshi_ob_live_redis", daemon=True
        )
        self._r = None
        self.published = 0
        self.coalesced = 0

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        self._thread.join(timeout=2.0)

    def submit(self, payload: dict[str, Any]) -> None:
        mt = str(payload.get("market_ticker") or "").strip()
        if not mt:
            return
        with self._lock:
            if mt in self._pending:
                self.coalesced += 1
            self._pending[mt] = payload
        self._wake.set()

    def _redis(self):
        if self._r is not None:
            return self._r
        import redis

        url = os.getenv("REDIS_URL", "").strip()
        if url:
            self._r = redis.from_url(url, decode_responses=True)
        else:
            self._r = redis.Redis(
                host=os.getenv("REDIS_HOST", "localhost"),
                port=int(os.getenv("REDIS_PORT", "6379")),
                password=os.getenv("REDIS_PASSWORD") or None,
                decode_responses=True,
            )
        return self._r

    def _run(self) -> None:
        while not self._stop.is_set():
            self._wake.wait(timeout=0.05)
            self._wake.clear()
            batch: Dict[str, dict[str, Any]] = {}
            with self._lock:
                if self._pending:
                    batch, self._pending = self._pending, {}
            if not batch:
                continue
            try:
                self._flush_batch(batch)
            except Exception:
                log.exception("ob live redis flush failed")
                self._r = None

    def _flush_batch(self, batch: Dict[str, dict[str, Any]]) -> None:
        r = self._redis()
        pipe = r.pipeline()
        redis_written_ms = _now_ms()
        hints: list[dict[str, Any]] = []
        for mt, payload in batch.items():
            body = dict(payload)
            body["redis_written_ms"] = redis_written_ms
            pipe.set(
                trade_monitor_orderbook_redis_key(mt),
                json.dumps(body, default=str),
                ex=7200,
            )
            hints.append(body)
        pipe.execute()
        for body in hints:
            mt = str(body.get("market_ticker") or "")
            hint = {
                "type": "live_state_updated",
                "kind": "orderbook",
                "key": "",
                "market_ticker": mt,
                "market_interval": "15m",
                "book_seq": body.get("seq"),
                "ts_ms": body.get("ts_ms"),
                "venue_ts_ms": body.get("venue_ts_ms"),
                "sending_ts_ms": body.get("sending_ts_ms"),
                "redis_written_ms": redis_written_ms,
                "t_ws_recv_ms": body.get("t_ws_recv_ms"),
                "t_apply_ms": body.get("t_apply_ms"),
                "clock": body.get("clock"),
            }
            r.publish(LIVE_STATE_CHANNEL, json.dumps(hint, default=str))
            try:
                from backend.core.upper_tail_rail_trigger import (
                    maybe_emit_rail_from_orderbook_payload,
                )

                maybe_emit_rail_from_orderbook_payload(mt, body)
            except Exception:
                pass
            self.published += 1


def _book_payload(book: Book) -> dict[str, Any]:
    venue = book.venue_ts_ms
    return {
        "v": 1,
        "market_ticker": book.ticker,
        "yes": dict(book.yes),
        "no": dict(book.no),
        "seq": book.last_seq,
        "ts_ms": venue if venue is not None else book.t_apply_ms,
        "venue_ts_ms": venue,
        "sending_ts_ms": book.sending_ts_ms,
        "t_ws_recv_ms": book.t_ws_recv_ms,
        "t_apply_ms": book.t_apply_ms,
        "clock": book.clock,
        "valid": bool(book.valid),
    }


def _stamp(book: Book, envelope: dict, msg: dict, recv_ms: int) -> None:
    book.t_ws_recv_ms = recv_ms
    book.t_apply_ms = _now_ms()
    book.venue_ts_ms = _opt_int(msg.get("ts_ms"))
    book.sending_ts_ms = _opt_int(envelope.get("sending_ts_ms"))
    book.clock = msg.get("clock")


def _enqueue_cycle(book: Book, *, kind: str, side: str = "", price: str = "", delta: Any = None) -> None:
    """Off-hot-path cycle package recording for the active ticker only."""
    try:
        from backend.core.cycle_hot_tables import enqueue_delta, enqueue_snapshot
        from backend.core.market_watchdog.venues.kalshi.schedule import (
            clock_current_15m_ticker as clock_cur,
        )

        now = time.time()
        if book.ticker != clock_cur(book.symbol, now):
            return
        if kind == "snapshot":
            enqueue_snapshot(
                book.ticker,
                yes=dict(book.yes),
                no=dict(book.no),
                seq=book.last_seq,
                reason="snapshot",
                ts_ms=book.venue_ts_ms,
                sending_ts_ms=book.sending_ts_ms,
                t_ws_recv_ms=book.t_ws_recv_ms,
            )
        else:
            enqueue_delta(
                book.ticker,
                side=side,
                price=price,
                delta=delta,
                seq=book.last_seq,
                ts_ms=book.venue_ts_ms,
                sending_ts_ms=book.sending_ts_ms,
                t_ws_recv_ms=book.t_ws_recv_ms,
            )
    except Exception:
        pass


class ObLiveFeed:
    def __init__(self, symbols: List[str], publisher: LatestWinsRedisPublisher) -> None:
        self.symbols = [s.upper() for s in symbols]
        self.publisher = publisher
        self.books: Dict[str, Book] = {
            s: Book(symbol=s, series=series_15m(s)) for s in self.symbols
        }
        self.by_ticker: Dict[str, Book] = {}
        self.channel_seq: Optional[int] = None
        self.channel_gaps = 0
        self.sid: Optional[int] = None

    def bind(self, symbol: str, ticker: str) -> bool:
        """Bind active ticker. Returns True if ticker changed (book reset)."""
        book = self.books[symbol]
        ticker = str(ticker or "").strip()
        if book.ticker == ticker:
            if ticker:
                self.by_ticker[ticker] = book
            return False
        if book.ticker and book.ticker in self.by_ticker:
            self.by_ticker.pop(book.ticker, None)
        book.ticker = ticker
        book.yes.clear()
        book.no.clear()
        book.last_seq = None
        book.valid = False
        if ticker:
            self.by_ticker[ticker] = book
        return True

    def set_pending(self, symbol: str, ticker: str) -> bool:
        book = self.books[symbol]
        ticker = str(ticker or "").strip()
        if book.pending_ticker == ticker:
            return False
        book.pending_ticker = ticker
        return True

    def subscribed_tickers(self) -> List[str]:
        out: list[str] = []
        seen: set[str] = set()
        for b in self.books.values():
            for mt in (b.ticker, b.pending_ticker):
                if mt and mt not in seen:
                    seen.add(mt)
                    out.append(mt)
        return out

    def note_seq(self, seq: Any) -> str:
        if seq is None:
            return "ok"
        seq_i = int(seq)
        if self.channel_seq is None:
            self.channel_seq = seq_i
            return "ok"
        if seq_i <= self.channel_seq:
            return "skip"
        if seq_i > self.channel_seq + 1:
            self.channel_gaps += 1
            self.channel_seq = seq_i
            for b in self.books.values():
                b.valid = False
            return "gap"
        self.channel_seq = seq_i
        return "ok"

    def apply_snapshot(self, book: Book, envelope: dict, msg: dict, recv_ms: int) -> None:
        yes: Dict[str, str] = {}
        no: Dict[str, str] = {}
        for key, dest in (("yes_dollars_fp", yes), ("no_dollars_fp", no)):
            for level in msg.get(key) or []:
                if isinstance(level, list) and len(level) >= 2:
                    try:
                        p = _px_key(level[0])
                        s = str(_dec(level[1]).quantize(Decimal("0.01")))
                        if _dec(s) > 0:
                            dest[p] = s
                    except Exception:
                        continue
        book.yes, book.no = yes, no
        seq = envelope.get("seq")
        if seq is not None:
            book.last_seq = int(seq)
        book.valid = True
        _stamp(book, envelope, msg, recv_ms)
        book.updates += 1
        self.publisher.submit(_book_payload(book))
        _enqueue_cycle(book, kind="snapshot")

    def apply_delta(self, book: Book, envelope: dict, msg: dict, recv_ms: int) -> None:
        if not book.valid:
            return
        side = str(msg.get("side") or "").lower()
        if side not in ("yes", "no"):
            return
        try:
            price = _px_key(msg["price_dollars"])
            delta = _dec(msg.get("delta_fp"))
        except Exception:
            return
        levels = book.yes if side == "yes" else book.no
        cur = _dec(levels.get(price, "0"))
        new_sz = cur + delta
        if new_sz <= 0:
            levels.pop(price, None)
        else:
            levels[price] = str(new_sz.quantize(Decimal("0.01")))
        seq = envelope.get("seq")
        if seq is not None:
            book.last_seq = int(seq)
        _stamp(book, envelope, msg, recv_ms)
        book.updates += 1
        self.publisher.submit(_book_payload(book))
        _enqueue_cycle(book, kind="delta", side=side, price=price, delta=delta)


def _ws_headers() -> dict[str, str]:
    from cryptography.hazmat.backends import default_backend
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding

    key_id = os.getenv("KALSHI_API_KEY_ID", "").strip()
    pem_path = os.getenv("KALSHI_PRIVATE_KEY_PATH", "").strip()
    if not key_id or not pem_path:
        raise RuntimeError("Set KALSHI_API_KEY_ID and KALSHI_PRIVATE_KEY_PATH")
    ts = str(_now_ms())
    sig_text = ts + "GET" + WS_SIGN_PATH
    with open(Path(pem_path).expanduser(), "rb") as f:
        key = serialization.load_pem_private_key(
            f.read(), password=None, backend=default_backend()
        )
    sig = key.sign(
        sig_text.encode(),
        padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.MAX_LENGTH),
        hashes.SHA256(),
    )
    return {
        "KALSHI-ACCESS-KEY": key_id,
        "KALSHI-ACCESS-TIMESTAMP": ts,
        "KALSHI-ACCESS-SIGNATURE": base64.b64encode(sig).decode(),
    }


def _sync_clock_bindings(feed: ObLiveFeed) -> Tuple[List[str], List[str]]:
    """Bind current+next tickers from wall clock. Returns (adds, drops).

    Clock is the only authority for which ticker is active. Pending is
    subscribed early but ignored until the clock advances (no WS promote).
    """
    now = time.time()
    want: set[str] = set()
    adds: list[str] = []
    prev_sub = set(feed.subscribed_tickers())
    for sym, book in feed.books.items():
        cur = clock_current_15m_ticker(sym, now)
        nxt = clock_next_15m_ticker(sym, now)
        old = book.ticker
        if feed.bind(sym, cur):
            if cur:
                adds.append(cur)
            log.info("bind %s active %s (was %s)", sym, cur, old or "-")
        if cur:
            want.add(cur)
        if nxt and nxt != cur:
            old_p = book.pending_ticker
            if feed.set_pending(sym, nxt):
                adds.append(nxt)
                log.info("bind %s pending %s (was %s)", sym, nxt, old_p or "-")
            want.add(nxt)
        else:
            feed.set_pending(sym, "")
    drops = [mt for mt in prev_sub if mt and mt not in want]
    # Dedupe adds that are already subscribed
    adds = [mt for mt in adds if mt and mt not in (prev_sub - set(drops))]
    return adds, drops


async def run_ob_live(symbols: Optional[List[str]] = None) -> None:
    import websockets

    from backend.core.market_watchdog.venues.kalshi.auth import (
        load_kalshi_credentials_from_disk,
    )

    load_kalshi_credentials_from_disk()
    syms = symbols or owned_15m_symbols()
    if not syms:
        raise RuntimeError("no non-lean 15m symbols to own")
    publisher = LatestWinsRedisPublisher()
    publisher.start()
    feed = ObLiveFeed(syms, publisher)
    _sync_clock_bindings(feed)
    log.info("kalshi_ob_live starting symbols=%s tickers=%s", syms, feed.subscribed_tickers())

    cmd_id = 1
    backoff = 1.0
    while True:
        roll_task: Optional[asyncio.Task] = None
        try:
            headers = _ws_headers()
            async with websockets.connect(
                WS_URL,
                additional_headers=headers,
                ping_interval=20,
                ping_timeout=20,
                max_size=8 * 1024 * 1024,
            ) as ws:
                backoff = 1.0
                feed.channel_seq = None
                adds, _drops = _sync_clock_bindings(feed)
                tickers = feed.subscribed_tickers()
                cmd_id += 1
                await ws.send(
                    json.dumps(
                        {
                            "id": cmd_id,
                            "cmd": "subscribe",
                            "params": {
                                "channels": ["orderbook_delta"],
                                "market_tickers": tickers,
                            },
                        }
                    )
                )
                log.info("subscribed n=%s %s", len(tickers), tickers)

                async def _update(action: str, market_tickers: list[str]) -> None:
                    nonlocal cmd_id
                    if feed.sid is None or not market_tickers:
                        return
                    cmd_id += 1
                    await ws.send(
                        json.dumps(
                            {
                                "id": cmd_id,
                                "cmd": "update_subscription",
                                "params": {
                                    "sids": [feed.sid],
                                    "action": action,
                                    "market_tickers": market_tickers,
                                },
                            }
                        )
                    )

                async def roll_watch() -> None:
                    while True:
                        await asyncio.sleep(1.0)
                        adds2, drops2 = _sync_clock_bindings(feed)
                        if adds2:
                            await _update("add_markets", adds2)
                            # Snapshot only newly active markets (not pending).
                            actives = [
                                b.ticker
                                for b in feed.books.values()
                                if b.ticker and b.ticker in adds2
                            ]
                            if actives:
                                await _update("get_snapshot", actives)
                        if drops2:
                            await _update("delete_markets", drops2)

                roll_task = asyncio.create_task(roll_watch(), name="ob_live_roll")
                last_stat = time.monotonic()
                last_age: Optional[int] = None
                snap_requested = False
                async for raw in ws:
                    recv_ms = _now_ms()
                    try:
                        envelope = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    etype = str(envelope.get("type") or "")
                    if etype == "subscribed":
                        msg = envelope.get("msg") or {}
                        sid = envelope.get("sid") or msg.get("sid")
                        try:
                            feed.sid = int(sid) if sid is not None else None
                        except (TypeError, ValueError):
                            feed.sid = None
                        log.info("ws sid=%s", feed.sid)
                        if not snap_requested:
                            actives = [b.ticker for b in feed.books.values() if b.ticker]
                            await _update("get_snapshot", actives)
                            snap_requested = True
                        continue
                    if etype in ("ok", "error"):
                        if etype == "error":
                            log.warning("ws error %s", envelope)
                        continue
                    if etype not in ("orderbook_snapshot", "orderbook_delta"):
                        continue
                    msg = envelope.get("msg") or {}
                    mt = str(msg.get("market_ticker") or "").strip()
                    ch = feed.note_seq(envelope.get("seq"))
                    if ch == "skip":
                        continue
                    if ch == "gap":
                        await _update("get_snapshot", feed.subscribed_tickers())
                    # Clock owns rollover. Pending-market noise is ignored until
                    # roll_watch rebinds active via wall clock.
                    book = feed.by_ticker.get(mt)
                    if book is None or mt != book.ticker:
                        continue
                    if etype == "orderbook_snapshot":
                        feed.apply_snapshot(book, envelope, msg, recv_ms)
                    else:
                        feed.apply_delta(book, envelope, msg, recv_ms)
                    if book.venue_ts_ms is not None:
                        last_age = recv_ms - int(book.venue_ts_ms)
                    now_m = time.monotonic()
                    if now_m - last_stat >= 5.0:
                        last_stat = now_m
                        parts = [
                            f"{b.symbol}:{'ok' if b.valid else 'wait'}/u={b.updates}"
                            for b in feed.books.values()
                        ]
                        log.info(
                            "stats gaps=%s pub=%s coal=%s last_venue_to_recv_ms=%s %s",
                            feed.channel_gaps,
                            publisher.published,
                            publisher.coalesced,
                            last_age,
                            " ".join(parts),
                        )
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("reconnect in %.1fs", backoff)
            await asyncio.sleep(backoff)
            backoff = min(30.0, backoff * 2)
        finally:
            if roll_task is not None:
                roll_task.cancel()
                try:
                    await roll_task
                except asyncio.CancelledError:
                    pass
