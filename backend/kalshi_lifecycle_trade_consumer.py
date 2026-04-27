#!/usr/bin/env python3
"""
Per-tenant consumer: Kalshi ``market_lifecycle_v2`` outcomes → ``users_NNNN.trades_NNNN``.

Primary transport is a durable Redis Stream so brief consumer disconnects do not drop outcomes.
Each tenant process reads the same stream via its own consumer group and applies updates only within
its worker tenant (:envvar:`REC_USER_SCHEMA` / :envvar:`REC_USER_NO`).

Supervisor: one ``kalshi_lifecycle_consumer_<user>`` per trading user with the same ``environment`` as
``trade_manager_<user>`` (not ``env_global``).
"""

from __future__ import annotations

import logging
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")
log = logging.getLogger("kalshi_lifecycle_trade_consumer")


def main() -> int:
    from backend.core.kalshi_lifecycle_trade_outcome import apply_lifecycle_market_result_for_ticker
    from backend.core.tenant_context import get_worker_tenant_context, reset_worker_tenant_context_cache
    from backend.core.trading_redis_comms import (
        default_consumer_name,
        run_stream_consumer_loop,
        stream_kalshi_lifecycle_trades,
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

    stream = stream_kalshi_lifecycle_trades()
    group = f"kalshi_lifecycle_{ctx.user_no}"
    consumer = default_consumer_name(f"kalshi-lifecycle-{ctx.user_no}")
    log.info(
        "starting stream consumer stream=%s group=%s consumer=%s tenant=%s",
        stream,
        group,
        consumer,
        ctx.pg_schema,
    )

    def _handle(fields_decoded, _msg_id, _raw_fields) -> bool:
        if not isinstance(fields_decoded, dict):
            return True
        if fields_decoded.get("type") != "kalshi_lifecycle_trades":
            return True
        payload = fields_decoded.get("payload") or {}
        mt = payload.get("market_ticker")
        if not mt:
            return True
        try:
            apply_lifecycle_market_result_for_ticker(
                str(mt).strip(),
                payload.get("result"),
            )
            return True
        except Exception:
            log.exception("apply_lifecycle_market_result_for_ticker failed ticker=%s", mt)
            # Leave unacked so stream replay can retry after transient failures.
            return False

    run_stream_consumer_loop(
        stream=stream,
        group=group,
        consumer=consumer,
        handler=_handle,
        block_ms=5000,
        stop_event=None,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
