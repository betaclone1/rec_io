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
import queue
import threading
from typing import Any, Dict, Literal, Optional

from backend.core.cfbenchmarks_feed_cache import publish_tick

logger = logging.getLogger("cfbenchmarks_price_watchdog")

PublishMode = Literal["experiment", "shadow", "live_state"]
_VALID_MODES = frozenset({"experiment", "shadow", "live_state"})

_CYCLE_QUEUE_MAX = 20_000
_cycle_q: Optional["queue.Queue[Dict[str, Any]]"] = None
_cycle_thread: Optional[threading.Thread] = None
_cycle_lock = threading.Lock()
_cycle_dropped = 0


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


def _cycle_fanout_queue() -> "queue.Queue[Dict[str, Any]]":
    global _cycle_q, _cycle_thread
    with _cycle_lock:
        if _cycle_q is None:
            _cycle_q = queue.Queue(maxsize=_CYCLE_QUEUE_MAX)
        if _cycle_thread is None or not _cycle_thread.is_alive():
            _cycle_thread = threading.Thread(
                target=_cycle_fanout_loop,
                name="cfb_cycle_fanout",
                daemon=True,
            )
            _cycle_thread.start()
        return _cycle_q


def _cycle_fanout_loop() -> None:
    q = _cycle_q
    if q is None:
        return
    while True:
        job = q.get()
        try:
            from backend.core.cycle_hot_tables import enqueue_cycle_price_metrics

            enqueue_cycle_price_metrics(**job)
        except Exception as e:
            logger.warning(
                "15m cycle ring fanout failed %s: %s", job.get("symbol"), e
            )


def _submit_cycle_fanout(**job: Any) -> None:
    """
    Hand cycle capture work to one persistent worker.

    ``enqueue_cycle_price_metrics`` reads live_state and can run DDL, so it must
    never execute on the WS asyncio thread; a thread per tick was also churn.
    """
    global _cycle_dropped
    try:
        _cycle_fanout_queue().put_nowait(job)
    except queue.Full:
        _cycle_dropped += 1
        if _cycle_dropped % 100 == 1:
            logger.warning(
                "15m cycle fanout queue full; dropped %s ticks", _cycle_dropped
            )


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

    # Sidecar PG rings (backtesting only): never block live_state. Same UTC tick key.
    if symbol in ("BTC", "ETH", "SOL", "XRP", "DOGE"):
        try:
            from backend.core.live_price_ring_90m import (
                avg_value_from_cfb_obj,
                decimal_from_cfb_value,
                enqueue_ring_tick,
                ring_timestamp_utc_from_source_ms,
            )

            ring_ts = ring_timestamp_utc_from_source_ms(envelope.get("source_ts_ms"))
            if ring_ts:
                ring_price = None
                if price is not None:
                    inner = (
                        envelope.get("inner")
                        if isinstance(envelope.get("inner"), dict)
                        else {}
                    )
                    ring_price = decimal_from_cfb_value(inner.get("value"))
                    if ring_price is None:
                        ring_price = decimal_from_cfb_value(price)
                    if ring_price is not None:
                        enqueue_ring_tick(
                            symbol,
                            ring_ts,
                            ring_price,
                            avg_60s=avg_value_from_cfb_obj(
                                envelope.get("avg_60s_data")
                            ),
                            last_60s_windowed_average_15min=avg_value_from_cfb_obj(
                                envelope.get("last_60s_windowed_average_15min")
                            ),
                        )
                if isinstance(tick_row, dict):
                    try:
                        from backend.core.live_metrics_ring_90m import (
                            enqueue_metrics_ring_tick,
                        )

                        enqueue_metrics_ring_tick(symbol, ring_ts, tick_row)
                    except Exception as e:
                        logger.debug(
                            "metrics ring PG enqueue skipped %s: %s", symbol, e
                        )
                # Per-ticker 15m cycle packages (historical_data hot tables).
                # Off the WS asyncio thread: ensure_live_cycle_hot reads live_state
                # and can do sync DDL, which stalled pings → reconnect.
                try:
                    from backend.core.cycle_hot_tables import enabled_cycle_symbols

                    if symbol in enabled_cycle_symbols():
                        _submit_cycle_fanout(
                            symbol=symbol,
                            timestamp_utc=ring_ts,
                            price=ring_price,
                            avg_60s=avg_value_from_cfb_obj(
                                envelope.get("avg_60s_data")
                            ),
                            last_60s_windowed_average_15min=avg_value_from_cfb_obj(
                                envelope.get("last_60s_windowed_average_15min")
                            ),
                            metrics=tick_row if isinstance(tick_row, dict) else None,
                        )
                except Exception as e:
                    logger.warning(
                        "15m cycle ring enqueue skipped %s: %s", symbol, e
                    )
        except Exception as e:
            logger.debug("ring PG enqueue skipped %s: %s", symbol, e)

    envelope["cfb_publish_mode"] = mode
