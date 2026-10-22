"""``live_data.symbols_list.live_data_level`` is the live-feed switch for every symbol.

Levels, independent of ``category``:

- ``full`` — underlying price, internal metrics, orderbooks, and the rest of the market feed
- ``market`` — underlying price plus lean market data (public trades, lifecycle, market meta)
- ``price_only`` — underlying price only
- ``none`` — no live tracking

Callers re-read a short-lived cache. A row update moves that symbol to the new depth
on the next read. A failed refresh keeps the last successful snapshot. Until the first
successful read, every symbol is ``none``.
"""

from __future__ import annotations

import logging
import threading
import time

logger = logging.getLogger(__name__)

LEVEL_FULL = "full"
LEVEL_MARKET = "market"
LEVEL_PRICE_ONLY = "price_only"
LEVEL_NONE = "none"

LIVE_DATA_LEVELS = frozenset(
    {LEVEL_FULL, LEVEL_MARKET, LEVEL_PRICE_ONLY, LEVEL_NONE}
)
PRICE_LEVELS = frozenset({LEVEL_FULL, LEVEL_MARKET, LEVEL_PRICE_ONLY})
MARKET_LEVELS = frozenset({LEVEL_FULL, LEVEL_MARKET})

_CACHE_TTL_SEC = 5.0
_lock = threading.Lock()
_order: tuple[str, ...] = ()
_levels: dict[str, str] = {}
_loaded_mono = 0.0
_has_snapshot = False


def _load_from_db() -> tuple[tuple[str, ...], dict[str, str]]:
    from backend.core.config.database import get_system_postgresql_connection

    conn = get_system_postgresql_connection()
    if conn is None:
        raise RuntimeError("symbols_list live_data_level: no database connection")
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT UPPER(TRIM(symbol::text)), LOWER(TRIM(live_data_level::text))
                FROM live_data.symbols_list
                WHERE symbol IS NOT NULL AND TRIM(symbol::text) <> ''
                ORDER BY id
                """
            )
            rows = cur.fetchall()
    finally:
        conn.close()

    order: list[str] = []
    levels: dict[str, str] = {}
    for raw_sym, raw_level in rows:
        sym = str(raw_sym or "").strip().upper()
        if not sym or sym in levels:
            continue
        level = str(raw_level or "").strip().lower()
        if level not in LIVE_DATA_LEVELS:
            logger.error(
                "symbols_list %s live_data_level %r is not a known level; treating as none",
                sym,
                raw_level,
            )
            level = LEVEL_NONE
        levels[sym] = level
        order.append(sym)
    return tuple(order), levels


def refresh_live_data_levels(*, force: bool = False) -> dict[str, str]:
    """Return symbol → level. Refreshes from Postgres when the cache is older than 5s."""
    global _order, _levels, _loaded_mono, _has_snapshot
    now = time.monotonic()
    with _lock:
        if _has_snapshot and not force and (now - _loaded_mono) < _CACHE_TTL_SEC:
            return dict(_levels)
    try:
        order, levels = _load_from_db()
    except Exception as exc:
        with _lock:
            if _has_snapshot:
                logger.warning(
                    "symbols_list live_data_level refresh failed (%s); keeping last snapshot",
                    exc,
                )
                return dict(_levels)
        logger.error(
            "symbols_list live_data_level refresh failed (%s); no snapshot yet, every symbol is none",
            exc,
        )
        return {}
    with _lock:
        _order = order
        _levels = levels
        _loaded_mono = time.monotonic()
        _has_snapshot = True
        return dict(_levels)


def level_of(symbol: str) -> str:
    """Feed depth for one symbol. Missing row or unread catalog → ``none``."""
    sym = str(symbol or "").strip().upper()
    if not sym:
        return LEVEL_NONE
    return refresh_live_data_levels().get(sym, LEVEL_NONE)


def symbols_at_levels(*levels: str) -> tuple[str, ...]:
    """Symbols at any of ``levels``, in ``symbols_list.id`` order."""
    want = {str(level).strip().lower() for level in levels}
    refresh_live_data_levels()
    with _lock:
        return tuple(sym for sym in _order if _levels.get(sym) in want)


def full_package_symbols() -> tuple[str, ...]:
    return symbols_at_levels(LEVEL_FULL)


def market_feed_symbols() -> tuple[str, ...]:
    """Symbols that receive Kalshi market data (``full`` and ``market``)."""
    return symbols_at_levels(LEVEL_FULL, LEVEL_MARKET)


def price_feed_symbols() -> tuple[str, ...]:
    """Symbols that receive an underlying price feed."""
    return symbols_at_levels(LEVEL_FULL, LEVEL_MARKET, LEVEL_PRICE_ONLY)


def cfb_index_ids_for_price_feed() -> list[str]:
    """CF Benchmarks index ids whose symbols currently want a price feed."""
    from backend.core.cfbenchmarks_feed_cache import INDEX_TO_SYMBOL

    want = set(price_feed_symbols())
    return [iid for iid, sym in INDEX_TO_SYMBOL.items() if sym in want]


def pyth_underlyings_for_price_feed() -> list[str]:
    """Pyth underlyings whose symbols currently want a price feed."""
    from backend.core.pyth_feed_cache import SYMBOL_TO_UNDERLYING

    out: list[str] = []
    for sym in price_feed_symbols():
        und = SYMBOL_TO_UNDERLYING.get(sym)
        if und and und not in out:
            out.append(und)
    return out
