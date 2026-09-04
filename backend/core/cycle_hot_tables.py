"""
Cycle package hot tables in ``historical_data`` (backtest capture).

Per market ticker (quoted identifiers), six tables:

  historical_data."{TICKER}_snapshot"
  historical_data."{TICKER}_deltas"
  historical_data."{TICKER}_strike_table"
  historical_data."{TICKER}_price_ring"
  historical_data."{TICKER}_metrics_ring"
  historical_data."{TICKER}_market_meta"

OB stream is high-rate (batched writer). Strike / price / metrics are 1 Hz-ish
sidecars (separate queue) so they never stall book capture.

Price + metrics fan out to registered hot tickers for the matching symbol
still inside their cycle window. Strike rows append only for tickers already
registered (OB-subscribed).

Env:
  CYCLE_HOT_PG — default on (``1``). Legacy aliases: ``BTC15M_CYCLE_HOT_PG``,
    ``TESTING_BTC15M_ORDERBOOK_CYCLE_PG``.
  CYCLE_HOT_SYMBOLS — comma list (default ``BTC,ETH``).
  CYCLE_SERIES_MAP — optional ``SYM:SERIES,...`` override (else built-in defaults).
  CYCLE_HOT_OB_QUEUE_MAX — bounded OB PG queue (default ``20000``). On full,
    enqueue drops the item (never blocks MW). Does not shed on the ingest path.
  CYCLE_HOT_OB_QUEUE_SHED — depth that triggers proactive shed on the OB PG
    writer thread only (default ``15000``). Keeps latest snapshot per ticker;
    drops queued deltas. Live Redis apply/flush must not wait on this.
"""

from __future__ import annotations

import atexit
import json
import logging
import os
import queue
import re
import threading
import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional, Set, Tuple
from zoneinfo import ZoneInfo

logger = logging.getLogger("cycle_hot")

_UTC = timezone.utc
_EST = ZoneInfo("America/New_York")
_SCHEMA = "historical_data"
_DEFAULT_HOT_SYMBOLS = ("BTC", "ETH")
# Default series ids used today; override with CYCLE_SERIES_MAP for other venues.
_DEFAULT_SERIES_BY_SYMBOL = {
    "BTC": "KXBTC15M",
    "ETH": "KXETH15M",
    "SOL": "KXSOL15M",
    "XRP": "KXXRP15M",
    "DOGE": "KXDOGE15M",
}

# Series-TIMESTAMP-suffix style tickers (current Kalshi 15m shape).
_TICKER_RE = re.compile(
    r"^([A-Z0-9]+)-(\d{2}[A-Z]{3}\d{2}\d{4})-(\d{2})$", re.IGNORECASE
)

_ddl_lock = threading.Lock()
_ensured_tables: Set[str] = set()
# Tickers whose hot tables were dropped (e.g. by cycle_packager in another process).
# Stop enqueue/write for the rest of this process lifetime so we do not recreate
# tables under an already-packaged cycle or retry forever on UndefinedTable.
_ob_skip_tickers: Set[str] = set()
_hot_tickers: Set[str] = set()
_hot_lock = threading.Lock()
_last_hot_refresh_mono = 0.0
_HOT_REFRESH_MIN_SEC = 1.0


def _ticker_key(market_ticker: str) -> str:
    return str(market_ticker or "").strip().upper()


def _is_undefined_relation(exc: BaseException) -> bool:
    """True when Postgres reports a missing relation (packager drop / stale cache)."""
    if getattr(exc, "pgcode", None) == "42P01":
        return True
    if type(exc).__name__ == "UndefinedTable":
        return True
    msg = str(exc).lower()
    return "does not exist" in msg and "relation" in msg


def _cycle_package_exists(market_ticker: str) -> bool:
    """Lazy import — cycle_packager imports this module at top level."""
    try:
        from backend.core.cycle_packager import package_path_for_ticker

        path = package_path_for_ticker(market_ticker)
        return bool(path is not None and path.exists())
    except Exception:
        return False


def _mark_ob_skip_ticker(market_ticker: str, reason: str) -> None:
    key = _ticker_key(market_ticker)
    with _ddl_lock:
        _ensured_tables.discard(key)
        _ob_skip_tickers.add(key)
    unregister_hot_ticker(market_ticker)
    logger.warning("OB cycle writer skipping %s (%s)", market_ticker, reason)


def _should_skip_ob_ticker(market_ticker: str) -> bool:
    return _ticker_key(market_ticker) in _ob_skip_tickers


def invalidate_ensured_tables(market_ticker: str) -> None:
    """Drop in-process DDL cache for ``market_ticker`` (cross-process drop recovery)."""
    with _ddl_lock:
        _ensured_tables.discard(_ticker_key(market_ticker))

# market_ticker → last snapshot seq (stamped on following deltas)
_last_snapshot_seq: Dict[str, int] = {}
_snapshot_seq_lock = threading.Lock()

# --- OB writer (high volume) ---
_ob_lock = threading.Lock()
_ob_thread: Optional[threading.Thread] = None
_ob_stop = threading.Event()
_ob_q: Optional[queue.Queue] = None
_ob_drain_done = threading.Event()

# --- Sidecar writer (strike / rings) ---
_sc_lock = threading.Lock()
_sc_thread: Optional[threading.Thread] = None
_sc_stop = threading.Event()
_sc_q: Optional[queue.Queue] = None
_sc_drain_done = threading.Event()

_enqueued = 0
_ob_dropped = 0
_ob_shed_count = 0
_last_depth_log_mono = 0.0
_last_shed_mono = 0.0

_DEFAULT_BATCH_SIZE = 200
_DEFAULT_BATCH_MS = 50.0
_DEFAULT_DRAIN_TIMEOUT_SEC = 120.0
_DEPTH_WARN = 5_000
_DEFAULT_OB_QUEUE_MAX = 20_000
_DEFAULT_OB_QUEUE_SHED = 15_000
_FLUSH_FAIL_BUDGET = 40
_SNAPSHOT_REQUEUE_MAX = 2


def _env_first(*names: str, default: str = "") -> str:
    for name in names:
        raw = os.getenv(name)
        if raw is not None and str(raw).strip() != "":
            return str(raw).strip()
    return default


def recorder_enabled() -> bool:
    raw = _env_first(
        "CYCLE_HOT_PG",
        "BTC15M_CYCLE_HOT_PG",
        "TESTING_BTC15M_ORDERBOOK_CYCLE_PG",
        default="1",
    ).lower()
    return raw not in ("0", "false", "no", "off")


def enabled_cycle_symbols() -> frozenset:
    """Symbols whose cycles are written to hot tables / packages."""
    raw = _env_first("CYCLE_HOT_SYMBOLS", "KALSHI_15M_CYCLE_HOT_SYMBOLS", default="")
    if raw:
        return frozenset(s.strip().upper() for s in raw.split(",") if s.strip())
    return frozenset(_DEFAULT_HOT_SYMBOLS)


def _series_by_symbol() -> Dict[str, str]:
    enabled = enabled_cycle_symbols()
    raw = _env_first("CYCLE_SERIES_MAP", default="")
    mapping: Dict[str, str] = {}
    if raw:
        for part in raw.split(","):
            part = part.strip()
            if not part or ":" not in part:
                continue
            sym, series = part.split(":", 1)
            sym_u = sym.strip().upper()
            series_u = series.strip().upper()
            if sym_u and series_u:
                mapping[sym_u] = series_u
    else:
        mapping = dict(_DEFAULT_SERIES_BY_SYMBOL)
    return {sym: series for sym, series in mapping.items() if sym in enabled}


def _symbol_by_series() -> Dict[str, str]:
    return {series: sym for sym, series in _series_by_symbol().items()}


def series_from_ticker(market_ticker: str) -> Optional[str]:
    m = _TICKER_RE.match(str(market_ticker or "").strip())
    if not m:
        return None
    series = m.group(1).upper()
    if series not in _symbol_by_series():
        return None
    return series


def symbol_from_cycle_ticker(market_ticker: str) -> Optional[str]:
    series = series_from_ticker(market_ticker)
    if series is None:
        return None
    return _symbol_by_series().get(series)


def is_cycle_ticker(market_ticker: str) -> bool:
    """True when ticker is an enabled cycle package candidate."""
    return symbol_from_cycle_ticker(market_ticker) is not None


def parse_cycle_ticker_end_est(market_ticker: str) -> Optional[datetime]:
    m = _TICKER_RE.match(str(market_ticker or "").strip())
    if not m:
        return None
    try:
        return datetime.strptime(m.group(2), "%y%b%d%H%M").replace(tzinfo=_EST)
    except Exception:
        return None


def cycle_window_utc(market_ticker: str) -> Optional[Tuple[datetime, datetime]]:
    """Return ``(open_utc, close_utc)`` for the cycle named by ``market_ticker``."""
    end_est = parse_cycle_ticker_end_est(market_ticker)
    if end_est is None:
        return None
    end_utc = end_est.astimezone(_UTC)
    return end_utc - timedelta(minutes=15), end_utc


def _utc_now_iso() -> str:
    return (
        datetime.now(_UTC)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def utc_iso_from_unix(ts: float | int) -> str:
    return (
        datetime.fromtimestamp(float(ts), tz=_UTC)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def snapshot_table_name(market_ticker: str) -> str:
    return f"{str(market_ticker).strip()}_snapshot"


def deltas_table_name(market_ticker: str) -> str:
    return f"{str(market_ticker).strip()}_deltas"


def strike_table_name(market_ticker: str) -> str:
    return f"{str(market_ticker).strip()}_strike_table"


def price_ring_table_name(market_ticker: str) -> str:
    return f"{str(market_ticker).strip()}_price_ring"


def metrics_ring_table_name(market_ticker: str) -> str:
    return f"{str(market_ticker).strip()}_metrics_ring"


def market_meta_table_name(market_ticker: str) -> str:
    return f"{str(market_ticker).strip()}_market_meta"


def all_table_names(market_ticker: str) -> Tuple[str, str, str, str, str, str]:
    return (
        snapshot_table_name(market_ticker),
        deltas_table_name(market_ticker),
        strike_table_name(market_ticker),
        price_ring_table_name(market_ticker),
        metrics_ring_table_name(market_ticker),
        market_meta_table_name(market_ticker),
    )


def _qi(ident: str) -> str:
    return '"' + str(ident).replace('"', '""') + '"'


def _qualified(table: str) -> str:
    return f"{_SCHEMA}.{_qi(table)}"


def _batch_size() -> int:
    try:
        return max(
            1,
            int(
                os.getenv(
                    "TESTING_BTC15M_ORDERBOOK_CYCLE_PG_BATCH",
                    str(_DEFAULT_BATCH_SIZE),
                )
            ),
        )
    except (TypeError, ValueError):
        return _DEFAULT_BATCH_SIZE


def _batch_ms() -> float:
    try:
        return max(
            1.0,
            float(
                os.getenv(
                    "TESTING_BTC15M_ORDERBOOK_CYCLE_PG_BATCH_MS",
                    str(_DEFAULT_BATCH_MS),
                )
            ),
        )
    except (TypeError, ValueError):
        return _DEFAULT_BATCH_MS


def _drain_timeout_sec() -> float:
    try:
        return max(
            1.0,
            float(
                os.getenv(
                    "TESTING_BTC15M_ORDERBOOK_CYCLE_PG_DRAIN_SEC",
                    str(_DEFAULT_DRAIN_TIMEOUT_SEC),
                )
            ),
        )
    except (TypeError, ValueError):
        return _DEFAULT_DRAIN_TIMEOUT_SEC


def _system_conn():
    from backend.core.config.database import get_system_postgresql_connection

    return get_system_postgresql_connection()


def register_hot_ticker(market_ticker: str) -> None:
    mt = str(market_ticker or "").strip()
    if not is_cycle_ticker(mt):
        return
    with _hot_lock:
        _hot_tickers.add(mt.upper())


def unregister_hot_ticker(market_ticker: str) -> None:
    with _hot_lock:
        _hot_tickers.discard(str(market_ticker or "").strip().upper())


def list_hot_tickers() -> List[str]:
    with _hot_lock:
        return sorted(_hot_tickers)


def hydrate_hot_tickers_from_db() -> int:
    """Replace in-memory hot set from PG (enabled ``KX*15M-*_deltas`` tables)."""
    global _last_hot_refresh_mono
    found = list_hot_cycle_tickers_in_db()
    with _hot_lock:
        before = set(_hot_tickers)
        _hot_tickers.clear()
        for mt in found:
            _hot_tickers.add(str(mt).strip().upper())
        _last_hot_refresh_mono = time.monotonic()
        return len(_hot_tickers) - len(before)


def refresh_hot_tickers_from_db(*, force: bool = False) -> None:
    """
    Resync hot set from DB so new cycles are visible to CFB / strike publisher
    processes that never see OB ``register_hot_ticker`` calls.

    Throttled to ~1/s unless ``force``.
    """
    global _last_hot_refresh_mono
    now = time.monotonic()
    if not force and (now - _last_hot_refresh_mono) < _HOT_REFRESH_MIN_SEC:
        return
    try:
        hydrate_hot_tickers_from_db()
    except Exception:
        pass


def _ensure_hot_set_loaded() -> None:
    """Always refresh (throttled) — do not skip when the set is non-empty."""
    refresh_hot_tickers_from_db(force=False)


def active_hot_tickers_for_ts(ts_utc_iso: str) -> List[str]:
    """Hot tickers whose cycle window contains ``ts`` (inclusive open and close).

    Inclusive close so the quarter-hour ``:00`` settlement tick is recorded on the
    ending cycle (and also on the next cycle's open when both are hot).
    """
    _ensure_hot_set_loaded()
    try:
        ts = datetime.fromisoformat(str(ts_utc_iso).replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=_UTC)
        else:
            ts = ts.astimezone(_UTC)
    except Exception:
        return list_hot_tickers()
    out: List[str] = []
    for mt in list_hot_tickers():
        win = cycle_window_utc(mt)
        if win is None:
            out.append(mt)
            continue
        open_u, close_u = win
        if open_u <= ts <= close_u:
            out.append(mt)
    return out


def _parse_ts_utc(ts_utc_iso: str) -> Optional[datetime]:
    try:
        ts = datetime.fromisoformat(str(ts_utc_iso).replace("Z", "+00:00"))
    except Exception:
        return None
    if ts.tzinfo is None:
        return ts.replace(tzinfo=_UTC)
    return ts.astimezone(_UTC)


def ensure_live_cycle_hot_for_ts(
    ts_utc_iso: str, *, symbol: Optional[str] = None
) -> None:
    """
    Ensure live cycle market(s) are registered for ``ts``.

    Price/metrics fan-out must not wait for the first OB snapshot (often a few
    seconds after cycle open). Creates empty hot tables if needed so index ticks
    from open are captured.

    When ``symbol`` is set, only that symbol is ensured; otherwise every enabled
    cycle symbol is checked.
    """
    ts = _parse_ts_utc(ts_utc_iso)
    if ts is None:
        return
    symbols = (
        (str(symbol).strip().upper(),)
        if symbol
        else tuple(sorted(enabled_cycle_symbols()))
    )
    for sym in symbols:
        if sym not in enabled_cycle_symbols():
            continue
        _ensure_live_symbol_cycle_hot_for_ts(ts, sym)


def _ensure_live_symbol_cycle_hot_for_ts(ts: datetime, symbol: str) -> None:
    try:
        from backend.core import live_state_cache

        data = live_state_cache.get_market_data(
            _env_first("CYCLE_LIVE_VENUE", default="kalshi"),
            _env_first("CYCLE_LIVE_MARKET", default="15m"),
            symbol,
        )
    except Exception as e:
        logger.debug("live_state market read for hot ensure failed %s: %s", symbol, e)
        return
    if not isinstance(data, dict):
        return
    markets = data.get("markets")
    rows: List[Any]
    if isinstance(markets, list):
        rows = markets
    elif isinstance(markets, dict):
        rows = list(markets.values())
    else:
        return
    for row in rows:
        if not isinstance(row, dict):
            continue
        mt = str(row.get("market_ticker") or row.get("ticker") or "").strip()
        if symbol_from_cycle_ticker(mt) != symbol:
            continue
        win = cycle_window_utc(mt)
        if win is None:
            continue
        open_u, close_u = win
        if not (open_u <= ts <= close_u):
            continue
        key = mt.upper()
        with _hot_lock:
            already = key in _hot_tickers
        if already:
            return
        try:
            ensure_cycle_tables(mt)
        except Exception as e:
            logger.debug("ensure live %s 15m hot failed %s: %s", symbol, mt, e)
        return


def _maybe_log_depth(q: Optional[queue.Queue], label: str) -> None:
    global _last_depth_log_mono
    if q is None:
        return
    qsize = q.qsize()
    if qsize < _DEPTH_WARN:
        return
    now = time.monotonic()
    if now - _last_depth_log_mono < 5.0:
        return
    _last_depth_log_mono = now
    logger.warning(
        "%s queue depth high qsize=%s dropped=%s shed=%s",
        label,
        qsize,
        _ob_dropped,
        _ob_shed_count,
    )


def _ob_queue_max() -> int:
    try:
        return max(1_000, int(_env_first("CYCLE_HOT_OB_QUEUE_MAX", default=str(_DEFAULT_OB_QUEUE_MAX))))
    except (TypeError, ValueError):
        return _DEFAULT_OB_QUEUE_MAX


def _ob_queue_shed_at() -> int:
    try:
        n = int(_env_first("CYCLE_HOT_OB_QUEUE_SHED", default=str(_DEFAULT_OB_QUEUE_SHED)))
    except (TypeError, ValueError):
        n = _DEFAULT_OB_QUEUE_SHED
    return max(500, min(n, _ob_queue_max()))


def _shed_ob_queue_items(items: List[Tuple[Any, ...]]) -> List[Tuple[Any, ...]]:
    """Keep latest snapshot per ticker; drop deltas/stops. Live Redis is unaffected."""
    snapshots: Dict[str, Tuple[Any, ...]] = {}
    for kind, payload in items:
        if kind == "snapshot" and isinstance(payload, tuple) and payload:
            mt = str(payload[0] or "").strip().upper()
            if mt:
                snapshots[mt] = (kind, payload)
    return list(snapshots.values())


def _drain_queue_to_list(q: queue.Queue) -> List[Tuple[Any, ...]]:
    out: List[Tuple[Any, ...]] = []
    while True:
        try:
            out.append(q.get_nowait())
        except queue.Empty:
            break
    return out


def shed_ob_cycle_queue(*, reason: str = "") -> int:
    """Discard backlog (keep one snapshot/ticker). Returns items removed.

    Must not run on the WS/ingest path. Drain does not hold ``_ob_lock`` so
    concurrent ``_ob_put`` (``put_nowait``) is never stalled by shed work.
    """
    global _ob_shed_count, _last_shed_mono
    with _ob_lock:
        q = _ob_q
    if q is None:
        return 0
    items = _drain_queue_to_list(q)
    kept = _shed_ob_queue_items(items)
    for item in kept:
        try:
            q.put_nowait(item)
        except queue.Full:
            break
    removed = max(0, len(items) - len(kept))
    if removed:
        _ob_shed_count += 1
        _last_shed_mono = time.monotonic()
        logger.warning(
            "OB cycle queue shed reason=%s removed=%s kept_snapshots=%s",
            reason or "depth",
            removed,
            len(kept),
        )
    return removed


def reset_ob_cycle_queue(*, reason: str = "") -> int:
    """Drop all pending OB cycle PG jobs (live Redis path unchanged)."""
    global _ob_shed_count, _last_shed_mono
    with _ob_lock:
        q = _ob_q
    if q is None:
        return 0
    items = _drain_queue_to_list(q)
    n = len(items)
    if n:
        _ob_shed_count += 1
        _last_shed_mono = time.monotonic()
        logger.warning(
            "OB cycle queue reset reason=%s discarded=%s",
            reason or "reset",
            n,
        )
    return n


def _maybe_shed_ob_backlog_on_writer() -> None:
    """Proactive shed from the OB PG writer only (never from ingest)."""
    q = _ob_q
    if q is None:
        return
    if q.qsize() < _ob_queue_shed_at():
        return
    now = time.monotonic()
    if now - _last_shed_mono < 2.0:
        return
    shed_ob_cycle_queue(reason="proactive_depth_writer")


def _ob_put(item: Tuple[Any, ...]) -> bool:
    """Non-blocking enqueue only — never shed/drain on the caller thread.

    On full queue, drop the item. Archive backlog pressure is handled by
    ``_maybe_shed_ob_backlog_on_writer`` so MW Redis apply/flush stays live.
    """
    global _enqueued, _ob_dropped
    q = _get_ob_queue()
    try:
        q.put_nowait(item)
        _enqueued += 1
        _maybe_log_depth(q, "OB cycle")
        return True
    except queue.Full:
        _ob_dropped += 1
        if _ob_dropped == 1 or _ob_dropped % 500 == 0:
            logger.warning(
                "OB cycle enqueue dropped (queue full) total_dropped=%s",
                _ob_dropped,
            )
        return False


# ---------------------------------------------------------------------------
# DDL
# ---------------------------------------------------------------------------


def _table_exists(cur, table: str) -> bool:
    cur.execute(
        """
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = %s AND table_name = %s
        LIMIT 1
        """,
        (_SCHEMA, table),
    )
    return cur.fetchone() is not None


def _create_snapshot_table(cur, snap: str) -> None:
    cur.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {_qualified(snap)} (
            seq BIGINT NOT NULL,
            received_at TEXT NOT NULL,
            reason TEXT,
            yes JSONB NOT NULL DEFAULT '{{}}'::jsonb,
            no JSONB NOT NULL DEFAULT '{{}}'::jsonb
        )
        """
    )
    cur.execute(
        f"""
        CREATE INDEX IF NOT EXISTS {_qi(snap + "_received_at_idx")}
        ON {_qualified(snap)} (received_at)
        """
    )


def _create_deltas_table(cur, deltas: str) -> None:
    cur.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {_qualified(deltas)} (
            seq BIGINT NOT NULL,
            received_at TEXT NOT NULL,
            side TEXT NOT NULL,
            price NUMERIC(20, 8) NOT NULL,
            delta NUMERIC(20, 8) NOT NULL,
            snapshot_seq BIGINT
        )
        """
    )
    cur.execute(
        f"""
        CREATE INDEX IF NOT EXISTS {_qi(deltas + "_snapshot_seq_idx")}
        ON {_qualified(deltas)} (snapshot_seq, seq)
        """
    )
    cur.execute(
        f"""
        CREATE INDEX IF NOT EXISTS {_qi(deltas + "_received_at_idx")}
        ON {_qualified(deltas)} (received_at)
        """
    )


def _create_strike_table(cur, name: str) -> None:
    cur.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {_qualified(name)} (
            timestamp TEXT NOT NULL,
            probability_15m NUMERIC,
            yes_prob_15m NUMERIC,
            no_prob_15m NUMERIC,
            fair_price NUMERIC
        )
        """
    )
    cur.execute(
        f"""
        CREATE INDEX IF NOT EXISTS {_qi(name + "_timestamp_idx")}
        ON {_qualified(name)} (timestamp)
        """
    )


def _create_price_ring_table(cur, name: str) -> None:
    cur.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {_qualified(name)} (
            timestamp TEXT PRIMARY KEY,
            price NUMERIC,
            avg_60s NUMERIC,
            last_60s_windowed_average_15min NUMERIC
        )
        """
    )


def _create_metrics_ring_table(cur, name: str) -> None:
    cur.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {_qualified(name)} (
            timestamp TEXT PRIMARY KEY,
            momentum_percentile NUMERIC(8, 2),
            volatility_percentile NUMERIC(8, 2),
            movement_percentile NUMERIC(8, 2),
            momentum_5s_avg NUMERIC(8, 2),
            momentum_10s_avg NUMERIC(8, 2),
            momentum_30s_avg NUMERIC(8, 2),
            momentum_1m_avg NUMERIC(8, 2),
            momentum_acceleration NUMERIC(8, 2)
        )
        """
    )


def _create_market_meta_table(cur, name: str) -> None:
    """Single-row market identity / settlement fields for the cycle package."""
    cur.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {_qualified(name)} (
            market_ticker TEXT PRIMARY KEY,
            floor_strike NUMERIC,
            volume_fp TEXT,
            market_result TEXT,
            updated_at TEXT NOT NULL
        )
        """
    )


def _upgrade_market_meta_table(cur, name: str) -> None:
    """Drop unused columns from older market_meta shapes."""
    if not _table_exists(cur, name):
        return
    for col in ("event_ticker", "market_id"):
        cur.execute(
            """
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = %s AND table_name = %s AND column_name = %s
            LIMIT 1
            """,
            (_SCHEMA, name, col),
        )
        if cur.fetchone():
            cur.execute(
                f"ALTER TABLE {_qualified(name)} DROP COLUMN IF EXISTS {_qi(col)}"
            )


def ensure_cycle_tables(
    market_ticker: str,
    conn=None,
    *,
    force: bool = False,
) -> Tuple[str, str, str, str, str, str]:
    """Create all hot tables for ``market_ticker``; register as hot.

    ``force=True`` re-runs DDL even if this process previously cached success
    (needed when another process dropped the tables via ``drop_cycle_tables``).
    """
    names = all_table_names(market_ticker)
    if not is_cycle_ticker(market_ticker):
        return names
    key = _ticker_key(market_ticker)
    if key in _ob_skip_tickers:
        return names
    register_hot_ticker(market_ticker)
    with _ddl_lock:
        if key in _ensured_tables and not force:
            return names
        own = conn is None
        c = conn or _system_conn()
        if c is None:
            return names
        try:
            with c.cursor() as cur:
                cur.execute(f"CREATE SCHEMA IF NOT EXISTS {_SCHEMA}")
                _create_snapshot_table(cur, names[0])
                _create_deltas_table(cur, names[1])
                _create_strike_table(cur, names[2])
                _create_price_ring_table(cur, names[3])
                _create_metrics_ring_table(cur, names[4])
                _create_market_meta_table(cur, names[5])
                _upgrade_market_meta_table(cur, names[5])
            c.commit()
            _ensured_tables.add(key)
        except Exception as e:
            try:
                c.rollback()
            except Exception:
                pass
            logger.warning("ensure cycle tables failed %s: %s", market_ticker, e)
        finally:
            if own:
                try:
                    c.close()
                except Exception:
                    pass
    return names


def ensure_market_meta_table(market_ticker: str, conn=None) -> str:
    """Ensure ``_market_meta`` exists even if sibling tables were created earlier."""
    name = market_meta_table_name(market_ticker)
    own = conn is None
    c = conn or _system_conn()
    if c is None:
        return name
    try:
        with c.cursor() as cur:
            cur.execute(f"CREATE SCHEMA IF NOT EXISTS {_SCHEMA}")
            _create_market_meta_table(cur, name)
            _upgrade_market_meta_table(cur, name)
        c.commit()
    except Exception as e:
        try:
            c.rollback()
        except Exception:
            pass
        logger.warning("ensure market_meta failed %s: %s", market_ticker, e)
    finally:
        if own:
            try:
                c.close()
            except Exception:
                pass
    return name


def drop_cycle_tables(market_ticker: str, conn=None) -> None:
    names = all_table_names(market_ticker)
    own = conn is None
    c = conn or _system_conn()
    if c is None:
        return
    try:
        with c.cursor() as cur:
            for n in names:
                cur.execute(f"DROP TABLE IF EXISTS {_qualified(n)}")
        c.commit()
        key = _ticker_key(market_ticker)
        with _ddl_lock:
            _ensured_tables.discard(key)
            # Same-process packager path: also stop OB writes for this ticker.
            _ob_skip_tickers.add(key)
        unregister_hot_ticker(market_ticker)
    except Exception as e:
        try:
            c.rollback()
        except Exception:
            pass
        logger.warning("drop cycle tables failed %s: %s", market_ticker, e)
    finally:
        if own:
            try:
                c.close()
            except Exception:
                pass


def list_hot_cycle_tickers_in_db(conn=None) -> List[str]:
    """Discover enabled ``KX*15M-*`` cycles that still have a ``_deltas`` table."""
    own = conn is None
    c = conn or _system_conn()
    if c is None:
        return []
    series_list = sorted(_series_by_symbol().values())
    if not series_list:
        return []
    try:
        with c.cursor() as cur:
            # Build OR of LIKE patterns for each enabled series.
            clauses = []
            params: List[Any] = [_SCHEMA]
            for series in series_list:
                clauses.append("tablename LIKE %s ESCAPE '\\'")
                params.append(f"{series}-%\\_deltas")
            cur.execute(
                f"""
                SELECT tablename FROM pg_tables
                WHERE schemaname = %s
                  AND ({' OR '.join(clauses)})
                ORDER BY 1
                """,
                params,
            )
            out = []
            for (tn,) in cur.fetchall():
                if tn.endswith("_deltas"):
                    mt = tn[: -len("_deltas")]
                    if is_cycle_ticker(mt):
                        out.append(mt)
            return out
    finally:
        if own:
            try:
                c.close()
            except Exception:
                pass


# ---------------------------------------------------------------------------
# OB enqueue / write
# ---------------------------------------------------------------------------


def _get_ob_queue() -> queue.Queue:
    global _ob_q, _ob_thread
    with _ob_lock:
        if _ob_q is None:
            _ob_q = queue.Queue(maxsize=_ob_queue_max())
        if _ob_thread is None or not _ob_thread.is_alive():
            _ob_stop.clear()
            _ob_drain_done.clear()
            _ob_thread = threading.Thread(
                target=_ob_writer_loop,
                name="cycle_ob_pg",
                daemon=True,
            )
            _ob_thread.start()
        return _ob_q


def _get_sc_queue() -> queue.Queue:
    global _sc_q, _sc_thread
    with _sc_lock:
        if _sc_q is None:
            _sc_q = queue.Queue()
        if _sc_thread is None or not _sc_thread.is_alive():
            _sc_stop.clear()
            _sc_drain_done.clear()
            _sc_thread = threading.Thread(
                target=_sc_writer_loop,
                name="cycle_sidecar_pg",
                daemon=True,
            )
            _sc_thread.start()
        return _sc_q


def drain_recorder(*, timeout_sec: Optional[float] = None) -> bool:
    """Drain OB + sidecar writers (process shutdown only)."""
    if timeout_sec is None:
        timeout_sec = _drain_timeout_sec()
    deadline = time.monotonic() + timeout_sec
    ok_ob = _drain_one(
        _ob_lock,
        "_ob",
        timeout_sec=max(0.1, deadline - time.monotonic()),
    )
    ok_sc = _drain_one(
        _sc_lock,
        "_sc",
        timeout_sec=max(0.1, deadline - time.monotonic()),
    )
    return ok_ob and ok_sc


def _drain_one(lock: threading.Lock, which: str, *, timeout_sec: float) -> bool:
    global _ob_thread, _ob_q, _sc_thread, _sc_q
    with lock:
        if which == "_ob":
            t, q, stop, done = _ob_thread, _ob_q, _ob_stop, _ob_drain_done
        else:
            t, q, stop, done = _sc_thread, _sc_q, _sc_stop, _sc_drain_done
    if t is None or not t.is_alive():
        return True
    logger.info("cycle %s drain start qsize=%s", which, q.qsize() if q else 0)
    done.clear()
    stop.set()
    if q is not None:
        q.put(("stop", None))
    ok = done.wait(timeout=timeout_sec)
    t.join(timeout=1.0)
    with lock:
        if which == "_ob":
            if _ob_thread is t:
                _ob_thread = None
                _ob_q = None
        else:
            if _sc_thread is t:
                _sc_thread = None
                _sc_q = None
    return ok


def shutdown_recorder_executor() -> None:
    drain_recorder()


atexit.register(shutdown_recorder_executor)


def _dec(v: Any) -> Optional[Decimal]:
    from backend.core.kalshi_market_normalize import decimal_from_api_number

    return decimal_from_api_number(v)


def _floor_strike_from_live_state(market_ticker: str) -> Optional[Decimal]:
    """Kalshi ``floor_strike`` from live_state market (exact API digits; not ladder strike)."""
    mt = str(market_ticker or "").strip().upper()
    if not mt:
        return None
    symbol = symbol_from_cycle_ticker(mt)
    if symbol is None:
        return None
    try:
        from backend.core import live_state_cache

        data = live_state_cache.get_market_data(
            _env_first("CYCLE_LIVE_VENUE", default="kalshi"),
            _env_first("CYCLE_LIVE_MARKET", default="15m"),
            symbol,
        )
    except Exception as e:
        logger.debug("live_state market read failed for floor_strike %s: %s", mt, e)
        return None
    if not isinstance(data, dict):
        return None
    markets = data.get("markets")
    rows: List[Any]
    if isinstance(markets, list):
        rows = markets
    elif isinstance(markets, dict):
        rows = list(markets.values())
    else:
        return None
    for row in rows:
        if not isinstance(row, dict):
            continue
        row_mt = str(row.get("market_ticker") or row.get("ticker") or "").strip().upper()
        if row_mt != mt:
            continue
        # Prefer API floor_strike; do not use display/ladder integer ``strike``.
        return _dec(row.get("floor_strike"))
    return None


def enqueue_snapshot(
    market_ticker: str,
    *,
    yes: Dict[str, str],
    no: Dict[str, str],
    seq: Optional[int],
    reason: str = "snapshot",
    sid: Optional[int] = None,
) -> None:
    del sid
    if not recorder_enabled() or not is_cycle_ticker(market_ticker):
        return
    if _should_skip_ob_ticker(market_ticker):
        return
    if seq is None:
        return
    try:
        seq_i = int(seq)
    except (TypeError, ValueError):
        return
    mt = str(market_ticker).strip()
    received_at = _utc_now_iso()
    with _snapshot_seq_lock:
        _last_snapshot_seq[mt.upper()] = seq_i
    try:
        _ob_put(
            ("snapshot", (mt, dict(yes or {}), dict(no or {}), seq_i, reason, received_at))
        )
    except Exception as e:
        logger.warning("OB cycle snapshot enqueue failed %s: %s", mt, e)


def enqueue_delta(
    market_ticker: str,
    *,
    side: str,
    price: str,
    delta: Any,
    seq: Optional[int],
    sid: Optional[int] = None,
) -> None:
    del sid
    if not recorder_enabled() or not is_cycle_ticker(market_ticker):
        return
    if _should_skip_ob_ticker(market_ticker):
        return
    if seq is None:
        return
    try:
        seq_i = int(seq)
    except (TypeError, ValueError):
        return
    mt = str(market_ticker).strip()
    side_l = str(side or "").strip().lower()
    if side_l not in ("yes", "no"):
        return
    d = _dec(delta)
    p = _dec(price)
    if d is None or p is None:
        return
    received_at = _utc_now_iso()
    with _snapshot_seq_lock:
        snap_seq = _last_snapshot_seq.get(mt.upper())
    try:
        _ob_put(("delta", (mt, side_l, p, d, seq_i, snap_seq, received_at)))
    except Exception as e:
        logger.warning("OB cycle delta enqueue failed %s: %s", mt, e)


def enqueue_strike_row(
    market_ticker: str,
    *,
    timestamp_utc: str,
    probability_15m: Any = None,
    yes_prob_15m: Any = None,
    no_prob_15m: Any = None,
    fair_price: Any = None,
) -> None:
    """Append irreversible strike fields for an already-registered hot ticker."""
    if not recorder_enabled() or not is_cycle_ticker(market_ticker):
        return
    mt = str(market_ticker).strip().upper()
    _ensure_hot_set_loaded()
    with _hot_lock:
        if mt not in _hot_tickers:
            return
    ts = str(timestamp_utc or "").strip()
    if not ts:
        return
    try:
        _get_sc_queue().put(
            (
                "strike",
                (
                    mt,
                    ts,
                    _dec(probability_15m),
                    _dec(yes_prob_15m),
                    _dec(no_prob_15m),
                    _dec(fair_price),
                ),
            )
        )
    except Exception as e:
        logger.debug("strike cycle enqueue failed %s: %s", mt, e)


def enqueue_strike_ladder_rows(
    *,
    wall_second: int,
    ladder: Dict[str, Any],
    market: str = "15m",
    symbol: str = "BTC",
) -> None:
    """From strike snapshot publish: append irreversible cols for hot 15m tickers."""
    if not recorder_enabled():
        return
    if str(market or "").strip().lower() != "15m":
        return
    sym = str(symbol or "").strip().upper()
    if sym not in enabled_cycle_symbols():
        return
    if not isinstance(ladder, dict):
        return
    ts = utc_iso_from_unix(wall_second)
    for sd in ladder.get("strikes") or []:
        if not isinstance(sd, dict):
            continue
        mt = str(sd.get("ticker") or "").strip()
        if not mt:
            continue
        if symbol_from_cycle_ticker(mt) != sym:
            continue
        enqueue_strike_row(
            mt,
            timestamp_utc=ts,
            # live_state ladder uses ``probability`` for the active market leg
            probability_15m=sd.get("probability_15m", sd.get("probability")),
            yes_prob_15m=sd.get("yes_prob_15m"),
            no_prob_15m=sd.get("no_prob_15m"),
            fair_price=sd.get("fair_price"),
        )
        # Ladder ``strike`` is integer-normalized — not Kalshi floor_strike.
        enqueue_market_meta_update(
            mt,
            floor_strike=_floor_strike_from_live_state(mt),
            volume_fp=sd.get("volume_fp"),
        )


def enqueue_market_meta_update(
    market_ticker: str,
    *,
    floor_strike: Any = None,
    volume_fp: Any = None,
    market_result: Any = None,
) -> None:
    """Upsert irreversible / identity market fields for a hot cycle ticker."""
    if not recorder_enabled() or not is_cycle_ticker(market_ticker):
        return
    mt = str(market_ticker).strip().upper()
    _ensure_hot_set_loaded()
    with _hot_lock:
        hot = mt in _hot_tickers
    if not hot:
        # Settlement / late identity can arrive after unregister if PG tables remain.
        if mt not in {t.upper() for t in list_hot_cycle_tickers_in_db()}:
            return
    try:
        _get_sc_queue().put(
            (
                "market_meta",
                (
                    mt,
                    _dec(floor_strike),
                    str(volume_fp).strip() if volume_fp not in (None, "") else None,
                    str(market_result).strip().lower()
                    if market_result not in (None, "")
                    else None,
                    _utc_now_iso(),
                ),
            )
        )
    except Exception as e:
        logger.debug("market_meta enqueue failed %s: %s", mt, e)


def enqueue_cycle_price_metrics(
    *,
    symbol: str,
    timestamp_utc: str,
    price: Any = None,
    avg_60s: Any = None,
    last_60s_windowed_average_15min: Any = None,
    metrics: Optional[Dict[str, Any]] = None,
) -> None:
    """Fan CFB tick into per-ticker price/metrics rings for matching hot cycles."""
    if not recorder_enabled():
        return
    sym = str(symbol or "").strip().upper()
    if sym not in enabled_cycle_symbols():
        return
    ts = str(timestamp_utc or "").strip()
    if not ts:
        return
    # Cover quarter-hour open even before first OB snapshot registers the ticker.
    ensure_live_cycle_hot_for_ts(ts, symbol=sym)
    targets = [
        mt
        for mt in active_hot_tickers_for_ts(ts)
        if symbol_from_cycle_ticker(mt) == sym
    ]
    if not targets:
        return
    p = _dec(price)
    a60 = _dec(avg_60s)
    a15 = _dec(last_60s_windowed_average_15min)
    m = metrics if isinstance(metrics, dict) else {}

    def _m(key: str) -> Optional[Decimal]:
        return _dec(m.get(key))

    met_tuple = (
        _m("momentum_percentile"),
        _m("volatility_percentile"),
        _m("movement_percentile"),
        _m("momentum_5s_avg"),
        _m("momentum_10s_avg"),
        _m("momentum_30s_avg"),
        _m("momentum_1m_avg"),
        _m("momentum_acceleration"),
    )
    try:
        q = _get_sc_queue()
        for mt in targets:
            if p is not None:
                q.put(("price", (mt, ts, p, a60, a15)))
            if any(v is not None for v in met_tuple):
                q.put(("metrics", (mt, ts) + met_tuple))
    except Exception as e:
        logger.debug("price/metrics cycle enqueue failed: %s", e)


def _write_snapshot(
    conn,
    market_ticker: str,
    yes: Dict[str, str],
    no: Dict[str, str],
    seq: int,
    reason: str,
    received_at: str,
) -> None:
    if _should_skip_ob_ticker(market_ticker):
        return
    snap_tbl, *_ = ensure_cycle_tables(market_ticker, conn)
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                INSERT INTO {_qualified(snap_tbl)}
                    (seq, received_at, reason, yes, no)
                VALUES (%s, %s, %s, %s::jsonb, %s::jsonb)
                """,
                (seq, received_at, reason, json.dumps(yes), json.dumps(no)),
            )
        conn.commit()
    except Exception as e:
        if not _is_undefined_relation(e):
            raise
        try:
            conn.rollback()
        except Exception:
            pass
        invalidate_ensured_tables(market_ticker)
        if _cycle_package_exists(market_ticker):
            _mark_ob_skip_ticker(market_ticker, "snapshot table missing after package")
            return
        ensure_cycle_tables(market_ticker, conn, force=True)
        with conn.cursor() as cur:
            cur.execute(
                f"""
                INSERT INTO {_qualified(snap_tbl)}
                    (seq, received_at, reason, yes, no)
                VALUES (%s, %s, %s, %s::jsonb, %s::jsonb)
                """,
                (seq, received_at, reason, json.dumps(yes), json.dumps(no)),
            )
        conn.commit()
    with _snapshot_seq_lock:
        _last_snapshot_seq[market_ticker.upper()] = int(seq)


def _insert_delta_group(conn, mt: str, group: List[Tuple[Any, ...]]) -> None:
    names = ensure_cycle_tables(mt, conn)
    deltas_tbl = names[1]
    params = [
        (seq, received_at, side, price, delta, snap_seq)
        for (_mt, side, price, delta, seq, snap_seq, received_at) in group
    ]
    q = f"""
        INSERT INTO {_qualified(deltas_tbl)}
            (seq, received_at, side, price, delta, snapshot_seq)
        VALUES (%s, %s, %s, %s, %s, %s)
        """
    with conn.cursor() as cur:
        cur.executemany(q, params)
    conn.commit()


def _flush_delta_batch(conn, rows: List[Tuple[Any, ...]]) -> None:
    if not rows:
        return
    by_ticker: Dict[str, List[Tuple[Any, ...]]] = {}
    for r in rows:
        by_ticker.setdefault(r[0], []).append(r)
    for mt, group in by_ticker.items():
        if _should_skip_ob_ticker(mt):
            continue
        try:
            _insert_delta_group(conn, mt, group)
        except Exception as e:
            if not _is_undefined_relation(e):
                raise
            try:
                conn.rollback()
            except Exception:
                pass
            invalidate_ensured_tables(mt)
            if _cycle_package_exists(mt):
                _mark_ob_skip_ticker(mt, "deltas table missing after package")
                continue
            try:
                ensure_cycle_tables(mt, conn, force=True)
                _insert_delta_group(conn, mt, group)
            except Exception as e2:
                try:
                    conn.rollback()
                except Exception:
                    pass
                if _is_undefined_relation(e2):
                    _mark_ob_skip_ticker(mt, f"deltas table still missing: {e2}")
                    continue
                raise


def _ob_writer_loop() -> None:
    conn = None
    pending: List[Tuple[Any, ...]] = []
    batch_n = _batch_size()
    batch_s = _batch_ms() / 1000.0
    last_flush = time.monotonic()
    stop_seen = False

    def _close_conn() -> None:
        nonlocal conn
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
            conn = None

    def _conn():
        nonlocal conn
        if conn is None or getattr(conn, "closed", 1):
            conn = _system_conn()
        return conn

    def _flush() -> bool:
        nonlocal pending, last_flush
        if not pending:
            last_flush = time.monotonic()
            return True
        c = _conn()
        if c is None:
            time.sleep(0.25)
            return False
        try:
            _flush_delta_batch(c, pending)
            pending = []
            last_flush = time.monotonic()
            return True
        except Exception as e:
            try:
                c.rollback()
            except Exception:
                pass
            logger.warning("OB cycle delta batch write failed (will retry): %s", e)
            _close_conn()
            time.sleep(0.25)
            return False

    def _flush_or_drop() -> None:
        nonlocal pending
        for _ in range(_FLUSH_FAIL_BUDGET):
            if _flush():
                return
        if pending:
            logger.warning(
                "OB cycle dropping %s pending deltas after flush budget",
                len(pending),
            )
            pending = []

    def _handle_snapshot(payload: Tuple[Any, ...]) -> None:
        _flush_or_drop()
        write_payload = payload[:6] if len(payload) > 6 else payload
        mt = write_payload[0] if write_payload else ""
        if _should_skip_ob_ticker(str(mt)):
            return
        c = _conn()
        if c is None:
            # Do not requeue forever — archive miss is preferable to queue bomb.
            logger.warning("OB cycle snapshot skipped (no PG conn) %s", mt)
            time.sleep(0.25)
            return
        try:
            _write_snapshot(c, *write_payload)
        except Exception as e:
            try:
                c.rollback()
            except Exception:
                pass
            if _is_undefined_relation(e):
                invalidate_ensured_tables(str(mt))
                if _cycle_package_exists(str(mt)):
                    _mark_ob_skip_ticker(str(mt), "snapshot missing after package")
                    return
                try:
                    ensure_cycle_tables(str(mt), c, force=True)
                    _write_snapshot(c, *write_payload)
                    return
                except Exception as e2:
                    try:
                        c.rollback()
                    except Exception:
                        pass
                    if _is_undefined_relation(e2):
                        _mark_ob_skip_ticker(str(mt), f"snapshot still missing: {e2}")
                        return
                    e = e2
            logger.warning("OB cycle snapshot write failed %s: %s", mt, e)
            _close_conn()
            attempts = 0
            if len(payload) >= 7:
                try:
                    attempts = int(payload[6])
                except (TypeError, ValueError):
                    attempts = 0
            if attempts < _SNAPSHOT_REQUEUE_MAX and q is not None:
                _ob_put(("snapshot", tuple(write_payload) + (attempts + 1,)))
            time.sleep(0.25)

    def _handle_item(kind: str, payload: Any) -> None:
        nonlocal stop_seen
        if kind == "stop":
            stop_seen = True
            return
        if kind == "snapshot":
            _handle_snapshot(payload)
            return
        if kind == "delta":
            mt = payload[0] if payload else ""
            if _should_skip_ob_ticker(str(mt)):
                return
            pending.append(payload)
            if len(pending) >= batch_n:
                _flush()

    q = _ob_q
    try:
        while True:
            draining = stop_seen or _ob_stop.is_set()
            if not draining:
                _maybe_shed_ob_backlog_on_writer()
            if draining:
                qsize = q.qsize() if q is not None else 0
                if qsize == 0 and not pending:
                    break
                if pending and qsize == 0:
                    _flush()
                    continue
                try:
                    item = q.get_nowait() if q is not None else None
                except queue.Empty:
                    item = None
                if item is not None:
                    _handle_item(*item)
                continue

            timeout = max(0.001, batch_s - (time.monotonic() - last_flush))
            try:
                item = q.get(timeout=timeout) if q is not None else None
            except queue.Empty:
                item = None
            if item is not None:
                _handle_item(*item)
            if pending and (time.monotonic() - last_flush) >= batch_s:
                _flush()
    finally:
        deadline = time.monotonic() + 30.0
        while pending and time.monotonic() < deadline:
            if _flush():
                break
        _close_conn()
        _ob_drain_done.set()


def _sc_writer_loop() -> None:
    conn = None
    stop_seen = False

    def _close_conn() -> None:
        nonlocal conn
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
            conn = None

    def _conn():
        nonlocal conn
        if conn is None or getattr(conn, "closed", 1):
            conn = _system_conn()
        return conn

    def _handle(kind: str, payload: Any) -> None:
        nonlocal stop_seen
        if kind == "stop":
            stop_seen = True
            return
        c = _conn()
        if c is None:
            time.sleep(0.25)
            if q is not None:
                q.put((kind, payload))
            return
        try:
            if kind == "strike":
                mt, ts, p15, yp, np_, fp = payload
                names = ensure_cycle_tables(mt, c)
                with c.cursor() as cur:
                    cur.execute(
                        f"""
                        INSERT INTO {_qualified(names[2])}
                            (timestamp, probability_15m, yes_prob_15m, no_prob_15m, fair_price)
                        VALUES (%s, %s, %s, %s, %s)
                        """,
                        (ts, p15, yp, np_, fp),
                    )
                c.commit()
            elif kind == "price":
                mt, ts, price, a60, a15 = payload
                names = ensure_cycle_tables(mt, c)
                with c.cursor() as cur:
                    cur.execute(
                        f"""
                        INSERT INTO {_qualified(names[3])}
                            (timestamp, price, avg_60s, last_60s_windowed_average_15min)
                        VALUES (%s, %s, %s, %s)
                        ON CONFLICT (timestamp) DO UPDATE SET
                            price = EXCLUDED.price,
                            avg_60s = EXCLUDED.avg_60s,
                            last_60s_windowed_average_15min =
                                EXCLUDED.last_60s_windowed_average_15min
                        """,
                        (ts, price, a60, a15),
                    )
                c.commit()
            elif kind == "metrics":
                (
                    mt,
                    ts,
                    mom_p,
                    vol_p,
                    mov_p,
                    m5,
                    m10,
                    m30,
                    m1,
                    acc,
                ) = payload
                names = ensure_cycle_tables(mt, c)
                with c.cursor() as cur:
                    cur.execute(
                        f"""
                        INSERT INTO {_qualified(names[4])}
                            (timestamp, momentum_percentile, volatility_percentile,
                             movement_percentile, momentum_5s_avg, momentum_10s_avg,
                             momentum_30s_avg, momentum_1m_avg, momentum_acceleration)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (timestamp) DO UPDATE SET
                            momentum_percentile = EXCLUDED.momentum_percentile,
                            volatility_percentile = EXCLUDED.volatility_percentile,
                            movement_percentile = EXCLUDED.movement_percentile,
                            momentum_5s_avg = EXCLUDED.momentum_5s_avg,
                            momentum_10s_avg = EXCLUDED.momentum_10s_avg,
                            momentum_30s_avg = EXCLUDED.momentum_30s_avg,
                            momentum_1m_avg = EXCLUDED.momentum_1m_avg,
                            momentum_acceleration = EXCLUDED.momentum_acceleration
                        """,
                        (ts, mom_p, vol_p, mov_p, m5, m10, m30, m1, acc),
                    )
                c.commit()
            elif kind == "market_meta":
                (
                    mt,
                    floor_strike,
                    volume_fp,
                    market_result,
                    updated_at,
                ) = payload
                ensure_market_meta_table(mt, c)
                ensure_cycle_tables(mt, c)
                meta_tbl = market_meta_table_name(mt)
                with c.cursor() as cur:
                    cur.execute(
                        f"""
                        INSERT INTO {_qualified(meta_tbl)}
                            (market_ticker, floor_strike, volume_fp, market_result, updated_at)
                        VALUES (%s, %s, %s, %s, %s)
                        ON CONFLICT (market_ticker) DO UPDATE SET
                            floor_strike = COALESCE(
                                EXCLUDED.floor_strike, {_qualified(meta_tbl)}.floor_strike
                            ),
                            volume_fp = COALESCE(
                                EXCLUDED.volume_fp, {_qualified(meta_tbl)}.volume_fp
                            ),
                            market_result = COALESCE(
                                EXCLUDED.market_result, {_qualified(meta_tbl)}.market_result
                            ),
                            updated_at = EXCLUDED.updated_at
                        """,
                        (
                            mt,
                            floor_strike,
                            volume_fp,
                            market_result,
                            updated_at,
                        ),
                    )
                c.commit()
        except Exception as e:
            try:
                c.rollback()
            except Exception:
                pass
            logger.warning("sidecar write failed kind=%s: %s", kind, e)
            _close_conn()

    q = _sc_q
    try:
        while True:
            draining = stop_seen or _sc_stop.is_set()
            if draining:
                if q is None or q.qsize() == 0:
                    break
                try:
                    item = q.get_nowait()
                except queue.Empty:
                    break
                _handle(*item)
                continue
            try:
                item = q.get(timeout=0.5) if q is not None else None
            except queue.Empty:
                item = None
            if item is not None:
                _handle(*item)
    finally:
        _close_conn()
        _sc_drain_done.set()
