"""Startup/shutdown: legacy state migration + Redis db/preferences fan-in threads."""

import asyncio
import logging
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI

_log = logging.getLogger("main_app")


@asynccontextmanager
async def main_app_lifespan(_app: FastAPI, *, main_app_port: int):
    from backend.trading_mode import migrate_legacy_state_file
    from backend.web.main_realtime import (
        redis_cfbenchmarks_feed_consume_loop,
        redis_cfbenchmarks_feed_subscriber_thread,
        redis_db_changes_consume_loop,
        redis_db_changes_subscriber_thread,
        redis_live_state_debug_consume_loop,
        redis_live_state_debug_subscriber_thread,
        redis_trading_preferences_consume_loop,
        redis_trading_preferences_subscriber_thread,
    )

    try:
        migrate_legacy_state_file()
    except Exception as e:
        _log.warning("migrate_legacy_state_file: %s", e)
    _log.info("Main app started on port %s", main_app_port)
    redis_queue: asyncio.Queue = asyncio.Queue()
    pref_queue: asyncio.Queue = asyncio.Queue()
    live_state_queue: asyncio.Queue = asyncio.Queue()
    cfbenchmarks_queue: asyncio.Queue = asyncio.Queue()
    loop = asyncio.get_running_loop()
    consumer = asyncio.create_task(redis_db_changes_consume_loop(redis_queue))
    pref_consumer = asyncio.create_task(redis_trading_preferences_consume_loop(pref_queue))
    live_state_consumer = asyncio.create_task(
        redis_live_state_debug_consume_loop(live_state_queue)
    )
    cfbenchmarks_consumer = asyncio.create_task(
        redis_cfbenchmarks_feed_consume_loop(cfbenchmarks_queue)
    )
    forwarder_thread = threading.Thread(
        target=redis_db_changes_subscriber_thread,
        args=(redis_queue, loop),
        daemon=True,
        name="redis_db_changes_forwarder",
    )
    forwarder_thread.start()
    pref_forwarder = threading.Thread(
        target=redis_trading_preferences_subscriber_thread,
        args=(pref_queue, loop),
        daemon=True,
        name="redis_trading_preferences_forwarder",
    )
    pref_forwarder.start()
    live_state_forwarder = threading.Thread(
        target=redis_live_state_debug_subscriber_thread,
        args=(live_state_queue, loop),
        daemon=True,
        name="redis_live_state_debug_forwarder",
    )
    live_state_forwarder.start()
    cfbenchmarks_forwarder = threading.Thread(
        target=redis_cfbenchmarks_feed_subscriber_thread,
        args=(cfbenchmarks_queue, loop),
        daemon=True,
        name="redis_cfbenchmarks_feed_forwarder",
    )
    cfbenchmarks_forwarder.start()
    try:
        from backend.core.performance_rollups import warm_dashboard_performance_snapshots_async

        warm_dashboard_performance_snapshots_async()
    except Exception as e:
        _log.warning("dashboard performance snapshot warm skipped: %s", e)
    try:
        yield
    finally:
        consumer.cancel()
        pref_consumer.cancel()
        live_state_consumer.cancel()
        cfbenchmarks_consumer.cancel()
        try:
            await consumer
        except asyncio.CancelledError:
            pass
        try:
            await pref_consumer
        except asyncio.CancelledError:
            pass
        try:
            await live_state_consumer
        except asyncio.CancelledError:
            pass
        try:
            await cfbenchmarks_consumer
        except asyncio.CancelledError:
            pass
        _log.info("Main app shutting down")
