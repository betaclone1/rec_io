#!/usr/bin/env python3
"""
Kalshi cfbenchmarks_value price watchdog (multi-index, one WebSocket).

Default indices: BRTI, ETHUSD_RTI, SOLUSD_RTI, XRPUSD_RTI, DOGEUSD_RTI.

Publish routing (CFBENCHMARKS_PUBLISH_MODE):
  experiment  — test UI only (rec_io:experiment:cfbenchmarks:*); default
  shadow      — experiment + live_state (staging validation)
  live_state  — production cutover hot path (replaces symbol_price_watchdog)

See docs/CFB_PRICE_WATCHDOG_CUTOVER.md. Do not run live_state/shadow against legacy
symbol_price_watchdog writers on the same symbols.

Run: python backend/cfbenchmarks_price_watchdog.py
     python backend/cfbenchmarks_price_watchdog.py BRTI,ETHUSD_RTI
Docs: https://docs.kalshi.com/websockets/cfbenchmarks-value
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import time
from datetime import datetime
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

import websockets
from websockets.exceptions import ConnectionClosedError, ConnectionClosedOK

from backend.util.paths import get_project_root

if get_project_root() not in sys.path:
    sys.path.insert(0, get_project_root())

from backend.core.cfbenchmarks_feed_cache import (
    parse_index_ids,
    set_meta,
    symbol_for_index,
)
from backend.core.cfbenchmarks_feed_health import (
    CfBenchmarksFeedHealth,
    feed_health_check_interval_sec,
    feed_health_enabled,
)
from backend.core.cfbenchmarks_publish import publish_envelope_outputs, publish_mode
from backend.core.cfbenchmarks_tick_metrics import (
    attach_legacy_metrics,
    preload_analytics_profiles,
    symbols_for_index_ids,
    wall_timestamp_est,
)
from backend.core.kalshi_ws_auth import kalshi_ws_connect_headers

WS_URL = os.getenv(
    "KALSHI_WS_URL", "wss://external-api-ws.kalshi.com/trade-api/ws/v2"
).strip()
EST = ZoneInfo("America/New_York")


def _est_formatter():
    class ESTFormatter(logging.Formatter):
        def formatTime(self, record, datefmt=None):
            dt = datetime.fromtimestamp(record.created, tz=EST)
            if datefmt:
                return dt.strftime(datefmt)
            s = dt.strftime("%Y-%m-%dT%H:%M:%S")
            z = dt.strftime("%z")
            return s + (z[:3] + ":" + z[3:] if len(z) >= 5 else z)

    return ESTFormatter(fmt="%(asctime)s %(levelname)s [%(name)s] %(message)s")


class _FlushingStreamHandler(logging.StreamHandler):
    def emit(self, record):
        super().emit(record)
        self.flush()


def _configure_logging() -> logging.Logger:
    log = logging.getLogger("cfbenchmarks_price_watchdog")
    if log.handlers:
        return log
    handler = _FlushingStreamHandler(sys.stdout)
    handler.setFormatter(_est_formatter())
    log.addHandler(handler)
    log.setLevel(logging.INFO)
    return log


logger = _configure_logging()


def _parse_inner_data(raw: Any) -> Dict[str, Any]:
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return dict(raw)
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else {"raw": raw}
        except json.JSONDecodeError:
            return {"raw": raw}
    return {"raw": str(raw)}


def _float_or_none(val: Any) -> Optional[float]:
    if val is None:
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def envelope_from_ws_message(
    data: Dict[str, Any],
    *,
    seq: int,
    ingest_mono: float,
) -> Optional[Dict[str, Any]]:
    if data.get("type") != "cfbenchmarks_value":
        return None
    msg = data.get("msg") if isinstance(data.get("msg"), dict) else {}
    index_id = str(msg.get("index_id") or "").strip().upper()
    if not index_id:
        return None
    inner = _parse_inner_data(msg.get("data"))
    price = _float_or_none(inner.get("value"))
    source_ts_ms = inner.get("time") or msg.get("received_at")
    kalshi_received_ms = msg.get("received_at")
    now_ms = int(time.time() * 1000)
    lag_kalshi_ms = None
    lag_source_ms = None
    if kalshi_received_ms is not None and source_ts_ms is not None:
        try:
            lag_source_ms = int(kalshi_received_ms) - int(source_ts_ms)
        except (TypeError, ValueError):
            pass
    if now_ms and kalshi_received_ms is not None:
        try:
            lag_kalshi_ms = now_ms - int(kalshi_received_ms)
        except (TypeError, ValueError):
            pass

    return {
        "type": "cfbenchmarks_tick",
        "index_id": index_id,
        "symbol": symbol_for_index(index_id),
        "price": price,
        "source_ts_ms": source_ts_ms,
        "kalshi_received_at_ms": kalshi_received_ms,
        "ingest_mono": ingest_mono,
        "lag_source_to_kalshi_ms": lag_source_ms,
        "lag_kalshi_to_local_ms": lag_kalshi_ms,
        "inner": inner,
        "avg_60s_data": msg.get("avg_60s_data"),
        "last_60s_windowed_average_15min": msg.get("last_60s_windowed_average_15min"),
        "sid": data.get("sid"),
        "seq": seq,
        "published_at": wall_timestamp_est(),
    }


class CfBenchmarksWatchdog:
    def __init__(self, index_ids: List[str]) -> None:
        self.index_ids = [i.strip().upper() for i in index_ids if i.strip()]
        if not self.index_ids:
            self.index_ids = parse_index_ids()
        self.symbols = symbols_for_index_ids(self.index_ids)
        preload_analytics_profiles(self.symbols)
        try:
            from backend.core.live_price_ring_90m import hydrate_startup_buffers

            hydrate_startup_buffers(self.symbols)
        except Exception as e:
            logger.warning("ring PG startup hydrate failed: %s", e)
        self.command_id = 1
        self.tick_seq_by_index: Dict[str, int] = {iid: 0 for iid in self.index_ids}
        self.connected = False
        self.subscription_sid: Optional[int] = None
        self._backoff_sec = 1.0
        self._feed_health = CfBenchmarksFeedHealth(self.index_ids)

    def _next_cmd_id(self) -> int:
        cid = self.command_id
        self.command_id += 1
        return cid

    async def _subscribe(self, ws) -> None:
        sub = {
            "id": self._next_cmd_id(),
            "cmd": "subscribe",
            "params": {
                "channels": ["cfbenchmarks_value"],
                "index_ids": self.index_ids,
            },
        }
        await ws.send(json.dumps(sub))
        logger.info(
            "sent subscribe cfbenchmarks_value index_ids=%s", self.index_ids
        )

    def _handle_control(self, data: Dict[str, Any]) -> None:
        msg_type = data.get("type")
        if msg_type == "subscribed":
            msg = data.get("msg") if isinstance(data.get("msg"), dict) else {}
            self.subscription_sid = msg.get("sid") or data.get("sid")
            logger.info(
                "subscribed sid=%s channel=%s",
                self.subscription_sid,
                msg.get("channel"),
            )
        elif msg_type == "cfbenchmarks_value_indexlist":
            logger.info("indexlist: %s", data)
        elif msg_type == "error":
            logger.warning("ws error: %s", data)

    def _update_meta(self, index_id: str, *, extra: Optional[Dict[str, Any]] = None) -> None:
        iid = index_id.strip().upper()
        meta = {
            "index_id": iid,
            "symbol": symbol_for_index(iid),
            "index_ids": self.index_ids,
            "connected": self.connected,
            "subscription_sid": self.subscription_sid,
            "tick_count": self.tick_seq_by_index.get(iid, 0),
            "updated_at": datetime.now(EST).isoformat(),
        }
        if extra:
            meta.update(extra)
        if feed_health_enabled():
            meta.update(self._feed_health.meta_snapshot())
        set_meta(iid, meta)

    def _update_meta_all(self, *, extra: Optional[Dict[str, Any]] = None) -> None:
        for iid in self.index_ids:
            self._update_meta(iid, extra=extra)

    async def _handle_message(self, raw: str) -> None:
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            logger.debug("non-json frame: %s", raw[:200])
            return
        if not isinstance(data, dict):
            return

        msg_type = data.get("type")
        if msg_type in ("subscribed", "error", "cfbenchmarks_value_indexlist"):
            self._handle_control(data)
            return

        ingest_mono = time.monotonic()
        envelope = envelope_from_ws_message(
            data, seq=0, ingest_mono=ingest_mono
        )
        if not envelope:
            return

        iid = str(envelope.get("index_id") or "").strip().upper()
        if iid not in self.index_ids:
            logger.debug("tick for unsubscribed index %s", iid)
            return

        if iid not in self.tick_seq_by_index:
            self.tick_seq_by_index[iid] = 0
        self.tick_seq_by_index[iid] += 1
        envelope["seq"] = self.tick_seq_by_index[iid]

        self._feed_health.record_tick(iid)
        attach_legacy_metrics(envelope, ingest_mono=ingest_mono)
        publish_envelope_outputs(envelope, ingest_mono=ingest_mono)
        self._update_meta(
            iid,
            extra={
                "last_tick_at": envelope.get("published_at"),
                "last_price": envelope.get("price"),
            },
        )
        seq = self.tick_seq_by_index.get(iid, 0)
        if seq == 1 or seq % 60 == 0:
            logger.info(
                "tick %s seq=%s price=%s delta_1m=%s momentum=%s lag_kalshi_ms=%s window_15m=%s",
                iid,
                seq,
                envelope.get("price"),
                envelope.get("delta_1m"),
                envelope.get("momentum"),
                envelope.get("lag_kalshi_to_local_ms"),
                "yes"
                if envelope.get("last_60s_windowed_average_15min")
                else "no",
            )

    async def _feed_health_loop(self, ws) -> None:
        """Force reconnect when any subscribed index stops printing ticks."""
        interval = feed_health_check_interval_sec()
        while True:
            await asyncio.sleep(interval)
            healthy, summary, reconnect_reason = self._feed_health.evaluate()
            if healthy:
                continue
            logger.warning(
                "feed health unhealthy (%s); closing websocket to reconnect",
                summary,
            )
            self._update_meta_all(
                extra={
                    "feed_health_summary": summary,
                    "last_error": reconnect_reason,
                }
            )
            try:
                await ws.close(
                    code=1012,
                    reason=(reconnect_reason or "feed_stale")[:120],
                )
            except Exception as e:
                logger.debug("feed health ws.close: %s", e)
            return

    async def _run_connected_session(self, ws) -> Optional[str]:
        """Read messages until disconnect or feed-health forces reconnect."""
        self._feed_health.begin_session()
        self.connected = True
        self._backoff_sec = 1.0
        self._update_meta_all()
        await self._subscribe(ws)
        health_task: Optional[asyncio.Task] = None
        if feed_health_enabled():
            health_task = asyncio.create_task(self._feed_health_loop(ws))
        feed_error: Optional[str] = None
        try:
            async for message in ws:
                await self._handle_message(message)
        except (ConnectionClosedOK, ConnectionClosedError):
            pass
        finally:
            if health_task is not None:
                health_task.cancel()
                try:
                    await health_task
                except asyncio.CancelledError:
                    pass
                except Exception as e:
                    logger.debug("feed health task exit: %s", e)
            snap = self._feed_health.meta_snapshot()
            feed_error = snap.get("feed_reconnect_pending")
            if feed_error:
                feed_error = str(feed_error)
        return feed_error

    async def run_forever(self) -> None:
        while True:
            last_error: Optional[str] = None
            try:
                headers = kalshi_ws_connect_headers()
                logger.info(
                    "connecting %s index_ids=%s feed_health=%s",
                    WS_URL,
                    self.index_ids,
                    feed_health_enabled(),
                )
                async with websockets.connect(
                    WS_URL,
                    additional_headers=headers,
                    ping_interval=20,
                    ping_timeout=20,
                    close_timeout=10,
                ) as ws:
                    last_error = await self._run_connected_session(ws)
            except (ConnectionClosedOK, ConnectionClosedError) as e:
                if not last_error:
                    last_error = str(e)
                logger.warning("websocket closed: %s", e)
            except FileNotFoundError as e:
                logger.error("credentials: %s", e)
                raise SystemExit(1) from e
            except Exception as e:
                last_error = str(e)
                logger.warning("connection error: %s", e)
            finally:
                self.connected = False
                self.subscription_sid = None
                self._update_meta_all(extra={"last_error": last_error})

            wait = min(self._backoff_sec, 60.0)
            logger.info("reconnect in %.1fs", wait)
            await asyncio.sleep(wait)
            self._backoff_sec = min(self._backoff_sec * 2, 60.0)


def main() -> int:
    # Required before symbol_price_watchdog import (analytics profiles / port config).
    os.environ.setdefault("REC_POOL_USER_NUMBER", "0001")
    if len(sys.argv) > 1:
        index_ids = parse_index_ids(sys.argv[1])
    else:
        index_ids = parse_index_ids()
    from backend.core.cfbenchmarks_feed_health import feed_stale_tick_sec

    logger.info(
        "starting cfbenchmarks watchdog mode=%s index_ids=%s symbols=%s feed_stale_tick_sec=%s",
        publish_mode(),
        index_ids,
        [symbol_for_index(i) for i in index_ids],
        feed_stale_tick_sec(),
    )
    try:
        asyncio.run(CfBenchmarksWatchdog(index_ids=index_ids).run_forever())
    except KeyboardInterrupt:
        logger.info("stopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
