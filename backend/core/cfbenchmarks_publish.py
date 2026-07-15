"""
Publish routing for cfbenchmarks_price_watchdog.

Modes (CFBENCHMARKS_PUBLISH_MODE):
  experiment  — rec_io:experiment:cfbenchmarks:* only (default)
  shadow      — experiment + live_state hot path (validation; do not run with legacy WDs writing live_state)
  live_state  — production cutover: same contract as symbol_price_watchdog hot path

Does not modify symbol_price_watchdog.py.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, Literal, Optional

from backend.core.cfbenchmarks_feed_cache import publish_tick

logger = logging.getLogger("cfbenchmarks_price_watchdog")

PublishMode = Literal["experiment", "shadow", "live_state"]
_VALID_MODES = frozenset({"experiment", "shadow", "live_state"})


def publish_mode() -> PublishMode:
    raw = os.getenv("CFBENCHMARKS_PUBLISH_MODE", "experiment").strip().lower()
    if raw not in _VALID_MODES:
        logger.warning(
            "invalid CFBENCHMARKS_PUBLISH_MODE=%r; using experiment", raw
        )
        return "experiment"
    return raw  # type: ignore[return-value]


def pg_ticks_enabled() -> bool:
    return os.getenv("CFBENCHMARKS_PG_TICKS", "0").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def _table_name_for_symbol(symbol: str) -> str:
    from backend.symbol_price_watchdog import SYMBOL_CONFIG

    cfg = SYMBOL_CONFIG.get(symbol.upper(), {})
    return str(cfg.get("table_name") or f"live_price_log_1s_{symbol.lower()}")


def publish_live_state_hot_path(
    symbol: str,
    tick_row: Dict[str, Any],
    timestamp: str,
    *,
    ingest_mono: Optional[float] = None,
) -> bool:
    """
    Mirror symbol_price_watchdog _publish_crypto_live_state (live_state + optional spool).

    Does not call legacy private helpers; behavior aligned with that path.
    """
    from backend.core.live_state_config import (
        live_state_cache_enabled,
        live_state_spool_enabled,
    )
    from backend.core import live_state_cache

    sym = symbol.strip().upper()
    if not live_state_cache_enabled():
        logger.warning("live_state cache disabled; skip publish for %s", sym)
        return False

    table_name = _table_name_for_symbol(sym)
    live_state_cache.set_symbol(
        sym,
        tick_row,
        source_event_at=timestamp,
        publish_detail="full",
        ingest_mono=ingest_mono,
    )
    if live_state_spool_enabled():
        try:
            from backend.core import event_spool
        except ImportError:
            event_spool = None  # type: ignore[misc, assignment]
        if event_spool is not None:
            event_spool.append_event(
                "tick",
                {"symbol": sym, "table_name": table_name, "row": tick_row},
                source="cfbenchmarks_price_watchdog",
                idempotency_key=f"tick:{sym}:{timestamp}",
                occurred_at=timestamp,
            )
    return True


def publish_pg_tick(
    symbol: str,
    timestamp: str,
    price: float,
    *,
    ingest_mono: float,
) -> None:
    """
    Optional cold path via legacy insert_tick (rebuilds row from buffer; see cutover doc).
    """
    from backend.symbol_price_watchdog import insert_tick

    insert_tick(symbol, timestamp, float(price), ws_received_mono=ingest_mono)


def publish_envelope_outputs(
    envelope: Dict[str, Any],
    *,
    ingest_mono: float,
) -> None:
    """
    After attach_legacy_metrics: route to experiment Redis and/or live_state per mode.
    """
    iid = str(envelope.get("index_id") or "").strip().upper()
    if not iid:
        return

    mode = publish_mode()
    tick_row = envelope.get("metrics")
    symbol = str(envelope.get("symbol") or "").strip().upper()
    ts = envelope.get("published_at") or ""
    price = envelope.get("price")

    if mode in ("experiment", "shadow"):
        if not publish_tick(iid, envelope):
            logger.warning(
                "experiment redis publish failed %s seq=%s",
                iid,
                envelope.get("seq"),
            )

    if mode in ("shadow", "live_state") and tick_row and symbol:
        if not publish_live_state_hot_path(
            symbol, tick_row, ts, ingest_mono=ingest_mono
        ):
            logger.warning("live_state publish failed %s", symbol)
        elif pg_ticks_enabled() and price is not None:
            try:
                publish_pg_tick(symbol, ts, float(price), ingest_mono=ingest_mono)
            except Exception as e:
                logger.warning("PG insert_tick failed %s: %s", symbol, e)

    if price is not None and symbol in ("BTC", "ETH", "SOL", "XRP", "DOGE"):
        metrics = envelope.get("metrics") if isinstance(envelope.get("metrics"), dict) else {}
        ring_ts = str(metrics.get("timestamp") or ts or "").strip()
        if ring_ts:
            try:
                from backend.core.live_price_ring_90m import enqueue_ring_tick

                enqueue_ring_tick(symbol, ring_ts, float(price))
            except Exception as e:
                logger.debug("ring PG enqueue skipped %s: %s", symbol, e)

    envelope["cfb_publish_mode"] = mode
