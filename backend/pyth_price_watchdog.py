#!/usr/bin/env python3
"""
Kalshi pyth_value price watchdog for commodity underlyings (GOLD / SILVER / WTI).

Default underlyings (Kalshi settlement sources):
  Metal.Index.1OZGOLD/USD → GOLD
  Metal.Index.SILVER/USD → SILVER
  Commodities.Index.PYTHOIL/USD → WTI

Publish routing (PYTH_PUBLISH_MODE): experiment | shadow | live_state (default).

Run: python backend/pyth_price_watchdog.py
     python backend/pyth_price_watchdog.py Metal.Index.1OZGOLD/USD,Metal.Index.SILVER/USD
Docs: https://docs.kalshi.com/websockets/pyth-value
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

from backend.core.kalshi_ws_auth import kalshi_ws_connect_headers
from backend.core.pyth_feed_cache import (
    parse_underlyings,
    set_meta,
    symbol_for_underlying,
)
from backend.core.pyth_feed_health import (
    PythFeedHealth,
    feed_health_check_interval_sec,
    feed_health_enabled,
    feed_stale_tick_sec,
)
from backend.core.pyth_publish import publish_envelope_outputs, publish_mode
from backend.core.pyth_tick_metrics import (
    attach_commodity_metrics,
    preload_analytics_profiles,
    wall_timestamp_est,
)

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
    log = logging.getLogger("pyth_price_watchdog")
    if log.handlers:
        return log
    handler = _FlushingStreamHandler(sys.stdout)
    handler.setFormatter(_est_formatter())
    log.addHandler(handler)
    log.setLevel(logging.INFO)
    return log


logger = _configure_logging()


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
    if data.get("type") != "pyth_value":
        return None
    msg = data.get("msg") if isinstance(data.get("msg"), dict) else {}
    underlying = str(msg.get("underlying_ticker") or "").strip()
    if not underlying:
        return None
    price = _float_or_none(msg.get("value_usd"))
    source_ts_ms = msg.get("source_ts_ms")
    kalshi_received_ms = msg.get("received_at")
    now_ms = int(time.time() * 1000)
    lag_kalshi_ms = None
    lag_source_ms = None
    if kalshi_received_ms is not None and source_ts_ms is not None:
        try:
            lag_source_ms = int(kalshi_received_ms) - int(source_ts_ms)
        except (TypeError, ValueError):
            pass
    if kalshi_received_ms is not None:
        try:
            lag_kalshi_ms = now_ms - int(kalshi_received_ms)
        except (TypeError, ValueError):
            pass

    return {
        "type": "pyth_tick",
        "underlying_ticker": underlying,
        "symbol": symbol_for_underlying(underlying),
        "price": price,
        "source_ts_ms": source_ts_ms,
        "kalshi_received_at_ms": kalshi_received_ms,
        "ingest_mono": ingest_mono,
        "lag_source_to_kalshi_ms": lag_source_ms,
        "lag_kalshi_to_local_ms": lag_kalshi_ms,
        "sid": data.get("sid"),
        "seq": seq,
        "published_at": wall_timestamp_est(),
    }


class PythPriceWatchdog:
    def __init__(self, underlyings: List[str]) -> None:
        self.underlyings = [u.strip() for u in underlyings if u.strip()]
        if not self.underlyings:
            self.underlyings = parse_underlyings()
        from backend.symbol_price_watchdog import COMMODITY_LIVE_STATE_SYMBOLS

        self.symbols = [
            symbol_for_underlying(u)
            for u in self.underlyings
            if symbol_for_underlying(u) in COMMODITY_LIVE_STATE_SYMBOLS
        ]
        preload_analytics_profiles(self.symbols)
        try:
            from backend.core.live_price_ring_90m import hydrate_startup_buffers

            hydrate_startup_buffers(self.symbols)
        except Exception as e:
            logger.warning("commodity ring hydrate failed: %s", e)
        self.command_id = 1
        self.tick_seq_by_underlying: Dict[str, int] = {
            u: 0 for u in self.underlyings
        }
        self.connected = False
        self.subscription_sid: Optional[int] = None
        self._backoff_sec = 1.0
        self._feed_health = PythFeedHealth(self.underlyings)

    def _next_cmd_id(self) -> int:
        cid = self.command_id
        self.command_id += 1
        return cid

    async def _subscribe(self, ws) -> None:
        sub = {
            "id": self._next_cmd_id(),
            "cmd": "subscribe",
            "params": {
                "channels": ["pyth_value"],
                "underlying_tickers": self.underlyings,
            },
        }
        await ws.send(json.dumps(sub))
        logger.info(
            "sent subscribe pyth_value underlying_tickers=%s", self.underlyings
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
        elif msg_type == "pyth_value_underlying_list":
            logger.info("underlying_list: %s", data.get("msg"))
        elif msg_type == "error":
            logger.warning("ws error: %s", data)

    def _update_meta(
        self, underlying: str, *, extra: Optional[Dict[str, Any]] = None
    ) -> None:
        und = underlying.strip()
        meta = {
            "underlying_ticker": und,
            "symbol": symbol_for_underlying(und),
            "underlyings": self.underlyings,
            "connected": self.connected,
            "subscription_sid": self.subscription_sid,
            "tick_count": self.tick_seq_by_underlying.get(und, 0),
            "updated_at": datetime.now(EST).isoformat(),
        }
        if extra:
            meta.update(extra)
        if feed_health_enabled():
            meta.update(self._feed_health.meta_snapshot())
        set_meta(und, meta)

    def _update_meta_all(self, *, extra: Optional[Dict[str, Any]] = None) -> None:
        for und in self.underlyings:
            self._update_meta(und, extra=extra)

    async def _handle_message(self, raw: str) -> None:
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            logger.debug("non-json frame: %s", raw[:200])
            return
        if not isinstance(data, dict):
            return

        msg_type = data.get("type")
        if msg_type in ("subscribed", "error", "pyth_value_underlying_list"):
            self._handle_control(data)
            return

        ingest_mono = time.monotonic()
        envelope = envelope_from_ws_message(
            data, seq=0, ingest_mono=ingest_mono
        )
        if not envelope:
            return

        und = str(envelope.get("underlying_ticker") or "").strip()
        if und not in self.underlyings:
            logger.debug("tick for unsubscribed underlying %s", und)
            return

        self.tick_seq_by_underlying[und] = self.tick_seq_by_underlying.get(und, 0) + 1
        envelope["seq"] = self.tick_seq_by_underlying[und]

        self._feed_health.record_tick(und)
        attach_commodity_metrics(envelope, ingest_mono=ingest_mono)
        publish_envelope_outputs(envelope, ingest_mono=ingest_mono)
        self._update_meta(
            und,
            extra={
                "last_tick_at": envelope.get("published_at"),
                "last_price": envelope.get("price"),
            },
        )
        seq = self.tick_seq_by_underlying.get(und, 0)
        if seq == 1 or seq % 60 == 0:
            logger.info(
                "tick %s (%s) seq=%s price=%s lag_kalshi_ms=%s",
                und,
                envelope.get("symbol"),
                seq,
                envelope.get("price"),
                envelope.get("lag_kalshi_to_local_ms"),
            )

    async def _feed_health_loop(self, ws) -> None:
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
                    "connecting %s underlyings=%s feed_health=%s",
                    WS_URL,
                    self.underlyings,
                    feed_health_enabled(),
                )
                async with websockets.connect(
                    WS_URL,
                    additional_headers=headers,
                    ping_interval=20,
                    ping_timeout=60,
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
    os.environ.setdefault("REC_POOL_USER_NUMBER", "0001")
    if len(sys.argv) > 1:
        underlyings = parse_underlyings(sys.argv[1])
    else:
        underlyings = parse_underlyings()
    logger.info(
        "starting pyth watchdog mode=%s underlyings=%s symbols=%s feed_stale_tick_sec=%s",
        publish_mode(),
        underlyings,
        [symbol_for_underlying(u) for u in underlyings],
        feed_stale_tick_sec(),
    )
    try:
        asyncio.run(PythPriceWatchdog(underlyings=underlyings).run_forever())
    except KeyboardInterrupt:
        logger.info("stopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
