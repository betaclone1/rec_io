"""
Build live_state tick rows for pyth_value commodity ticks.

Same path as CFB: append to symbol_tick_buffer, then
``symbol_price_watchdog.build_symbol_tick_row`` for full deltas / momentum /
movement / volatility fields.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List
from zoneinfo import ZoneInfo

from backend.core.pyth_feed_cache import UNDERLYING_TO_SYMBOL

logger = logging.getLogger("pyth_price_watchdog")

_EST = ZoneInfo("America/New_York")
_TRACKED = frozenset(UNDERLYING_TO_SYMBOL.values())
_profiles_loaded = False

_METRIC_SHORTCUTS = (
    "delta_1m",
    "delta_2m",
    "delta_3m",
    "delta_4m",
    "delta_15m",
    "delta_30m",
    "delta_5s",
    "delta_10s",
    "delta_15s",
    "delta_30s",
    "momentum",
    "momentum_percentile",
    "momentum_5s_avg",
    "momentum_10s_avg",
    "momentum_30s_avg",
    "momentum_1m_avg",
    "momentum_acceleration",
    "one_minute_avg",
    "volatility",
    "volatility_percentile",
    "move_1m",
    "move_2m",
    "move_3m",
    "move_4m",
    "move_15m",
    "move_30m",
    "movement",
    "movement_percentile",
)


def wall_timestamp_est() -> str:
    now = datetime.now(_EST)
    return now.strftime("%Y-%m-%dT%H:%M:%S") + f".{now.microsecond // 1000:03d}"


def _tick_timestamp_est(envelope: Dict[str, Any]) -> str:
    ms = envelope.get("source_ts_ms")
    if ms is not None:
        try:
            dt = datetime.fromtimestamp(int(ms) / 1000.0, tz=_EST)
            return (
                dt.strftime("%Y-%m-%dT%H:%M:%S")
                + f".{dt.microsecond // 1000:03d}"
            )
        except (TypeError, ValueError, OSError):
            pass
    return str(envelope.get("published_at") or wall_timestamp_est())


def preload_analytics_profiles(symbols: List[str]) -> None:
    """Best-effort percentile profiles (missing commodity tables → empty / soft fail)."""
    global _profiles_loaded
    if _profiles_loaded:
        return
    from backend.symbol_price_watchdog import (
        load_momentum_profile,
        load_movement_profile,
        load_volatility_profile,
    )

    for sym in symbols:
        u = str(sym or "").strip().upper()
        if u not in _TRACKED:
            continue
        try:
            load_momentum_profile(u)
            load_volatility_profile(u)
            load_movement_profile(u)
            logger.info("loaded analytics profiles for %s", u)
        except Exception as e:
            logger.warning("analytics profile preload %s: %s", u, e)
    _profiles_loaded = True


def attach_commodity_metrics(
    envelope: Dict[str, Any],
    *,
    ingest_mono: float,
) -> Dict[str, Any]:
    """
    Full price-watchdog tick row (deltas, momentum, movement, volatility).

    Requires GOLD/SILVER/WTI in SYMBOL_CONFIG and LIVE_STATE_TICK_BUFFER_SYMBOLS
    so metrics read the in-process tick buffer (no commodity PG price-log required).
    """
    symbol = str(envelope.get("symbol") or "").strip().upper()
    price = envelope.get("price")
    if symbol not in _TRACKED or price is None:
        return envelope

    ts = _tick_timestamp_est(envelope)
    px = float(price)

    try:
        from backend.core.symbol_tick_buffer import append_tick
        from backend.symbol_price_watchdog import build_symbol_tick_row

        append_tick(symbol, ts, px)
        tick_row, _table = build_symbol_tick_row(
            symbol, ts, px, ws_received_mono=ingest_mono
        )
        tick_row["feed"] = "pyth_value"
        tick_row["underlying_ticker"] = envelope.get("underlying_ticker")

        envelope["metrics"] = tick_row
        envelope["published_at"] = ts
        for key in _METRIC_SHORTCUTS:
            if key in tick_row:
                envelope[key] = tick_row[key]
    except Exception as e:
        logger.warning("commodity metrics failed %s: %s", symbol, e)
        envelope["metrics_error"] = str(e)
        envelope["metrics"] = {
            "timestamp": ts,
            "ws_received_mono": ingest_mono,
            "price": px,
            "feed": "pyth_value",
            "underlying_ticker": envelope.get("underlying_ticker"),
        }
        envelope["published_at"] = ts

    return envelope
