"""
Coalesced tradeflow evaluation on ``rec_io:live_state:updated`` (Phase 6).

Supervisors keep a failsafe poll; this wakes them when live_state changes.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from typing import Callable, List, Optional, Tuple

logger = logging.getLogger(__name__)

_listener_lock = threading.Lock()
_listener_thread: Optional[threading.Thread] = None


def tradeflow_live_state_trigger_enabled() -> bool:
    raw = os.getenv("TRADEFLOW_LIVE_STATE_TRIGGER", "1").strip().lower()
    return raw in ("1", "true", "yes", "on")


def tradeflow_trigger_min_interval_sec() -> float:
    raw = os.getenv("TRADEFLOW_LIVE_STATE_TRIGGER_MIN_SEC", "0.2").strip()
    try:
        return max(0.05, float(raw))
    except (TypeError, ValueError):
        return 0.2


def tradeflow_orderbook_trigger_min_interval_sec() -> float:
    raw = os.getenv("TRADEFLOW_ORDERBOOK_TRIGGER_MIN_SEC", "0.05").strip()
    try:
        return max(0.01, float(raw))
    except (TypeError, ValueError):
        return 0.05


class TradeflowLiveStateCoalescer:
    """Rate-limit evaluate callbacks per (symbol, market) or special keys."""

    def __init__(self, min_interval_sec: float) -> None:
        self._min = float(min_interval_sec)
        self._last: dict[str, float] = {}
        self._lock = threading.Lock()

    def should_fire(self, symbol: str, market: str) -> bool:
        sym = str(symbol or "").strip().upper()
        mkt = (str(market or "hourly").strip().lower()) or "hourly"
        if mkt not in ("hourly", "15m"):
            mkt = "hourly"
        if not sym:
            return False
        key = f"{sym}:{mkt}"
        now = time.monotonic()
        with self._lock:
            last = self._last.get(key, 0.0)
            if now - last < self._min:
                return False
            self._last[key] = now
            return True


def parse_tradeflow_symbol_market(payload: dict) -> List[Tuple[str, str]]:
    """Extract (symbol, market) pairs from a live_state_updated message."""
    kind = str(payload.get("kind") or "").strip()
    if kind == "orderbook":
        mt = str(payload.get("market_ticker") or "").strip()
        if not mt:
            return []
        from backend.core.orderbook_hot_publish_registry import (
            is_hot_tradeflow_orderbook_ticker,
            symbol_market_from_orderbook_ticker,
        )

        if not is_hot_tradeflow_orderbook_ticker(mt):
            return []
        sym, mkt = symbol_market_from_orderbook_ticker(mt)
        if sym and mkt:
            return [(sym, mkt)]
        return []
    key = str(payload.get("key") or "")
    parts = key.split(":")
    if len(parts) < 2:
        return []
    sym = str(parts[-1]).strip().upper()
    mkt = str(parts[-2]).strip().lower()
    out: List[Tuple[str, str]] = []
    if kind == "symbol" and sym:
        out.append((sym, "hourly"))
        out.append((sym, "15m"))
        return out
    if kind in ("market", "strike_ladder") and sym and mkt in ("hourly", "15m"):
        out.append((sym, mkt))
    return out


def start_tradeflow_live_state_listener(
    on_evaluate: Callable[[], None],
    *,
    service: str = "tradeflow",
    symbol_market_filter: Optional[Callable[[str, str], bool]] = None,
) -> bool:
    """
    Subscribe to live_state updates and invoke ``on_evaluate`` (coalesced).

    Returns False if not started (cache off, trigger disabled, or no Redis).
    """
    from backend.core.live_state_config import live_state_cache_enabled
    from backend.core.tradeflow_live_reads import tradeflow_requires_live_state

    if not live_state_cache_enabled() or not tradeflow_requires_live_state():
        return False
    if not tradeflow_live_state_trigger_enabled():
        return False

    with _listener_lock:
        global _listener_thread
        if _listener_thread is not None and _listener_thread.is_alive():
            return True

        coalescer = TradeflowLiveStateCoalescer(tradeflow_trigger_min_interval_sec())
        ob_coalescer = TradeflowLiveStateCoalescer(tradeflow_orderbook_trigger_min_interval_sec())

        def _worker() -> None:
            from backend.core.live_state_cache import UPDATED_CHANNEL, redis_client_optional

            r = redis_client_optional()
            if not r:
                logger.warning("[%s] live_state trigger: no Redis client", service)
                return
            pubsub = r.pubsub()
            pubsub.subscribe(UPDATED_CHANNEL)
            logger.info(
                "[%s] live_state trigger subscribed %s",
                service,
                UPDATED_CHANNEL,
            )
            while True:
                try:
                    msg = pubsub.get_message(
                        ignore_subscribe_messages=True,
                        timeout=1.0,
                    )
                    if not msg or msg.get("type") != "message":
                        continue
                    raw = msg.get("data")
                    if not raw:
                        continue
                    if isinstance(raw, bytes):
                        raw = raw.decode("utf-8", errors="replace")
                    payload = json.loads(raw)
                    if payload.get("type") != "live_state_updated":
                        continue

                    fired = False
                    kind = str(payload.get("kind") or "").strip()
                    # Redis active_trades pool writes use kind=active_trades (not symbol/market keys).
                    if kind == "active_trades":
                        if coalescer.should_fire("__ACTIVE_TRADES__", "all"):
                            fired = True
                    elif kind == "orderbook":
                        for sym, mkt in parse_tradeflow_symbol_market(payload):
                            if symbol_market_filter and not symbol_market_filter(
                                sym, mkt
                            ):
                                continue
                            if ob_coalescer.should_fire(sym, mkt):
                                fired = True
                    else:
                        for sym, mkt in parse_tradeflow_symbol_market(payload):
                            if symbol_market_filter and not symbol_market_filter(
                                sym, mkt
                            ):
                                continue
                            if coalescer.should_fire(sym, mkt):
                                fired = True
                    if fired:
                        try:
                            on_evaluate()
                        except Exception as exc:
                            logger.warning(
                                "[%s] live_state evaluate callback failed: %s",
                                service,
                                exc,
                            )
                except Exception as exc:
                    logger.debug("[%s] live_state trigger loop: %s", service, exc)
                    time.sleep(1.0)

        _listener_thread = threading.Thread(
            target=_worker,
            name=f"tradeflow_ls_{service}",
            daemon=True,
        )
        _listener_thread.start()
        return True
