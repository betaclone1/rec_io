"""
Publish routing for pyth_price_watchdog.

Modes (PYTH_PUBLISH_MODE):
  experiment  — rec_io:pyth:* only
  shadow      — experiment + live_state
  live_state  — production hot path (default for commodities)
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, Literal, Optional

from backend.core.pyth_feed_cache import publish_tick

logger = logging.getLogger("pyth_price_watchdog")

PublishMode = Literal["experiment", "shadow", "live_state"]
_VALID_MODES = frozenset({"experiment", "shadow", "live_state"})


def publish_mode() -> PublishMode:
    raw = os.getenv("PYTH_PUBLISH_MODE", "live_state").strip().lower()
    if raw not in _VALID_MODES:
        logger.warning("invalid PYTH_PUBLISH_MODE=%r; using live_state", raw)
        return "live_state"
    return raw  # type: ignore[return-value]


def publish_live_state_hot_path(
    symbol: str,
    tick_row: Dict[str, Any],
    timestamp: str,
    *,
    ingest_mono: Optional[float] = None,
) -> bool:
    from backend.core.live_state_config import live_state_cache_enabled
    from backend.core import live_state_cache

    sym = symbol.strip().upper()
    if not live_state_cache_enabled():
        logger.warning("live_state cache disabled; skip publish for %s", sym)
        return False
    live_state_cache.set_symbol(
        sym,
        tick_row,
        source_event_at=timestamp,
        publish_detail="full",
        ingest_mono=ingest_mono,
    )
    return True


def publish_envelope_outputs(
    envelope: Dict[str, Any],
    *,
    ingest_mono: float,
) -> None:
    und = str(envelope.get("underlying_ticker") or "").strip()
    if not und:
        return

    mode = publish_mode()
    tick_row = envelope.get("metrics")
    symbol = str(envelope.get("symbol") or "").strip().upper()
    ts = envelope.get("published_at") or ""

    if mode in ("experiment", "shadow"):
        if not publish_tick(und, envelope):
            logger.warning(
                "experiment redis publish failed %s seq=%s",
                und,
                envelope.get("seq"),
            )

    if mode in ("shadow", "live_state") and tick_row and symbol:
        if not publish_live_state_hot_path(
            symbol, tick_row, ts, ingest_mono=ingest_mono
        ):
            logger.warning("live_state publish failed %s", symbol)

    _enqueue_commodity_price_ring(envelope, tick_row if isinstance(tick_row, dict) else None)
    envelope["pyth_publish_mode"] = mode


def _enqueue_commodity_price_ring(
    envelope: Dict[str, Any],
    tick_row: Optional[Dict[str, Any]],
) -> None:
    """Persist pyth-method commodity ticks so symbol_close can read ring avg_60s."""
    symbol = str(envelope.get("symbol") or "").strip().upper()
    if not symbol:
        return
    try:
        from backend.symbol_price_watchdog import COMMODITY_LIVE_STATE_SYMBOLS
    except Exception:
        return
    if symbol not in COMMODITY_LIVE_STATE_SYMBOLS:
        return
    try:
        from backend.core.live_price_ring_90m import (
            decimal_from_cfb_value,
            enqueue_ring_tick,
            ring_timestamp_utc_from_source_ms,
        )

        ring_ts = ring_timestamp_utc_from_source_ms(envelope.get("source_ts_ms"))
        price = decimal_from_cfb_value(envelope.get("price"))
        if not ring_ts or price is None:
            return
        avg = None
        if tick_row is not None:
            avg = decimal_from_cfb_value(tick_row.get("one_minute_avg"))
        enqueue_ring_tick(symbol, ring_ts, price, avg_60s=avg)
    except Exception as e:
        logger.warning("commodity price ring enqueue failed %s: %s", symbol, e)
