"""Orderbook publish policy: immediate Redis flush is universal; wake filters are separate.

Foundation rule: every subscribed orderbook ticker publishes levels to Redis as soon as
a delta/snapshot is applied. Strategy arming (UT watch, TM watch) must never gate
whether the shared book is fresh — only whether a given consumer wakes on the hint.
"""

from __future__ import annotations

import os
import re
import threading
import time
from typing import Optional

# Short so TM / UT watch flips take effect for *wake* filters quickly.
_REFRESH_SEC = float(os.getenv("MARKET_WATCHDOG_HOT_REGISTRY_REFRESH_SEC", "0.05"))

_CRYPTO_15M_RE = re.compile(r"^KX(BTC|ETH|SOL|XRP|DOGE)15M-", re.IGNORECASE)

_lock = threading.Lock()
_allowlist: set[str] = set()
_watched: Optional[str] = None
_last_refresh_mono: float = 0.0


def immediate_orderbook_flush_enabled() -> bool:
    """System-wide: flush every dirty OB ticker immediately (default on)."""
    raw = os.getenv("MARKET_WATCHDOG_IMMEDIATE_ORDERBOOK_FLUSH", "1").strip().lower()
    return raw in ("1", "true", "yes", "on")


def hot_ticker_flush_enabled() -> bool:
    """Back-compat alias for immediate OB flush."""
    return immediate_orderbook_flush_enabled()


def hot_crypto_15m_enabled() -> bool:
    """Crypto 15m is always in the tradeflow wake set (not a flush gate)."""
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
    """Reload TM watch + env allowlist used by tradeflow/UI wake filters."""
    global _allowlist, _watched, _last_refresh_mono
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


def should_immediate_flush_orderbook(market_ticker: str) -> bool:
    """True → publish Redis levels now. Foundation path: all non-empty tickers when enabled."""
    if not immediate_orderbook_flush_enabled():
        return False
    return bool(str(market_ticker or "").strip())


def is_hot_orderbook_ticker(market_ticker: str) -> bool:
    """
    Back-compat name used by ingest flush scheduling.

    Means: immediate Redis publish for this book. Does **not** mean UT-armed.
    """
    return should_immediate_flush_orderbook(market_ticker)


def should_wake_tradeflow_on_orderbook(market_ticker: str) -> bool:
    """
    Whether AES/ATS should wake on this orderbook hint.

    Independent of Redis freshness. Live crypto 15m current cycle + allowlist
    + TM watch. Pre-subscribed *next* crypto 15m books do not wake tradeflow
    until the clock rolls (blank-slate lab lesson).
    Upper Tail uses ``upper_tail_rail_trigger`` — not tradeflow wake.
    """
    mt = str(market_ticker or "").strip()
    if not mt:
        return False
    if hot_crypto_15m_enabled() and is_crypto_15m_orderbook_ticker(mt):
        sym, market = symbol_market_from_orderbook_ticker(mt)
        if sym and market == "15m":
            try:
                from backend.core.market_watchdog.venues.kalshi.schedule import (
                    clock_current_15m_ticker,
                )

                if mt == clock_current_15m_ticker(sym, time.time()):
                    return True
            except Exception:
                # Clock helper unavailable — keep prior "any crypto 15m" wake.
                return True
        else:
            return True
    refresh_hot_tickers_if_stale()
    with _lock:
        if mt in _allowlist:
            return True
        if _watched and mt == _watched:
            return True
    return False


def is_hot_tradeflow_orderbook_ticker(market_ticker: str) -> bool:
    """Back-compat alias for tradeflow wake filter."""
    return should_wake_tradeflow_on_orderbook(market_ticker)


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
    # Commodity 15m (and any other KX*15M) — symbol from ticker prefix after KX.
    m_any = re.match(r"^KX([A-Z0-9]+)15M-", mt)
    if m_any:
        return m_any.group(1), "15m"
    return None, None
