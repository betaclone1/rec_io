"""Hot orderbook/ticker publish registry for immediate Redis flush (HF path)."""

from __future__ import annotations

import os
import re
import threading
import time
from typing import Optional

# Short so UT arm / trade-monitor watch flips take effect before the next cold coalesce.
_REFRESH_SEC = float(os.getenv("MARKET_WATCHDOG_HOT_REGISTRY_REFRESH_SEC", "0.05"))

_CRYPTO_15M_RE = re.compile(r"^KX(BTC|ETH|SOL|XRP|DOGE)15M-", re.IGNORECASE)

_lock = threading.Lock()
_allowlist: set[str] = set()
_watched: Optional[str] = None
_ut_watched: set[str] = set()
_last_refresh_mono: float = 0.0


def hot_ticker_flush_enabled() -> bool:
    raw = os.getenv("MARKET_WATCHDOG_HOT_TICKER_FLUSH", "1").strip().lower()
    return raw in ("1", "true", "yes", "on")


def hot_crypto_15m_enabled() -> bool:
    """Always immediate-flush crypto 15m books (no coalesce / no UT-arm wait)."""
    raw = os.getenv("MARKET_WATCHDOG_HOT_CRYPTO_15M", "1").strip().lower()
    return raw in ("1", "true", "yes", "on")


def is_crypto_15m_orderbook_ticker(market_ticker: str) -> bool:
    return bool(_CRYPTO_15M_RE.match(str(market_ticker or "").strip()))


def _parse_allowlist_env() -> set[str]:
    raw = os.getenv("MARKET_WATCHDOG_HOT_ORDERBOOK_TICKERS", "").strip()
    if not raw:
        return set()
    return {t.strip() for t in raw.split(",") if t.strip()}


def refresh_hot_tickers_if_stale(*, force: bool = False) -> None:
    """Reload watch keys + env allowlist (throttled unless forced)."""
    global _allowlist, _watched, _ut_watched, _last_refresh_mono
    now = time.monotonic()
    with _lock:
        if not force and now - _last_refresh_mono < _REFRESH_SEC:
            return
        _last_refresh_mono = now
        _allowlist = _parse_allowlist_env()
        watched: Optional[str] = None
        try:
            from backend.core.trade_monitor_orderbook_watch import (
                get_trade_monitor_orderbook_watch,
            )

            watched = get_trade_monitor_orderbook_watch()
        except Exception:
            pass
        _watched = str(watched).strip() if watched else None
        ut: set[str] = set()
        try:
            from backend.core.upper_tail_orderbook_watch import (
                get_upper_tail_orderbook_watch,
            )

            ut = set(get_upper_tail_orderbook_watch())
        except Exception:
            ut = set()
        _ut_watched = ut


def is_hot_orderbook_ticker(market_ticker: str) -> bool:
    if not hot_ticker_flush_enabled():
        return False
    mt = str(market_ticker or "").strip()
    if not mt:
        return False
    if hot_crypto_15m_enabled() and is_crypto_15m_orderbook_ticker(mt):
        return True
    refresh_hot_tickers_if_stale()
    with _lock:
        if mt in _allowlist:
            return True
        if _watched and mt == _watched:
            return True
        if mt in _ut_watched:
            return True
    return False


def symbol_market_from_orderbook_ticker(market_ticker: str) -> tuple[Optional[str], Optional[str]]:
    """Map Kalshi orderbook ticker to (symbol, market) for tradeflow wake."""
    mt = str(market_ticker or "").strip().upper()
    if not mt:
        return None, None
    m15 = re.match(r"^KX(BTC|ETH|SOL|XRP|DOGE)15M-", mt)
    if m15:
        return m15.group(1), "15m"
    mh = re.match(r"^KX(BTC|ETH|SOL|XRP|DOGE)D-", mt)
    if mh:
        return mh.group(1), "hourly"
    return None, None


def is_hot_tradeflow_orderbook_ticker(market_ticker: str) -> bool:
    """Orderbook hints wake AES/ATS only for hot/watched tickers."""
    return is_hot_orderbook_ticker(market_ticker)
