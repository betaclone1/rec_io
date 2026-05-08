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
        redis_db_changes_consume_loop,
        redis_db_changes_subscriber_thread,
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
    loop = asyncio.get_running_loop()
    consumer = asyncio.create_task(redis_db_changes_consume_loop(redis_queue))
    pref_consumer = asyncio.create_task(redis_trading_preferences_consume_loop(pref_queue))
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
    try:
        yield
    finally:
        consumer.cancel()
        pref_consumer.cancel()
        try:
            await consumer
        except asyncio.CancelledError:
            pass
        try:
            await pref_consumer
        except asyncio.CancelledError:
            pass
        _log.info("Main app shutting down")
