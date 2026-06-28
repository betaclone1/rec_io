"""
Tradeflow operational reads from Redis ``live_state`` (no PG fallback when cache is on).

See docs/live-data-architecture/parity_validation_checklist.md (tradeflow contract).
"""

from __future__ import annotations

import logging
import os
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from backend.core import live_state_cache
from backend.core.exchange_ids import DEFAULT_EXCHANGE, normalize_exchange
from backend.core.live_state_config import live_state_cache_enabled
from backend.core.live_state_read_helpers import strike_ladder_from_cache
from backend.core.time_eastern import EST

logger = logging.getLogger(__name__)

_last_warn_mono: Dict[str, float] = {}
_WARN_INTERVAL_SEC = 30.0


def tradeflow_live_state_max_age_sec() -> float:
    raw = os.getenv("TRADEFLOW_LIVE_STATE_MAX_AGE_SEC", "").strip()
    if raw:
        try:
            return max(0.5, float(raw))
        except (TypeError, ValueError):
            pass
    raw2 = os.getenv("REC_STRIKE_SNAPSHOT_MAX_AGE_SEC", "3").strip()
    try:
        return max(0.5, float(raw2))
    except (TypeError, ValueError):
        return 3.0


def tradeflow_requires_live_state() -> bool:
    return live_state_cache_enabled()


def _log_throttled(key: str, msg: str, *args: Any) -> None:
    now = time.monotonic()
    last = _last_warn_mono.get(key, 0.0)
    if now - last < _WARN_INTERVAL_SEC:
        return
    _last_warn_mono[key] = now
    logger.warning(msg, *args)


def _envelope_age_sec(envelope: Optional[Dict[str, Any]]) -> float:
    if not envelope:
        return float("inf")
    return live_state_cache.cache_age_sec(envelope)


def _check_fresh(
    kind: str,
    key: str,
    envelope: Optional[Dict[str, Any]],
    *,
    max_age_sec: Optional[float] = None,
) -> Tuple[bool, str, float]:
    if not live_state_cache_enabled():
        return False, "cache_disabled", float("inf")
    if not envelope:
        _log_throttled(
            f"{kind}:{key}",
            "stale_live_state miss %s key=%s",
            kind,
            key,
        )
        return False, "miss", float("inf")
    age = _envelope_age_sec(envelope)
    limit = max_age_sec if max_age_sec is not None else tradeflow_live_state_max_age_sec()
    if age > limit:
        _log_throttled(
            f"{kind}:{key}",
            "stale_live_state %s key=%s age=%.2fs max=%.2fs",
            kind,
            key,
            age,
            limit,
        )
        return False, "stale", age
    return True, "ok", age


def symbol_metrics(
    symbol: str,
    *,
    max_age_sec: Optional[float] = None,
) -> Optional[Dict[str, Any]]:
    sym = str(symbol or "").strip().upper()
    if not sym or not live_state_cache_enabled():
        return None
    env = live_state_cache.get_symbol(sym)
    ok, _reason, _age = _check_fresh("symbol", sym, env, max_age_sec=max_age_sec)
    if not ok:
        return None
    data = (env or {}).get("data") if env else None
    if not isinstance(data, dict):
        return None
    return dict(data)


def symbol_spot_price(
    symbol: str,
    *,
    max_age_sec: Optional[float] = None,
) -> Optional[float]:
    m = symbol_metrics(symbol, max_age_sec=max_age_sec)
    if not m:
        return None
    for key in ("price", "one_minute_avg"):
        v = m.get(key)
        if v is None:
            continue
        try:
            return float(v)
        except (TypeError, ValueError):
            continue
    return None


def symbol_spot_price_for_monitoring(
    symbol: str,
    *,
    prefer_max_age_sec: Optional[float] = None,
    allow_stale_max_age_sec: float = 180.0,
) -> Optional[float]:
    sym = str(symbol or "").strip().upper()
    if not sym:
        return None
    fresh = symbol_spot_price(sym, max_age_sec=prefer_max_age_sec)
    if fresh is not None:
        return fresh
    if not live_state_cache_enabled():
        return None
    env = live_state_cache.get_symbol(sym)
    if not env:
        return None
    age = _envelope_age_sec(env)
    if age > allow_stale_max_age_sec:
        return None
    data = env.get("data")
    if not isinstance(data, dict):
        return None
    for key in ("price", "one_minute_avg"):
        v = data.get(key)
        if v is None:
            continue
        try:
            return float(v)
        except (TypeError, ValueError):
            continue
    return None


def strike_ladder(
    symbol: str,
    market: str,
    exchange: Optional[str] = None,
    *,
    max_age_sec: Optional[float] = None,
) -> Optional[Dict[str, Any]]:
    ex = normalize_exchange(exchange or DEFAULT_EXCHANGE)
    sym = str(symbol or "").strip().upper()
    mkt = (market or "hourly").strip().lower()
    if mkt not in ("hourly", "15m"):
        mkt = "hourly"
    if not sym:
        return None
    if not live_state_cache_enabled():
        from backend.core.strike_ladder_fetch import fetch_strike_ladder_prefer_snapshot

        return fetch_strike_ladder_prefer_snapshot(sym, mkt, ex)
    env = live_state_cache.get_strike_ladder(ex, mkt, sym)
    ok, _reason, _age = _check_fresh(
        "strike_ladder",
        f"{ex}:{mkt}:{sym}",
        env,
        max_age_sec=max_age_sec,
    )
    if not ok:
        return None
    ladder = strike_ladder_from_cache(ex, mkt, sym)
    if not ladder:
        return None
    return ladder


def ttc_seconds_from_ladder(
    ladder: Optional[Dict[str, Any]],
    market: str,
) -> Optional[int]:
    if not ladder:
        return None
    mkt = (market or "hourly").strip().lower()
    for key in ("ttc", "ttc_seconds"):
        v = ladder.get(key)
        if v is None:
            continue
        try:
            return int(v)
        except (TypeError, ValueError):
            continue
    if mkt == "15m":
        v = ladder.get("ttc_15m")
    else:
        v = ladder.get("ttc_hourly")
    if v is None:
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _market_snapshot_from_strike_ladder(ladder: Dict[str, Any]) -> Dict[str, Any]:
    """Tradeflow quote snapshot from OB-priced strike ladder rows (AES/ATS/UI contract)."""
    markets: List[Dict[str, Any]] = []
    event_ticker = ladder.get("event_ticker")
    for row in ladder.get("strikes") or []:
        if not isinstance(row, dict):
            continue
        markets.append(
            {
                "ticker": row.get("ticker"),
                "yes_ask_dollars": row.get("yes_ask_dollars"),
                "no_ask_dollars": row.get("no_ask_dollars"),
                "volume": row.get("volume_fp"),
                "event_ticker": row.get("event_ticker") or event_ticker,
                "strike": row.get("strike"),
            }
        )
    return {
        "markets": markets,
        "timestamp": datetime.now(EST).isoformat(),
        "event_ticker": event_ticker,
        "source": "strike_ladder",
    }


def kalshi_market_snapshot(
    symbol: str,
    market: str,
    exchange: Optional[str] = None,
    *,
    max_age_sec: Optional[float] = None,
) -> Optional[Dict[str, Any]]:
    """
    Per-contract yes/no asks for tradeflow (ATS marks, closing price).

    When ``live_state`` is enabled, quotes come from the OB-priced strike ladder
    (same rows as AES entry and trade monitor), not the legacy ticker WS market cache.
    """
    ex = normalize_exchange(exchange or DEFAULT_EXCHANGE)
    sym = str(symbol or "").strip().upper()
    mkt = (market or "hourly").strip().lower()
    if mkt not in ("hourly", "15m"):
        mkt = "hourly"
    if not sym or not live_state_cache_enabled():
        return None
    ladder = strike_ladder(sym, mkt, ex, max_age_sec=max_age_sec)
    if not ladder or not ladder.get("strikes"):
        return None
    snap = _market_snapshot_from_strike_ladder(ladder)
    if not snap.get("markets"):
        return None
    return snap


def kalshi_market_snapshot_for_monitoring(
    symbol: str,
    market: str,
    exchange: Optional[str] = None,
    *,
    prefer_max_age_sec: Optional[float] = None,
    allow_stale_max_age_sec: float = 180.0,
) -> Optional[Dict[str, Any]]:
    snap = kalshi_market_snapshot(
        symbol,
        market,
        exchange,
        max_age_sec=prefer_max_age_sec,
    )
    if snap and snap.get("markets"):
        return snap
    if not live_state_cache_enabled():
        return None
    ex = normalize_exchange(exchange or DEFAULT_EXCHANGE)
    sym = str(symbol or "").strip().upper()
    mkt = (market or "hourly").strip().lower()
    if mkt not in ("hourly", "15m"):
        mkt = "hourly"
    if not sym:
        return None
    env = live_state_cache.get_strike_ladder(ex, mkt, sym)
    if not env:
        return None
    age = _envelope_age_sec(env)
    if age > allow_stale_max_age_sec:
        return None
    ladder = strike_ladder_from_cache(ex, mkt, sym)
    if not ladder or not ladder.get("strikes"):
        return None
    relaxed = _market_snapshot_from_strike_ladder(ladder)
    if relaxed.get("markets"):
        _log_throttled(
            f"strike_ladder_relaxed:{ex}:{mkt}:{sym}",
            "ats_monitoring using relaxed stale strike_ladder %s:%s:%s age=%.1fs max=%.1fs",
            ex,
            mkt,
            sym,
            age,
            allow_stale_max_age_sec,
        )
    return relaxed if relaxed.get("markets") else None


def kalshi_closing_price_for_ticker(
    symbol: str,
    market: str,
    trade_ticker: str,
    trade_side: str,
    exchange: Optional[str] = None,
    *,
    max_age_sec: Optional[float] = None,
) -> Optional[float]:
    snap = kalshi_market_snapshot(
        symbol, market, exchange, max_age_sec=max_age_sec
    )
    if not snap:
        return None
    tt = str(trade_ticker or "").strip().upper()
    side_u = str(trade_side or "").strip().upper()
    if side_u in ("YES",):
        side_u = "Y"
    if side_u in ("NO",):
        side_u = "N"
    for m in snap.get("markets") or []:
        if str(m.get("ticker") or "").strip().upper() != tt:
            continue
        if side_u == "Y":
            v = m.get("no_ask_dollars")
        elif side_u == "N":
            v = m.get("yes_ask_dollars")
        else:
            return None
        if v is None:
            return None
        try:
            return float(v)
        except (TypeError, ValueError):
            return None
    return None


def kalshi_closing_price_for_ticker_monitoring(
    symbol: str,
    market: str,
    trade_ticker: str,
    trade_side: str,
    exchange: Optional[str] = None,
    *,
    prefer_max_age_sec: Optional[float] = None,
    allow_stale_max_age_sec: float = 180.0,
) -> Optional[float]:
    snap = kalshi_market_snapshot_for_monitoring(
        symbol,
        market,
        exchange,
        prefer_max_age_sec=prefer_max_age_sec,
        allow_stale_max_age_sec=allow_stale_max_age_sec,
    )
    if not snap:
        return None
    tt = str(trade_ticker or "").strip().upper()
    side_u = str(trade_side or "").strip().upper()
    if side_u in ("YES",):
        side_u = "Y"
    if side_u in ("NO",):
        side_u = "N"
    for m in snap.get("markets") or []:
        if str(m.get("ticker") or "").strip().upper() != tt:
            continue
        if side_u == "Y":
            v = m.get("no_ask_dollars")
        elif side_u == "N":
            v = m.get("yes_ask_dollars")
        else:
            return None
        if v is None:
            return None
        try:
            return float(v)
        except (TypeError, ValueError):
            return None
    return None


def kalshi_order(user_no: str, order_id: str) -> Optional[Dict[str, Any]]:
    """Kalshi order row from portfolio hot hash (WS-driven; no PostgreSQL)."""
    from backend.core import live_state_kalshi_portfolio as lskp

    oid = str(order_id or "").strip()
    if not oid:
        return None
    return lskp.get_order(user_no, oid)


def find_ladder_strike_row(
    ladder: Optional[Dict[str, Any]],
    ticker: str,
) -> Optional[Dict[str, Any]]:
    if not ladder or not ticker:
        return None
    t = str(ticker).strip()
    for row in ladder.get("strikes") or []:
        if not isinstance(row, dict):
            continue
        if str(row.get("ticker") or "").strip() == t:
            return row
    return None
