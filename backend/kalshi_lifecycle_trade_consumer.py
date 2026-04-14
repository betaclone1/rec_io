#!/usr/bin/env python3
"""
Per-tenant consumer: Kalshi ``market_lifecycle_v2`` outcomes → ``users_NNNN.trades_NNNN``.

Subscribe to :func:`backend.core.trading_redis_comms.channel_kalshi_lifecycle_trades` and call
:func:`backend.core.kalshi_lifecycle_trade_outcome.apply_lifecycle_market_result_for_ticker`
using this process's worker tenant (:envvar:`REC_USER_SCHEMA` / :envvar:`REC_USER_NO`).

Supervisor: one ``kalshi_lifecycle_consumer_<user>`` per trading user with the same ``environment`` as
``trade_manager_<user>`` (not ``env_global``).
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")
log = logging.getLogger("kalshi_lifecycle_trade_consumer")


def main() -> int:
    from backend.core.kalshi_lifecycle_trade_outcome import apply_lifecycle_market_result_for_ticker
    from backend.core.tenant_context import get_worker_tenant_context, reset_worker_tenant_context_cache
    from backend.core.trading_redis_comms import (
        channel_kalshi_lifecycle_trades,
        redis_connect_uncached,
        use_trading_redis_comms,
    )

    reset_worker_tenant_context_cache()
    try:
        ctx = get_worker_tenant_context()
    except Exception as e:
        log.error("tenant context required (REC_USER_SCHEMA or REC_USER_NO): %s", e)
        return 1

    if not use_trading_redis_comms():
        log.error("USE_TRADING_REDIS_COMMS must be enabled for lifecycle fan-out")
        return 1

    ch = channel_kalshi_lifecycle_trades()

    def _connect():
        r = redis_connect_uncached()
        if not r:
            return None, None
        ps = r.pubsub()
        ps.subscribe(ch)
        log.info("subscribed channel=%s tenant=%s", ch, ctx.pg_schema)
        return r, ps

    r, pubsub = _connect()
    if not r or not pubsub:
        log.error("Redis unavailable")
        return 1

    try:
        while True:
            msg = pubsub.get_message(timeout=30.0)
            if msg is None:
                try:
                    r.ping()
                except Exception:
                    log.warning("redis ping failed; reconnecting")
                    try:
                        pubsub.close()
                    except Exception:
                        pass
                    try:
                        r.close()
                    except Exception:
                        pass
                    time.sleep(2.0)
                    r, pubsub = _connect()
                    if not r or not pubsub:
                        time.sleep(5.0)
                    continue
                continue
            if msg.get("type") != "message":
                continue
            raw = msg.get("data")
            if not raw:
                continue
            try:
                body = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if body.get("type") != "kalshi_lifecycle_trades":
                continue
            mt = body.get("market_ticker")
            res = body.get("result")
            if not mt:
                continue
            try:
                apply_lifecycle_market_result_for_ticker(str(mt).strip(), res)
            except Exception:
                log.exception("apply_lifecycle_market_result_for_ticker failed ticker=%s", mt)
    finally:
        try:
            pubsub.close()
        except Exception:
            pass
        try:
            r.close()
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
