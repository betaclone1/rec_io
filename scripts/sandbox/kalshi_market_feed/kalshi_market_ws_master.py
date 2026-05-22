#!/usr/bin/env python3
"""
Kalshi sandbox — single-process market WebSocket master.

GET /markets per series on startup and on SANDBOX_KALSHI_SCHEDULE_REFRESH_SEC (default 15m)
for pre-discovery only — never on quarter-hour rollover. Rollover uses wall-clock ticker +
WSS only. One WSS (ticker + orderbook_delta + market_lifecycle_v2).
market_result from ``market_lifecycle_v2`` ``determined``/``settled`` (prod path); ticker WS kept as fallback.
Orderbook ``seq`` is per subscription (sid), not per market. sandbox Redis hot state, JSONL events.

Run:
  python scripts/sandbox/kalshi_market_feed/kalshi_market_ws_master.py

Monitor (separate terminal):
  python scripts/sandbox/kalshi_market_feed/kalshi_market_feed_monitor.py

WS rollover verification (no REST): JSONL ``rollover_15m`` at each quarter hour, then
``market_result`` with ``source=lifecycle_ws`` for ``outgoing_ticker``. Log line:
``WS_ROLLOVER_OK market_result … (lifecycle_ws)``.

Env:
  SANDBOX_KALSHI_SYMBOLS     Comma-separated symbols, default BTC,ETH,SOL,XRP
  SANDBOX_KALSHI_15M_ONLY      default 0 (multi-strike hourly ATM window on)
  KALSHI_API_KEY_ID / KALSHI_PRIVATE_KEY_PATH
  REDIS_URL or REDIS_HOST, REDIS_PORT
  SANDBOX_KALSHI_REDIS_PREFIX  default sandbox:kalshi:
  SANDBOX_KALSHI_PREDISCOVER_HOURS  default 4 (markets close-time window ahead)
  SANDBOX_KALSHI_SCHEDULE_REFRESH_SEC  default 900 (15 minutes; pre-discovery only)
  SANDBOX_KALSHI_ORDERBOOK_CUTOVER_SEC  default 2
  SANDBOX_KALSHI_OUTGOING_TRACK_SEC  default 960 (~16m; one prior 15m for market_result)
  SANDBOX_KALSHI_HOURLY_ATM_STRIKES_EACH_SIDE  default 20 (spot-centered, same as market_watchdog_ws)
  SANDBOX_KALSHI_EVENT_LOG     default <this_dir>/kalshi_market_events.jsonl
  SANDBOX_KALSHI_DISTURBANCE_LOG  default <this_dir>/kalshi_market_disturbances.jsonl

No imports from backend/ or scripts/. Phase 2 maps Redis shapes to prod hot state.

Disturbance log (``kalshi_market_disturbances.jsonl``): WS down/up, resync batches, seq gaps —
not per-ticker noise, not rollover/cutover. Use for multi-hour soak trust tests.

Verified baseline (rollover + lifecycle_ws market_result): see CHECKPOINT_WS_ROLLOVER_BASELINE.md
in this directory. Return here before extending the feed.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import re
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Deque, Iterable, Optional
from zoneinfo import ZoneInfo

import requests
import websockets
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

# --- Kalshi series registry (symbol-agnostic; extend here) ---
SERIES_15M_BY_SYMBOL: dict[str, str] = {
    "BTC": "KXBTC15M",
    "ETH": "KXETH15M",
    "SOL": "KXSOL15M",
    "XRP": "KXXRP15M",
}
SERIES_HOURLY_BY_SYMBOL: dict[str, str] = {
    "BTC": "KXBTCD",
    "ETH": "KXETHD",
    "SOL": "KXSOLD",
}

EST = ZoneInfo("America/New_York")
MON_SHORT = (
    "JAN", "FEB", "MAR", "APR", "MAY", "JUN",
    "JUL", "AUG", "SEP", "OCT", "NOV", "DEC",
)

WS_URL = "wss://external-api-ws.kalshi.com/trade-api/ws/v2"
WS_SIGN_PATH = "/trade-api/ws/v2"
REST_BASE = "https://external-api.kalshi.com/trade-api/v2"
REST_HEADERS = {"Accept": "application/json", "User-Agent": "SandboxKalshiMarketWsMaster/1.0"}

SANDBOX_DIR = Path(__file__).resolve().parent
REDIS_PREFIX = os.getenv("SANDBOX_KALSHI_REDIS_PREFIX", "sandbox:kalshi:").strip()
PREDISCOVER_HOURS = float(os.getenv("SANDBOX_KALSHI_PREDISCOVER_HOURS", "4"))
ORDERBOOK_CUTOVER_SEC = float(os.getenv("SANDBOX_KALSHI_ORDERBOOK_CUTOVER_SEC", "2"))
# Only track the just-expired 15m for market_result; drop older without cluttering UI/subs.
OUTGOING_TRACK_SEC = float(os.getenv("SANDBOX_KALSHI_OUTGOING_TRACK_SEC", "960"))
HOURLY_ATM_EACH_SIDE = int(os.getenv("SANDBOX_KALSHI_HOURLY_ATM_STRIKES_EACH_SIDE", "20"))
PERIODIC_SNAPSHOT_SEC = float(os.getenv("SANDBOX_KALSHI_PERIODIC_SNAPSHOT_SEC", "0"))
SCHEDULE_REFRESH_SEC = float(os.getenv("SANDBOX_KALSHI_SCHEDULE_REFRESH_SEC", "900"))
ONLY_15M = os.getenv("SANDBOX_KALSHI_15M_ONLY", "0").strip().lower() in ("1", "true", "yes")
DEFAULT_SYMBOLS = ",".join(SERIES_15M_BY_SYMBOL.keys())
WS_MARKET_CHUNK = max(1, int(os.getenv("SANDBOX_KALSHI_WS_MARKET_CHUNK", "80")))
CHANNEL_RESYNC_DEBOUNCE_SEC = float(os.getenv("SANDBOX_KALSHI_CHANNEL_RESYNC_DEBOUNCE_SEC", "10"))
CHANNEL_RESYNC_MIN_INTERVAL_SEC = float(
    os.getenv("SANDBOX_KALSHI_CHANNEL_RESYNC_MIN_INTERVAL_SEC", "45")
)
META_HEARTBEAT_SEC = float(os.getenv("SANDBOX_KALSHI_META_HEARTBEAT_SEC", "0.5"))
LIFECYCLE_SYNC_SEC = float(os.getenv("SANDBOX_KALSHI_LIFECYCLE_SYNC_SEC", "1.0"))
PUBLISH_COALESCE_SEC = max(
    0.01, float(os.getenv("SANDBOX_KALSHI_PUBLISH_COALESCE_MS", "50")) / 1000.0
)
EVENT_LOG_PATH = Path(
    os.getenv("SANDBOX_KALSHI_EVENT_LOG", str(SANDBOX_DIR / "kalshi_market_events.jsonl"))
)
DISTURBANCE_LOG_PATH = Path(
    os.getenv(
        "SANDBOX_KALSHI_DISTURBANCE_LOG",
        str(SANDBOX_DIR / "kalshi_market_disturbances.jsonl"),
    )
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [kalshi_market_ws_master] %(message)s",
)
log = logging.getLogger("kalshi_market_ws_master")

_REST_LOCK = threading.Lock()
_event_queue: Deque[dict[str, Any]] = deque(maxlen=100_000)
_disturbance_queue: Deque[dict[str, Any]] = deque(maxlen=10_000)


def _load_kalshi_credentials_from_disk() -> None:
    """Local dev: load user_0001 prod credentials when env vars are unset."""
    if os.getenv("KALSHI_API_KEY_ID", "").strip() and os.getenv("KALSHI_PRIVATE_KEY_PATH", "").strip():
        return
    repo_root = Path(__file__).resolve().parents[3]
    cred_dir = (
        repo_root
        / "backend"
        / "data"
        / "users"
        / "user_0001"
        / "credentials"
        / "kalshi-credentials"
        / "prod"
    )
    env_path = cred_dir / ".env"
    pem_path = cred_dir / "kalshi.pem"
    if not env_path.is_file() or not pem_path.is_file():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        key, val = s.split("=", 1)
        key, val = key.strip(), val.strip()
        if key == "KALSHI_API_KEY_ID" and val:
            os.environ.setdefault("KALSHI_API_KEY_ID", val)
        elif key == "KALSHI_PRIVATE_KEY_PATH" and val:
            p = Path(val)
            os.environ.setdefault(
                "KALSHI_PRIVATE_KEY_PATH",
                str(p if p.is_absolute() else cred_dir / p),
            )
    if not os.getenv("KALSHI_PRIVATE_KEY_PATH", "").strip():
        os.environ["KALSHI_PRIVATE_KEY_PATH"] = str(pem_path)


def _active_symbols() -> list[str]:
    raw = os.getenv("SANDBOX_KALSHI_SYMBOLS", DEFAULT_SYMBOLS).strip()
    out = [s.strip().upper() for s in raw.split(",") if s.strip()]
    if not out:
        out = ["BTC"]
    for sym in out:
        if sym not in SERIES_15M_BY_SYMBOL:
            raise ValueError(
                f"Unknown symbol {sym!r}; supported: {sorted(SERIES_15M_BY_SYMBOL)}"
            )
    return out


def _series_15m(symbol: str) -> str:
    return SERIES_15M_BY_SYMBOL[symbol.upper()]


def _series_hourly(symbol: str) -> Optional[str]:
    return SERIES_HOURLY_BY_SYMBOL.get(symbol.upper())


# --- durable events ---
def _emit_event(event_type: str, **payload: Any) -> None:
    _event_queue.append(
        {"type": event_type, "ts": datetime.now(timezone.utc).isoformat(), **payload}
    )


def _emit_disturbance(event_type: str, **payload: Any) -> None:
    """Curated feed incidents for soak tests (rollover/cutover excluded)."""
    _disturbance_queue.append(
        {"type": event_type, "ts": datetime.now(timezone.utc).isoformat(), **payload}
    )


def _flush_disturbances_sync() -> None:
    if not _disturbance_queue:
        return
    DISTURBANCE_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    batch = []
    while _disturbance_queue:
        batch.append(_disturbance_queue.popleft())
    with open(DISTURBANCE_LOG_PATH, "a", encoding="utf-8") as f:
        for rec in batch:
            f.write(json.dumps(rec, default=str) + "\n")


def _flush_events_sync() -> None:
    if not _event_queue:
        return
    EVENT_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    batch = []
    while _event_queue:
        batch.append(_event_queue.popleft())
    with open(EVENT_LOG_PATH, "a", encoding="utf-8") as f:
        for rec in batch:
            f.write(json.dumps(rec, default=str) + "\n")


async def _event_flush_loop() -> None:
    while True:
        await asyncio.sleep(0.05)
        await asyncio.to_thread(_flush_events_sync)
        await asyncio.to_thread(_flush_disturbances_sync)


# --- auth / rest ---
def _ws_headers() -> dict[str, str]:
    key_id = os.getenv("KALSHI_API_KEY_ID", "").strip()
    pem_path = os.getenv("KALSHI_PRIVATE_KEY_PATH", "").strip()
    if not key_id or not pem_path:
        raise RuntimeError("Set KALSHI_API_KEY_ID and KALSHI_PRIVATE_KEY_PATH")
    pem = Path(pem_path).expanduser()
    ts = str(int(time.time() * 1000))
    sig_text = ts + "GET" + WS_SIGN_PATH
    with open(pem, "rb") as f:
        key = serialization.load_pem_private_key(f.read(), password=None, backend=default_backend())
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


def _rest_get(path: str, params: Optional[dict[str, Any]] = None) -> Any:
    url = f"{REST_BASE}{path}"
    with _REST_LOCK:
        r = requests.get(url, headers=REST_HEADERS, params=params or {}, timeout=30)
        if r.status_code == 429:
            time.sleep(5.0)
            r = requests.get(url, headers=REST_HEADERS, params=params or {}, timeout=30)
    r.raise_for_status()
    return r.json()


def _prediscover_close_horizon(now: datetime) -> int:
    """Unix close_ts upper bound: PREDISCOVER_HOURS ahead + buffer so last 15m slot is included."""
    extra_min = 45  # up to three more 15m boundaries Kalshi may list past the raw 4h cut
    horizon = now + timedelta(hours=PREDISCOVER_HOURS, minutes=extra_min)
    return int(horizon.timestamp())


def _fetch_markets_for_series(series_ticker: str, now: datetime) -> list[dict[str, Any]]:
    """Single REST poll: paginated GET /markets for one series_ticker."""
    min_close = int((now - timedelta(hours=2)).timestamp())
    max_close = _prediscover_close_horizon(now)
    out: list[dict[str, Any]] = []
    cursor: Optional[str] = None
    while True:
        params: dict[str, Any] = {
            "series_ticker": series_ticker,
            "min_close_ts": min_close,
            "max_close_ts": max_close,
            "limit": 1000,
        }
        if cursor:
            params["cursor"] = cursor
        data = _rest_get("/markets", params)
        out.extend(m for m in (data.get("markets") or []) if isinstance(m, dict))
        cursor = data.get("cursor")
        if not cursor:
            break
    return out


# --- redis ---
def _redis():
    import redis

    url = os.getenv("REDIS_URL", "").strip()
    if url:
        return redis.from_url(url, decode_responses=True)
    return redis.Redis(
        host=os.getenv("REDIS_HOST", "localhost"),
        port=int(os.getenv("REDIS_PORT", "6379")),
        password=os.getenv("REDIS_PASSWORD") or None,
        decode_responses=True,
    )


def _sanitize_ticker_key(market_ticker: str) -> str:
    t = re.sub(r"[^A-Za-z0-9_]+", "_", market_ticker.strip()).strip("_").lower()
    return (t[:50] if t else "unknown")


def _rkey_schedule(interval: str, symbol: str) -> str:
    return f"{REDIS_PREFIX}schedule:v1:{interval}:{symbol.upper()}"


def _rkey_orderbook(market_ticker: str) -> str:
    return f"{REDIS_PREFIX}orderbook:v1:{_sanitize_ticker_key(market_ticker)}"


def _rkey_ticker(market_ticker: str) -> str:
    return f"{REDIS_PREFIX}ticker:v1:{_sanitize_ticker_key(market_ticker)}"


def _rkey_meta() -> str:
    return f"{REDIS_PREFIX}meta:v1"


def _rkey_settled() -> str:
    return f"{REDIS_PREFIX}settled:v1"


def _json_get(key: str) -> Any:
    raw = _redis().get(key)
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def _redis_set(key: str, obj: Any, ttl: int = 7200) -> None:
    _redis().set(key, json.dumps(obj, default=str), ex=ttl)


def _redis_del(key: str) -> None:
    try:
        _redis().delete(key)
    except Exception:
        pass


def _push_channel() -> str:
    return f"{REDIS_PREFIX}push:v1"


def _redis_publish_push(payload: dict[str, Any]) -> None:
    try:
        _redis().publish(_push_channel(), json.dumps(payload, default=str))
    except Exception:
        pass


def _parse_iso_ts(val: Any) -> Optional[float]:
    if not val:
        return None
    s = str(val).strip()
    try:
        if s.endswith("Z"):
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        else:
            dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except ValueError:
        return None


def _numeric_strike_from_market(market: dict[str, Any]) -> Optional[float]:
    """Align with prod ``strike_from_kalshi_15m_rest_market`` / floor_strike on REST rows."""
    fs = market.get("floor_strike")
    if fs is not None:
        try:
            return float(str(fs).replace("$", "").replace(",", "").strip())
        except (TypeError, ValueError):
            pass
    mt = str(market.get("ticker") or market.get("market_ticker") or "").strip()
    m = re.search(r"-T([\d.]+)$", mt)
    if m:
        try:
            return float(m.group(1))
        except ValueError:
            pass
    sub = str(market.get("subtitle") or "")
    if " or above" in sub:
        raw = sub.split(" or above")[0].strip().replace("$", "").replace(",", "")
        try:
            return float(raw)
        except ValueError:
            pass
    return None


def _hourly_spot_price(sym_u: str) -> Optional[float]:
    """Same sources as ``market_watchdog_ws._hourly_spot_price`` (live_symbol_status → 1s log)."""
    sym_u = sym_u.upper().strip()
    try:
        import psycopg2
    except ImportError:
        return None
    conn = None
    try:
        conn = psycopg2.connect(
            host=os.getenv("REC_DB_HOST", os.getenv("POSTGRES_HOST", "localhost")),
            port=int(os.getenv("REC_DB_PORT", os.getenv("POSTGRES_PORT", "5432"))),
            dbname=os.getenv("REC_DB_NAME", os.getenv("POSTGRES_DB", "rec_io")),
            user=os.getenv("REC_DB_USER", os.getenv("POSTGRES_USER", "postgres")),
            password=os.getenv("REC_DB_PASSWORD", os.getenv("POSTGRES_PASSWORD", "")),
        )
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
        pt = {
            "BTC": "live_price_log_1s_btc",
            "ETH": "live_price_log_1s_eth",
            "SOL": "live_price_log_1s_sol",
        }.get(sym_u)
        if pt:
            cur.execute(f"SELECT price FROM live_data.{pt} ORDER BY timestamp DESC LIMIT 1")
            row2 = cur.fetchone()
            if row2 and row2[0] is not None:
                return float(row2[0])
    except Exception as e:
        log.debug("hourly spot lookup failed for %s: %s", sym_u, e)
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
    return None


def _filter_hourly_markets_atm_window(
    markets: list[dict[str, Any]], symbol: str, *, strikes_each_side: int
) -> list[dict[str, Any]]:
    """
    Prod ``market_watchdog_ws``: keep (2 * strikes_each_side + 1) markets centered on spot,
    not median strike index.
    """
    if not markets or strikes_each_side <= 0:
        return list(markets)
    sym_u = symbol.upper().strip()
    pairs: list[tuple[float, dict[str, Any]]] = []
    for m in markets:
        fs = _numeric_strike_from_market(m)
        if fs is not None:
            pairs.append((fs, m))
    if not pairs:
        log.warning(
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
        log.warning(
            "hourly ATM cap: no spot for %s; using median strike %.2f",
            sym_u,
            spot,
        )
    best_i = min(range(len(strikes)), key=lambda i: abs(strikes[i] - spot))
    lo = max(0, best_i - strikes_each_side)
    hi = min(len(pairs) - 1, best_i + strikes_each_side)
    kept = pairs[lo : hi + 1]
    out = [m for _, m in kept]
    log.info(
        "hourly ATM cap %s: %s -> %s (spot=%.2f idx=%s [%s,%s] side=%s)",
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


# --- schedule ---
@dataclass
class MarketScheduleEntry:
    market_ticker: str
    symbol: str
    interval: str
    open_ts: float
    close_ts: float
    event_ticker: str = ""
    market_result: Optional[str] = None


@dataclass
class KalshiMarketWsMaster:
    symbols: list[str]
    schedule_by_symbol: dict[str, dict[str, list[MarketScheduleEntry]]] = field(default_factory=dict)
    books: dict[str, dict[str, Any]] = field(default_factory=dict)
    ticker_sid: Optional[int] = None
    orderbook_sid: Optional[int] = None
    lifecycle_sid: Optional[int] = None
    last_market_result: Optional[dict[str, Any]] = None
    last_rollover_boundary_key: Optional[str] = None
    ticker_subscribed: set[str] = field(default_factory=set)
    orderbook_subscribed: set[str] = field(default_factory=set)
    outgoing_tickers: set[str] = field(default_factory=set)
    settled_tickers: set[str] = field(default_factory=set)
    ws_connected: bool = False
    ws_last_msg_mono: float = 0.0
    ws_send: Any = None
    cmd_id: int = 1
    resync_queue: Deque[tuple[list[str], str]] = field(default_factory=deque)
    ob_channel_last_seq: Optional[int] = None
    channel_resync_debounce_until: float = 0.0
    last_hour_boundary_key: str = ""
    channel_resync_count: int = 0
    channel_resync_last_mono: float = 0.0
    resync_in_progress: bool = False
    resync_task: Optional[asyncio.Task[Any]] = None
    dirty_ob: set[str] = field(default_factory=set)
    dirty_ticker: set[str] = field(default_factory=set)
    ticker_pending: dict[str, dict[str, Any]] = field(default_factory=dict)
    hourly_markets_raw: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    hourly_ob_tickers_cache: dict[str, list[str]] = field(default_factory=dict)
    hourly_ob_cache_key: dict[str, str] = field(default_factory=dict)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    def all_entries(self) -> list[MarketScheduleEntry]:
        rows: list[MarketScheduleEntry] = []
        for sym in self.symbols:
            for interval in ("15m", "hourly"):
                rows.extend(self.schedule_by_symbol.get(sym, {}).get(interval, []))
        return rows


def _phase(ent: MarketScheduleEntry, now: float, master: KalshiMarketWsMaster) -> str:
    if ent.market_ticker in master.settled_tickers or ent.market_result:
        return "settled"
    cut = ent.close_ts - ORDERBOOK_CUTOVER_SEC
    if now < ent.open_ts:
        return "upcoming"
    if now < cut:
        return "live"
    if now - ent.close_ts > OUTGOING_TRACK_SEC:
        return "dropped"
    return "outgoing"


def _market_to_entry(m: dict[str, Any], symbol: str, interval: str) -> Optional[MarketScheduleEntry]:
    mt = str(m.get("ticker") or "").strip()
    if not mt:
        return None
    close_ts = _parse_iso_ts(m.get("close_time"))
    open_ts = _parse_iso_ts(m.get("open_time"))
    if not close_ts:
        return None
    return MarketScheduleEntry(
        market_ticker=mt,
        symbol=symbol,
        interval=interval,
        open_ts=open_ts or 0,
        close_ts=close_ts,
        event_ticker=str(m.get("event_ticker") or ""),
        market_result=None,
    )


def _schedule_from_markets_poll(
    symbol: str,
    interval: str,
    series: str,
    now: datetime,
    *,
    markets: Optional[list[dict[str, Any]]] = None,
) -> list[MarketScheduleEntry]:
    if markets is None:
        try:
            markets = _fetch_markets_for_series(series, now)
        except Exception as e:
            log.warning("%s %s GET /markets series=%s: %s", symbol, interval, series, e)
            return []
    rows: list[MarketScheduleEntry] = []
    for m in markets:
        ent = _market_to_entry(m, symbol, interval)
        if ent:
            rows.append(ent)
    return sorted(rows, key=lambda e: e.open_ts)


def _current_live_15m(entries: list[MarketScheduleEntry], now: float, master: KalshiMarketWsMaster) -> Optional[str]:
    """Among REST live rows, pick the most recently opened (current quarter)."""
    live = [e for e in entries if _phase(e, now, master) == "live"]
    if not live:
        return None
    return max(live, key=lambda e: (e.open_ts, e.close_ts)).market_ticker


def _resolve_live_15m_current(
    symbol: str, entries: list[MarketScheduleEntry], now: float, master: KalshiMarketWsMaster
) -> str:
    """Wall-clock 15m ticker is authoritative; REST schedule can lag ~20s at rollover."""
    clock = _clock_current_15m_ticker(symbol, now)
    scheduled = _current_live_15m(entries, now, master)
    if scheduled and scheduled != clock:
        log.warning(
            "%s 15m live schedule=%s clock=%s — using clock for subs",
            symbol,
            scheduled,
            clock,
        )
    return clock


def _est_15m_period_end(now: datetime) -> datetime:
    """End of the active 15m window in US/Eastern (wall clock)."""
    est = now.astimezone(EST).replace(second=0, microsecond=0)
    slot_end_min = ((est.minute // 15) + 1) * 15
    if slot_end_min >= 60:
        return est.replace(minute=0) + timedelta(hours=1)
    return est.replace(minute=slot_end_min)


def _ticker_for_15m_end(series: str, end: datetime) -> str:
    end_e = end.astimezone(EST)
    yy, mon = end_e.year % 100, MON_SHORT[end_e.month - 1]
    mid = f"{yy:02d}{mon}{end_e.day:02d}{end_e.hour:02d}{end_e.minute:02d}"
    return f"{series}-{mid}-{end_e.minute:02d}"


def _clock_current_15m_ticker(symbol: str, now: float) -> str:
    series = _series_15m(symbol)
    end = _est_15m_period_end(datetime.fromtimestamp(now, timezone.utc))
    return _ticker_for_15m_end(series, end)


def _clock_previous_15m_ticker(symbol: str, now: float) -> str:
    series = _series_15m(symbol)
    end = _est_15m_period_end(datetime.fromtimestamp(now, timezone.utc))
    prev_end = end - timedelta(minutes=15)
    return _ticker_for_15m_end(series, prev_end)


def _on_15m_rollover_boundary(now: float) -> bool:
    """First ~12s of each quarter hour — refresh schedule + prioritize rollover subs."""
    est = datetime.fromtimestamp(now, timezone.utc).astimezone(EST)
    return est.minute % 15 == 0 and est.second < 12


def _rollover_boundary_key(now: float) -> str:
    est = datetime.fromtimestamp(now, timezone.utc).astimezone(EST)
    return f"{est.year:04d}{est.month:02d}{est.day:02d}{est.hour:02d}{est.minute // 15:02d}"


def _on_hour_boundary(now: float) -> bool:
    """First ~30s of each hour — refresh hourly ladder + resubscribe."""
    est = datetime.fromtimestamp(now, timezone.utc).astimezone(EST)
    return est.minute == 0 and est.second < 30


def _hour_boundary_key(now: float) -> str:
    est = datetime.fromtimestamp(now, timezone.utc).astimezone(EST)
    return f"{est.year:04d}{est.month:02d}{est.day:02d}{est.hour:02d}"


def _latest_outgoing_15m(
    entries: list[MarketScheduleEntry], now: float, master: KalshiMarketWsMaster
) -> Optional[str]:
    outgoing = [e for e in entries if _phase(e, now, master) == "outgoing"]
    if not outgoing:
        return None
    return max(outgoing, key=lambda e: e.close_ts).market_ticker


def _hourly_event_ticker_for_clock(symbol: str, now: float) -> Optional[str]:
    """Upcoming hour event (prod ``get_current_event_ticker`` uses now+1h EST)."""
    series = _series_hourly(symbol)
    if not series:
        return None
    est = datetime.fromtimestamp(now, timezone.utc).astimezone(EST)
    upcoming = est + timedelta(hours=1)
    return (
        f"{series}-{upcoming.strftime('%y')}{upcoming.strftime('%b').upper()}"
        f"{upcoming.strftime('%d')}{upcoming.strftime('%H')}"
    )


def _hourly_live_ob_tickers(
    symbol: str, entries: list[MarketScheduleEntry], now: float, master: KalshiMarketWsMaster
) -> list[str]:
    """Current-event live hourly ladder, ATM-capped around spot (prod market_watchdog_ws)."""
    if ONLY_15M or not _series_hourly(symbol):
        return []
    _ = entries  # schedule used for UI; subscription set comes from REST + spot window
    event_tk = _hourly_event_ticker_for_clock(symbol, now)
    raw = master.hourly_markets_raw.get(symbol.upper(), [])
    event_markets: list[dict[str, Any]] = []
    for m in raw:
        mt = str(m.get("ticker") or "").strip()
        if not mt:
            continue
        et = str(m.get("event_ticker") or "").strip()
        if event_tk:
            if et and et != event_tk and not mt.startswith(event_tk + "-"):
                continue
            if not et and not mt.startswith(event_tk + "-"):
                continue
        close_ts = _parse_iso_ts(m.get("close_time"))
        open_ts = _parse_iso_ts(m.get("open_time"))
        if close_ts is not None and now >= close_ts - ORDERBOOK_CUTOVER_SEC:
            continue
        if open_ts is not None and now < open_ts:
            continue
        event_markets.append(m)
    sym_u = symbol.upper()
    cache_key = f"{event_tk or 'none'}:{len(event_markets)}"
    if (
        master.hourly_ob_cache_key.get(sym_u) == cache_key
        and master.hourly_ob_tickers_cache.get(sym_u)
    ):
        return list(master.hourly_ob_tickers_cache[sym_u])
    capped = _filter_hourly_markets_atm_window(
        event_markets, symbol, strikes_each_side=HOURLY_ATM_EACH_SIDE
    )
    tickers = sorted(
        {str(m.get("ticker") or "").strip() for m in capped if str(m.get("ticker") or "").strip()}
    )
    master.hourly_ob_tickers_cache[sym_u] = tickers
    master.hourly_ob_cache_key[sym_u] = cache_key
    return tickers


def _ticker_chunks(tickers: Iterable[str]) -> list[list[str]]:
    s = sorted(set(str(t).strip() for t in tickers if str(t).strip()))
    return [s[i : i + WS_MARKET_CHUNK] for i in range(0, len(s), WS_MARKET_CHUNK)]


def _lifecycle_sets(
    master: KalshiMarketWsMaster, now: float
) -> tuple[set[str], set[str], set[str]]:
    """15m current quarter per symbol + hourly ATM window on current event."""
    ticker_sub: set[str] = set()
    ob_sub: set[str] = set()
    track_outgoing: set[str] = set()
    for sym in master.symbols:
        entries_15m = master.schedule_by_symbol.get(sym, {}).get("15m", [])
        current = _resolve_live_15m_current(sym, entries_15m, now, master)
        prev = _latest_outgoing_15m(entries_15m, now, master)
        if prev:
            track_outgoing.add(prev)
        if current:
            ticker_sub.add(current)
            ob_sub.add(current)
        if not ONLY_15M:
            entries_h = master.schedule_by_symbol.get(sym, {}).get("hourly", [])
            for mt in _hourly_live_ob_tickers(sym, entries_h, now, master):
                ticker_sub.add(mt)
                ob_sub.add(mt)
    master.outgoing_tickers = track_outgoing
    for mt in track_outgoing:
        if mt not in master.settled_tickers:
            ticker_sub.add(mt)
    return ticker_sub, ob_sub, ob_sub - master.orderbook_subscribed


# --- orderbook (channel seq on orderbook_sid) ---
def _dec(v: Any) -> Decimal:
    return Decimal(str(v).strip())


def _book(master: KalshiMarketWsMaster, mt: str) -> dict[str, Any]:
    return master.books.setdefault(
        mt,
        {
            "yes": {},
            "no": {},
            "last_seq": None,
            "sid": None,
            "valid": False,
            "resync_count": 0,
            "last_book_mono": 0.0,
            "last_ticker_mono": 0.0,
            "last_book_wall_at": 0.0,
            "last_ticker_wall_at": 0.0,
        },
    )


def _parse_snapshot(msg: dict[str, Any]) -> tuple[dict[str, str], dict[str, str]]:
    yes: dict[str, str] = {}
    no: dict[str, str] = {}
    for key, dest in (("yes_dollars_fp", yes), ("no_dollars_fp", no)):
        for level in msg.get(key) or []:
            if isinstance(level, list) and len(level) >= 2:
                try:
                    p, s = str(_dec(level[0]).quantize(Decimal("0.000001"))), str(
                        _dec(level[1]).quantize(Decimal("0.01"))
                    )
                    if _dec(s) > 0:
                        dest[p] = s
                except (InvalidOperation, ValueError):
                    pass
    return yes, no


def _mark_ob_dirty(master: KalshiMarketWsMaster, mt: str) -> None:
    if mt:
        master.dirty_ob.add(mt)


def _orderbook_redis_payload(master: KalshiMarketWsMaster, mt: str) -> Optional[dict[str, Any]]:
    b = master.books.get(mt)
    if not b or not b.get("valid"):
        return None
    return {
        "v": 1,
        "market_ticker": mt,
        "yes": dict(b["yes"]),
        "no": dict(b["no"]),
        "seq": b.get("last_seq"),
        "valid": True,
    }


def _flush_dirty_redis_sync(master: KalshiMarketWsMaster, ob_tickers: list[str], ticker_tickers: list[str]) -> None:
    """Batch Redis writes off the WS hot path (pipelined SET + pub/sub hints)."""
    try:
        r = _redis()
        pipe = r.pipeline()
        published_ob: list[str] = []
        for mt in ob_tickers:
            payload = _orderbook_redis_payload(master, mt)
            if not payload:
                continue
            pipe.set(_rkey_orderbook(mt), json.dumps(payload, default=str), ex=7200)
            published_ob.append(mt)
        published_ticker: list[str] = []
        for mt in ticker_tickers:
            msg = master.ticker_pending.pop(mt, None)
            if not msg:
                continue
            existing = _json_get(_rkey_ticker(mt)) or {}
            body: dict[str, Any] = {
                "market_ticker": mt,
                "yes_ask_dollars": msg.get("yes_ask_dollars") or msg.get("yes_ask"),
                "no_ask_dollars": msg.get("no_ask_dollars") or msg.get("no_ask"),
                "yes_bid_dollars": msg.get("yes_bid_dollars") or msg.get("yes_bid"),
                "no_bid_dollars": msg.get("no_bid_dollars") or msg.get("no_bid"),
                "last_price_dollars": msg.get("last_price_dollars") or msg.get("price"),
                "volume_fp": msg.get("volume_fp") or msg.get("volume"),
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
            mr = _extract_market_result(msg)
            if mr:
                body["market_result"] = mr
            elif existing.get("market_result"):
                body["market_result"] = existing["market_result"]
            elif existing.get("result"):
                body["market_result"] = existing["result"]
            pipe.set(_rkey_ticker(mt), json.dumps(body, default=str), ex=7200)
            published_ticker.append(mt)
        if published_ob or published_ticker:
            pipe.execute()
        for mt in published_ob:
            _redis_publish_push({"kind": "orderbook", "market_ticker": mt})
        for mt in published_ticker:
            _redis_publish_push({"kind": "ticker", "market_ticker": mt})
    except Exception:
        log.debug("flush_dirty_redis failed", exc_info=True)


def _publish_book(master: KalshiMarketWsMaster, mt: str) -> None:
    """Immediate publish (meta/startup); hot path uses :func:`_mark_ob_dirty`."""
    payload = _orderbook_redis_payload(master, mt)
    if not payload:
        return
    _redis_set(_rkey_orderbook(mt), payload)
    b = _book(master, mt)
    now_wall = time.time()
    b["last_book_mono"] = time.monotonic()
    b["last_book_wall_at"] = now_wall
    _redis_publish_push({"kind": "orderbook", "market_ticker": mt})


def _invalidate_book(
    master: KalshiMarketWsMaster, mt: str, reason: str, *, emit_event: bool = True
) -> None:
    b = _book(master, mt)
    b["valid"] = False
    b["resync_count"] = int(b.get("resync_count") or 0) + 1
    _redis_del(_rkey_orderbook(mt))
    if emit_event:
        _emit_event("orderbook_invalid", market_ticker=mt, reason=reason)


async def _handle_lifecycle_v2(master: KalshiMarketWsMaster, msg: dict[str, Any]) -> None:
    """Off hot path so hourly settlement bursts cannot stall WS keepalive."""
    et = str(msg.get("event_type") or "").strip()
    if et not in ("determined", "settled"):
        return
    mt = str(msg.get("market_ticker") or "").strip()
    if not mt:
        return
    mr = _extract_market_result(msg)
    if not mr:
        return
    async with master.lock:
        if not _matches_tracked_series(mt, master):
            return
        _apply_market_result_ws(master, mt, mr, source="lifecycle_ws")


def _apply_snapshot(
    master: KalshiMarketWsMaster,
    mt: str,
    msg: dict,
    seq: Optional[int],
    sid: Optional[int],
    *,
    publish: bool = True,
) -> None:
    yes, no = _parse_snapshot(msg)
    b = _book(master, mt)
    b["yes"], b["no"] = yes, no
    if seq is not None:
        seq_i = int(seq)
        last = master.ob_channel_last_seq
        master.ob_channel_last_seq = seq_i if last is None else max(last, seq_i)
        b["last_seq"] = seq_i
    if sid is not None:
        b["sid"] = int(sid)
    b["valid"] = True
    now_wall = time.time()
    b["last_book_mono"] = time.monotonic()
    b["last_book_wall_at"] = now_wall
    if publish:
        _publish_book(master, mt)
    _emit_event("orderbook_snapshot", market_ticker=mt, seq=seq)


def _consume_ob_channel_seq(master: KalshiMarketWsMaster, seq: Any) -> tuple[str, Optional[int]]:
    """Kalshi seq is monotonic per orderbook subscription, shared across all market_tickers."""
    if seq is None:
        return "skip", None
    try:
        seq_i = int(seq)
    except (TypeError, ValueError):
        return "skip", None
    last = master.ob_channel_last_seq
    if last is not None and seq_i <= last:
        return "drop", seq_i
    if last is not None and seq_i > last + 1:
        # Advance channel cursor so one hole does not gap-storm every following message.
        master.ob_channel_last_seq = seq_i
        return "gap", seq_i
    master.ob_channel_last_seq = seq_i
    return "apply", seq_i


def _schedule_channel_resync(master: KalshiMarketWsMaster, reason: str) -> None:
    now = time.monotonic()
    if master.resync_in_progress:
        return
    if now < master.channel_resync_debounce_until:
        return
    if (
        master.channel_resync_last_mono
        and now - master.channel_resync_last_mono < CHANNEL_RESYNC_MIN_INTERVAL_SEC
    ):
        return
    master.channel_resync_debounce_until = now + CHANNEL_RESYNC_DEBOUNCE_SEC
    master.channel_resync_last_mono = now
    master.channel_resync_count += 1
    tickers = sorted(master.orderbook_subscribed)
    if tickers:
        _queue_resync(master, tickers, reason)


def _apply_delta(
    master: KalshiMarketWsMaster, mt: str, msg: dict, seq: int, *, publish: bool = True
) -> None:
    b = _book(master, mt)
    if not b["valid"]:
        return
    side = str(msg.get("side") or "").lower()
    if side not in ("yes", "no"):
        return
    price = str(_dec(msg["price_dollars"]).quantize(Decimal("0.000001")))
    delta = _dec(msg.get("delta_fp"))
    cur = _dec(b[side].get(price, "0"))
    new_sz = cur + delta
    if new_sz <= 0:
        b[side].pop(price, None)
    else:
        b[side][price] = str(new_sz.quantize(Decimal("0.01")))
    b["last_seq"] = seq
    b["last_book_mono"] = time.monotonic()
    b["last_book_wall_at"] = time.time()
    if publish:
        _publish_book(master, mt)


def _extract_market_result(msg: dict[str, Any]) -> Optional[str]:
    mr = msg.get("market_result")
    if mr is None:
        mr = msg.get("result")
    if mr is None:
        return None
    s = str(mr).strip()
    return s if s else None


MAX_SETTLED_RETAIN = 3


def _is_tracked_15m_ticker(mt: str, master: KalshiMarketWsMaster) -> bool:
    for sym in master.symbols:
        if mt.startswith(_series_15m(sym) + "-"):
            return True
    return False


def _filter_15m_settled_registry(reg: dict[str, str], master: KalshiMarketWsMaster) -> dict[str, str]:
    return {k: v for k, v in reg.items() if _is_tracked_15m_ticker(str(k), master)}


def _trim_settled_registry(reg: dict[str, str], master: KalshiMarketWsMaster) -> dict[str, str]:
    reg = _filter_15m_settled_registry(reg, master)
    if len(reg) <= MAX_SETTLED_RETAIN:
        return reg
    keep = sorted(reg.items())[-MAX_SETTLED_RETAIN:]
    return dict(keep)


def _prune_non_15m_settled(master: KalshiMarketWsMaster) -> None:
    for mt in list(master.settled_tickers):
        if not _is_tracked_15m_ticker(mt, master):
            master.settled_tickers.discard(mt)


def _trim_settled_master(master: KalshiMarketWsMaster) -> None:
    _prune_non_15m_settled(master)
    ordered = sorted(mt for mt in master.settled_tickers if _is_tracked_15m_ticker(mt, master))
    if len(ordered) <= MAX_SETTLED_RETAIN:
        return
    drop = ordered[: len(ordered) - MAX_SETTLED_RETAIN]
    for mt in drop:
        master.settled_tickers.discard(mt)
        for ent in master.all_entries():
            if ent.market_ticker == mt:
                ent.market_result = None


def _persist_settled_registry(master: KalshiMarketWsMaster, mt: str, mr: str) -> None:
    if not _is_tracked_15m_ticker(mt, master):
        return
    reg = _json_get(_rkey_settled()) or {}
    if not isinstance(reg, dict):
        reg = {}
    reg = _filter_15m_settled_registry(reg, master)
    reg[mt] = mr
    reg = _trim_settled_registry(reg, master)
    _redis_set(_rkey_settled(), reg, ttl=7 * 86400)


def _sync_settled_results_into_schedule(master: KalshiMarketWsMaster) -> None:
    """Re-apply 15m market_result after REST schedule refresh (hourly lifecycle must not win)."""
    reg = _json_get(_rkey_settled()) or {}
    if not isinstance(reg, dict):
        reg = {}
    reg = _trim_settled_registry(_filter_15m_settled_registry(reg, master), master)
    if reg:
        _redis_set(_rkey_settled(), reg, ttl=7 * 86400)
    _prune_non_15m_settled(master)
    for mt, mr in reg.items():
        mt_s = str(mt).strip()
        mr_s = str(mr).strip() if mr is not None else ""
        if not mt_s or not mr_s:
            continue
        master.settled_tickers.add(mt_s)
        master.outgoing_tickers.discard(mt_s)
        for ent in master.all_entries():
            if ent.market_ticker == mt_s:
                ent.market_result = mr_s
    lmr = master.last_market_result or {}
    lmt = str(lmr.get("market_ticker") or "").strip()
    lres = str(lmr.get("market_result") or "").strip()
    if lmt and lres and _is_tracked_15m_ticker(lmt, master):
        master.settled_tickers.add(lmt)
        master.outgoing_tickers.discard(lmt)
        for ent in master.all_entries():
            if ent.market_ticker == lmt:
                ent.market_result = lres


def _rehydrate_settled(master: KalshiMarketWsMaster) -> None:
    _sync_settled_results_into_schedule(master)


def _enrich_schedule_with_settled_results(
    master: KalshiMarketWsMaster, schedule: list[dict[str, Any]]
) -> None:
    """Ensure 15m rows with known lifecycle results show settled + yes/no in meta/UI."""
    reg = _json_get(_rkey_settled()) or {}
    if not isinstance(reg, dict):
        reg = {}
    reg = _filter_15m_settled_registry(reg, master)
    lmr = master.last_market_result or {}
    lmt = str(lmr.get("market_ticker") or "").strip()
    lres = str(lmr.get("market_result") or "").strip()
    for row in schedule:
        if row.get("interval") != "15m":
            continue
        mt = str(row.get("market_ticker") or "").strip()
        if not mt:
            continue
        mr = row.get("market_result") or reg.get(mt)
        if not mr and mt == lmt:
            mr = lres or None
        if mr:
            row["market_result"] = mr
            row["phase"] = "settled"
            master.settled_tickers.add(mt)


def _matches_tracked_series(mt: str, master: KalshiMarketWsMaster) -> bool:
    if _is_tracked_15m_ticker(mt, master):
        return True
    if ONLY_15M:
        return False
    for sym in master.symbols:
        hourly = _series_hourly(sym)
        if hourly and mt.startswith(hourly + "-"):
            return True
    return False


def _apply_market_result_ws(
    master: KalshiMarketWsMaster, mt: str, mr: str, *, source: str = "ticker_ws"
) -> None:
    if mt in master.settled_tickers:
        return
    master.settled_tickers.add(mt)
    master.outgoing_tickers.discard(mt)
    for ent in master.all_entries():
        if ent.market_ticker == mt:
            ent.market_result = mr
    _persist_settled_registry(master, mt, mr)
    _trim_settled_master(master)
    master.last_market_result = {
        "market_ticker": mt,
        "market_result": mr,
        "source": source,
        "ts": datetime.now(timezone.utc).isoformat(),
    }
    _emit_event("market_result", market_ticker=mt, market_result=mr, source=source)
    if source == "lifecycle_ws" and _is_tracked_15m_ticker(mt, master):
        log.info("WS_ROLLOVER_OK market_result %s %s (lifecycle_ws)", mt, mr)
    elif source != "lifecycle_ws":
        log.info("settled %s %s (%s)", mt, mr, source)


def _maybe_apply_market_result_from_ticker(
    master: KalshiMarketWsMaster, mt: str, msg: dict[str, Any]
) -> None:
    mr = _extract_market_result(msg)
    if mr:
        _apply_market_result_ws(master, mt, mr)


def _mark_ticker_dirty(master: KalshiMarketWsMaster, mt: str, msg: dict) -> None:
    master.ticker_pending[mt] = msg
    master.dirty_ticker.add(mt)


def _next_cmd(master: KalshiMarketWsMaster) -> int:
    master.cmd_id += 1
    return master.cmd_id


async def _ws_json(master: KalshiMarketWsMaster, payload: dict) -> None:
    if master.ws_send:
        await master.ws_send.send(json.dumps(payload))


async def _get_snapshot(master: KalshiMarketWsMaster, tickers: list[str]) -> None:
    if not tickers or master.orderbook_sid is None:
        return
    for chunk in _ticker_chunks(tickers):
        await _ws_json(
            master,
            {
                "id": _next_cmd(master),
                "cmd": "update_subscription",
                "params": {
                    "sid": master.orderbook_sid,
                    "action": "get_snapshot",
                    "market_tickers": chunk,
                },
            },
        )


async def _subscription_sync(master: KalshiMarketWsMaster) -> None:
    async with master.lock:
        now = time.time()
        want_ticker, want_ob, new_ob = _lifecycle_sets(master, now)

    if master.ws_send is None:
        async with master.lock:
            master.ticker_subscribed = set()
            master.orderbook_subscribed = set()
        return

    async with master.lock:
        ending_ob = master.orderbook_subscribed - want_ob
        for mt in ending_ob:
            master.books.pop(mt, None)
            _redis_del(_rkey_orderbook(mt))
            _emit_event("cycle_cutover", market_ticker=mt)

    if master.ticker_sid is None and want_ticker:
        await _ws_json(
            master,
            {
                "id": _next_cmd(master),
                "cmd": "subscribe",
                "params": {"channels": ["ticker"], "market_tickers": sorted(want_ticker)},
            },
        )
    else:
        add = want_ticker - master.ticker_subscribed
        rem = master.ticker_subscribed - want_ticker
        if master.ticker_sid and rem:
            await _ws_json(
                master,
                {
                    "id": _next_cmd(master),
                    "cmd": "update_subscription",
                    "params": {
                        "sid": master.ticker_sid,
                        "action": "delete_markets",
                        "market_tickers": sorted(rem),
                    },
                },
            )
        if add and master.ticker_sid:
            for chunk in _ticker_chunks(add):
                await _ws_json(
                    master,
                    {
                        "id": _next_cmd(master),
                        "cmd": "update_subscription",
                        "params": {
                            "sid": master.ticker_sid,
                            "action": "add_markets",
                            "market_tickers": chunk,
                        },
                    },
                )

    if master.orderbook_sid is None and want_ob:
        for mt in want_ob:
            _book(master, mt)
        await _ws_json(
            master,
            {
                "id": _next_cmd(master),
                "cmd": "subscribe",
                "params": {
                    "channels": ["orderbook_delta"],
                    "market_tickers": sorted(want_ob),
                },
            },
        )
    else:
        add_ob = want_ob - master.orderbook_subscribed
        rem_ob = master.orderbook_subscribed - want_ob
        if add_ob and master.orderbook_sid:
            for mt in add_ob:
                _book(master, mt)
            for chunk in _ticker_chunks(add_ob):
                await _ws_json(
                    master,
                    {
                        "id": _next_cmd(master),
                        "cmd": "update_subscription",
                        "params": {
                            "sid": master.orderbook_sid,
                            "action": "add_markets",
                            "market_tickers": chunk,
                        },
                    },
                )
        if master.orderbook_sid and rem_ob:
            await _ws_json(
                master,
                {
                    "id": _next_cmd(master),
                    "cmd": "update_subscription",
                    "params": {
                        "sid": master.orderbook_sid,
                        "action": "delete_markets",
                        "market_tickers": sorted(rem_ob),
                    },
                },
            )

    async with master.lock:
        master.ticker_subscribed = want_ticker
        master.orderbook_subscribed = want_ob

    if master.lifecycle_sid is None:
        await _ws_json(
            master,
            {
                "id": _next_cmd(master),
                "cmd": "subscribe",
                "params": {"channels": ["market_lifecycle_v2"]},
            },
        )

    if master.resync_queue:
        _schedule_resync_drain(master)


def _queue_resync(master: KalshiMarketWsMaster, tickers: list[str], reason: str) -> None:
    pending = [t for t in tickers if t]
    if not pending:
        return
    master.resync_queue.append((pending, reason))


async def _flush_resync_queue(master: KalshiMarketWsMaster) -> None:
    master.resync_in_progress = True
    try:
        pending: set[str] = set()
        reasons: set[str] = set()
        while master.resync_queue:
            tickers, reason = master.resync_queue.popleft()
            pending.update(tickers)
            if reason:
                reasons.add(reason)
        if not pending:
            return
        tickers = sorted(pending)
        reason = ",".join(sorted(reasons)) or "resync"
        log.info("get_snapshot n=%s reason=%s", len(tickers), reason)
        _emit_disturbance(
            "resync_batch",
            reason=reason,
            count=len(tickers),
            sample=tickers[:8],
        )
        await _get_snapshot(master, tickers)
    finally:
        master.resync_in_progress = False


def _schedule_resync_drain(master: KalshiMarketWsMaster) -> None:
    """Run snapshot drain in background so lifecycle/meta never stall for minutes."""
    if not master.resync_queue:
        return
    task = master.resync_task
    if task is not None and not task.done():
        return
    master.resync_task = asyncio.create_task(_flush_resync_queue(master))


def _write_meta(master: KalshiMarketWsMaster) -> None:
    now = time.time()
    mono = time.monotonic()
    per_ticker = {
        mt: {
            "valid": b.get("valid"),
            "last_seq": b.get("last_seq"),
            "resync_count": b.get("resync_count"),
            "last_book_wall_at": b.get("last_book_wall_at") or None,
            "last_ticker_wall_at": b.get("last_ticker_wall_at") or None,
        }
        for mt, b in master.books.items()
    }
    schedule = [
        {
            "market_ticker": e.market_ticker,
            "symbol": e.symbol,
            "interval": e.interval,
            "phase": _phase(e, now, master),
            "open_ts": e.open_ts,
            "close_ts": e.close_ts,
            "market_result": e.market_result,
        }
        for e in master.all_entries()
    ]
    _enrich_schedule_with_settled_results(master, schedule)
    sched_15m = [r for r in schedule if r.get("interval") == "15m"]
    _redis_set(
        _rkey_meta(),
        {
            "only_15m": ONLY_15M,
            "prediscover_hours": PREDISCOVER_HOURS,
            "schedule_counts": {
                "upcoming_15m": sum(1 for r in sched_15m if r.get("phase") == "upcoming"),
                "total_15m": len(sched_15m),
            },
            "symbols": master.symbols,
            "ws_connected": master.ws_connected,
            "meta_updated_at": now,
            "ws_last_msg_age_sec": (
                None
                if not master.ws_last_msg_mono
                else round(mono - master.ws_last_msg_mono, 2)
            ),
            "ticker_sid": master.ticker_sid,
            "orderbook_sid": master.orderbook_sid,
            "ticker_subscribed": sorted(master.ticker_subscribed),
            "orderbook_subscribed": sorted(master.orderbook_subscribed),
            "outgoing_tickers": sorted(master.outgoing_tickers),
            "settled_tickers": sorted(master.settled_tickers),
            "lifecycle_sid": master.lifecycle_sid,
            "last_market_result": master.last_market_result,
            "ob_channel_seq": master.ob_channel_last_seq,
            "channel_resync_count": master.channel_resync_count,
            "resync_in_progress": master.resync_in_progress,
            "per_ticker": per_ticker,
            "schedule": schedule,
        },
        ttl=120,
    )
    _redis_publish_push({"kind": "meta"})


def _write_meta_transport_pulse(master: KalshiMarketWsMaster) -> None:
    """When the ingest lock is busy, still refresh meta TTL + ws timestamps."""
    existing = _json_get(_rkey_meta()) or {}
    if not isinstance(existing, dict):
        existing = {}
    now = time.time()
    mono = time.monotonic()
    existing["meta_updated_at"] = now
    existing["ws_connected"] = master.ws_connected
    existing["ws_last_msg_age_sec"] = (
        None
        if not master.ws_last_msg_mono
        else round(mono - master.ws_last_msg_mono, 2)
    )
    existing["resync_in_progress"] = master.resync_in_progress
    _redis_set(_rkey_meta(), existing, ttl=120)
    _redis_publish_push({"kind": "meta"})


async def _publish_coalesce_loop(master: KalshiMarketWsMaster) -> None:
    """Flush dirty books/tickers on an interval — never block WS on per-delta Redis I/O."""
    while True:
        await asyncio.sleep(PUBLISH_COALESCE_SEC)
        async with master.lock:
            ob_batch = sorted(master.dirty_ob)
            master.dirty_ob.clear()
            ticker_batch = sorted(master.dirty_ticker)
            master.dirty_ticker.clear()
        if ob_batch or ticker_batch:
            await asyncio.to_thread(_flush_dirty_redis_sync, master, ob_batch, ticker_batch)


async def _meta_heartbeat_loop(master: KalshiMarketWsMaster) -> None:
    """Publish fresh per-ticker wall times; never write frozen snapshot ages."""
    while True:
        await asyncio.sleep(META_HEARTBEAT_SEC)
        try:
            await asyncio.wait_for(master.lock.acquire(), timeout=0.25)
        except asyncio.TimeoutError:
            await asyncio.to_thread(_write_meta_transport_pulse, master)
            continue
        try:
            await asyncio.to_thread(_write_meta, master)
        finally:
            master.lock.release()


def _refresh_all_schedules_sync(master: KalshiMarketWsMaster) -> None:
    """One GET /markets per series; publish schedule as each series returns."""
    now = datetime.now(timezone.utc)
    for sym in master.symbols:
        bucket = master.schedule_by_symbol.setdefault(sym, {})
        s15 = _series_15m(sym)
        bucket["15m"] = _schedule_from_markets_poll(sym, "15m", s15, now)
        _redis_set(_rkey_schedule("15m", sym), [e.__dict__ for e in bucket["15m"]])
        log.info("%s 15m markets=%s", sym, len(bucket["15m"]))
        if not ONLY_15M:
            hourly = _series_hourly(sym)
            if hourly:
                try:
                    raw_h = _fetch_markets_for_series(hourly, now)
                except Exception as e:
                    log.warning("%s hourly GET /markets series=%s: %s", sym, hourly, e)
                    raw_h = []
                sym_u = sym.upper()
                master.hourly_markets_raw[sym_u] = raw_h
                master.hourly_ob_tickers_cache.pop(sym_u, None)
                master.hourly_ob_cache_key.pop(sym_u, None)
                bucket["hourly"] = _schedule_from_markets_poll(
                    sym, "hourly", hourly, now, markets=raw_h
                )
                _redis_set(_rkey_schedule("hourly", sym), [e.__dict__ for e in bucket["hourly"]])
                ob_n = len(
                    _hourly_live_ob_tickers(sym, bucket["hourly"], time.time(), master)
                )
                log.info(
                    "%s hourly schedule=%s raw=%s ob_sub_window=%s",
                    sym,
                    len(bucket["hourly"]),
                    len(raw_h),
                    ob_n,
                )
    _sync_settled_results_into_schedule(master)
    _emit_event("schedule_refresh", symbols=master.symbols)
    log.info("schedule refreshed symbols=%s", master.symbols)


async def _refresh_all_schedules(master: KalshiMarketWsMaster) -> None:
    await asyncio.to_thread(_refresh_all_schedules_sync, master)


async def _schedule_loop(master: KalshiMarketWsMaster) -> None:
    """REST schedule poll for pre-discovery only — not tied to quarter-hour rollover."""
    await _refresh_all_schedules(master)
    last_refresh = time.time()
    while True:
        await asyncio.sleep(5.0)
        now = time.time()
        try:
            if now - last_refresh >= SCHEDULE_REFRESH_SEC:
                await _refresh_all_schedules(master)
                last_refresh = now
        except Exception as e:
            log.exception("schedule: %s", e)


async def _lifecycle_loop(master: KalshiMarketWsMaster) -> None:
    last_periodic = 0.0
    while True:
        await asyncio.sleep(LIFECYCLE_SYNC_SEC)
        try:
            now = time.time()
            async with master.lock:
                if (
                    PERIODIC_SNAPSHOT_SEC > 0
                    and time.monotonic() - last_periodic >= PERIODIC_SNAPSHOT_SEC
                    and master.orderbook_subscribed
                    and master.orderbook_sid
                ):
                    _schedule_channel_resync(master, "periodic")
                    last_periodic = time.monotonic()
            await _subscription_sync(master)
            if _on_15m_rollover_boundary(now):
                boundary_key = _rollover_boundary_key(now)
                if master.last_rollover_boundary_key != boundary_key:
                    master.last_rollover_boundary_key = boundary_key
                    for sym in master.symbols:
                        live_mt = _clock_current_15m_ticker(sym, now)
                        prev_mt = _clock_previous_15m_ticker(sym, now)
                        _emit_event(
                            "rollover_15m",
                            symbol=sym,
                            live_ticker=live_mt,
                            outgoing_ticker=prev_mt,
                            lifecycle_sid=master.lifecycle_sid,
                        )
                        log.info(
                            "rollover_15m %s live=%s outgoing=%s lifecycle_sid=%s",
                            sym,
                            live_mt,
                            prev_mt,
                            master.lifecycle_sid,
                        )
            if _on_hour_boundary(now) and not ONLY_15M:
                hour_key = _hour_boundary_key(now)
                if master.last_hour_boundary_key != hour_key:
                    master.last_hour_boundary_key = hour_key
                    log.info("rollover_hourly boundary=%s — refresh schedule + subs", hour_key)
                    for sym in master.symbols:
                        master.hourly_ob_tickers_cache.pop(sym.upper(), None)
                        master.hourly_ob_cache_key.pop(sym.upper(), None)
                    await _refresh_all_schedules(master)
                    await _subscription_sync(master)
                    _emit_event("rollover_hourly", hour_key=hour_key, symbols=master.symbols)
            async with master.lock:
                _sync_settled_results_into_schedule(master)
                _write_meta(master)
            if master.resync_queue:
                _schedule_resync_drain(master)
        except Exception as e:
            log.exception("lifecycle: %s", e)


async def _on_ws_message(master: KalshiMarketWsMaster, raw: str) -> None:
    master.ws_last_msg_mono = time.monotonic()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return
    dtype = data.get("type")

    if dtype == "subscribed":
        async with master.lock:
            msg = data.get("msg") or {}
            ch = msg.get("channel")
            sid = msg.get("sid")
            if sid is None:
                return
            sid = int(sid)
            if ch == "ticker":
                master.ticker_sid = sid
            elif ch == "orderbook_delta":
                if master.orderbook_sid != sid:
                    master.ob_channel_last_seq = None
                master.orderbook_sid = sid
            elif ch == "market_lifecycle_v2":
                master.lifecycle_sid = sid
                log.info("subscribed market_lifecycle_v2 sid=%s", sid)
        return

    if dtype == "market_lifecycle_v2":
        asyncio.create_task(_handle_lifecycle_v2(master, data.get("msg") or {}))
        return

    if dtype == "ticker":
        msg = data.get("msg") or {}
        mt = str(msg.get("market_ticker") or "").strip()
        if mt:
            async with master.lock:
                _maybe_apply_market_result_from_ticker(master, mt, msg)
                b = _book(master, mt)
                now_wall = time.time()
                b["last_ticker_mono"] = time.monotonic()
                b["last_ticker_wall_at"] = now_wall
            _mark_ticker_dirty(master, mt, msg)
            _emit_event("ticker", market_ticker=mt)
        return

    if dtype not in ("orderbook_snapshot", "orderbook_delta"):
        return

    async with master.lock:
        msg = data.get("msg") or {}
        mt = str(msg.get("market_ticker") or "").strip()
        if not mt or mt not in master.orderbook_subscribed:
            return
        sid = int(data["sid"]) if data.get("sid") is not None else None

        if dtype == "orderbook_snapshot":
            seq = int(data["seq"]) if data.get("seq") is not None else None
            _apply_snapshot(master, mt, msg, seq, sid, publish=False)
            _mark_ob_dirty(master, mt)
        else:
            action, _seq_i = _consume_ob_channel_seq(master, data.get("seq"))
            if action == "gap":
                _invalidate_book(master, mt, f"seq_gap_{master.ob_channel_last_seq}", emit_event=False)
                _queue_resync(master, [mt], "seq_gap")
            elif action == "apply":
                _apply_delta(master, mt, msg, int(data["seq"]), publish=False)
                _mark_ob_dirty(master, mt)


async def _ws_loop(master: KalshiMarketWsMaster) -> None:
    while True:
        try:
            headers = await asyncio.to_thread(_ws_headers)
            async with websockets.connect(
                WS_URL,
                additional_headers=headers,
                ping_interval=30,
                ping_timeout=120,
                max_queue=512,
            ) as ws:
                master.ws_send = ws
                master.ws_connected = False
                master.ticker_sid = None
                master.orderbook_sid = None
                master.lifecycle_sid = None
                master.ob_channel_last_seq = None
                log.info("connected symbols=%s", master.symbols)
                await _subscription_sync(master)
                master.ws_connected = True
                await asyncio.to_thread(_write_meta, master)
                _emit_disturbance(
                    "ws_connected",
                    symbols=master.symbols,
                    ob_sub_count=len(master.orderbook_subscribed),
                )
                async for raw in ws:
                    if isinstance(raw, bytes):
                        raw = raw.decode("utf-8", errors="replace")
                    await _on_ws_message(master, raw)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.warning("ws reconnect: %s", e)
            n_subs = len(master.orderbook_subscribed)
            _emit_disturbance(
                "ws_disconnect",
                error=str(e),
                ob_sub_count=n_subs,
            )
            master.ws_connected = False
            master.ws_send = None
            master.ticker_sid = None
            master.orderbook_sid = None
            master.lifecycle_sid = None
            master.ob_channel_last_seq = None
            for mt in sorted(master.orderbook_subscribed):
                _invalidate_book(master, mt, "reconnect", emit_event=False)
            await asyncio.sleep(3)


async def _run() -> None:
    symbols = _active_symbols()
    master = KalshiMarketWsMaster(symbols=symbols)
    log.info(
        "kalshi_market_ws_master symbols=%s only_15m=%s prefix=%s",
        symbols,
        ONLY_15M,
        REDIS_PREFIX,
    )
    _refresh_all_schedules_sync(master)
    _rehydrate_settled(master)
    if master.settled_tickers:
        log.info("rehydrated %s settled tickers from redis", len(master.settled_tickers))
    await asyncio.gather(
        _schedule_loop(master),
        _lifecycle_loop(master),
        _meta_heartbeat_loop(master),
        _publish_coalesce_loop(master),
        _ws_loop(master),
        _event_flush_loop(),
    )


def main() -> None:
    _load_kalshi_credentials_from_disk()
    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        log.info("stopped")


if __name__ == "__main__":
    main()
