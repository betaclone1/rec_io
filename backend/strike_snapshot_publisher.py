"""
Publish shared strike ladder snapshots to Redis once per wall-clock second.

Aligns the start of each publish cycle to the next integer second so all AES processes
can read the same payload for a given ``wall_second`` when they pull from Redis.

Run under supervisor as ``strike_snapshot_publisher``.
"""

from __future__ import annotations

import logging
import os
import sys
import time

from backend.core.exchange_ids import DEFAULT_EXCHANGE
from backend.core.strike_ladder_fetch import fetch_strike_ladder_prefer_snapshot
from backend.core.strike_snapshot_redis import publish_strike_snapshot, redis_client_optional

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [strike_snapshot_publisher] %(message)s",
)
log = logging.getLogger("strike_snapshot_publisher")


def _sleep_until_next_second_boundary() -> None:
    t = time.time()
    frac = t % 1.0
    if frac < 0.001:
        return
    time.sleep(1.0 - frac)


def _discover_symbols() -> list[str]:
    """Strike snapshots follow symbols at live_data_level=full."""
    from backend.core.live_data_level import full_package_symbols
    from backend.core.market_watchdog.venues.kalshi.schedule import SERIES_15M_BY_SYMBOL

    rows = [s for s in full_package_symbols() if s in SERIES_15M_BY_SYMBOL]
    if not rows:
        log.warning("no symbols at live_data_level=full for strike snapshots")
    return rows


def _markets() -> list[str]:
    raw = os.getenv("STRIKE_SNAPSHOT_MARKETS", "hourly,15m").strip().lower()
    out = []
    for p in raw.split(","):
        p = p.strip()
        if p in ("hourly", "15m"):
            out.append(p)
    return out if out else ["hourly", "15m"]


def main() -> int:
    r = redis_client_optional()
    if not r:
        log.error("Redis unavailable; strike_snapshot_publisher exiting")
        return 1

    ex = os.getenv("STRIKE_SNAPSHOT_EXCHANGE", DEFAULT_EXCHANGE).strip().lower() or DEFAULT_EXCHANGE
    symbols = _discover_symbols()
    markets = _markets()
    log.info(
        "starting exchange=%s symbols=%s markets=%s",
        ex,
        symbols,
        markets,
    )

    generation_seq = 0
    while True:
        _sleep_until_next_second_boundary()
        wall_second = int(time.time())
        generation_seq += 1
        for sym in symbols:
            for mkt in markets:
                payload = fetch_strike_ladder_prefer_snapshot(sym, mkt, ex)
                if not payload:
                    continue

                ok = publish_strike_snapshot(
                    r,
                    exchange=ex,
                    market=mkt,
                    symbol=sym,
                    generation_seq=generation_seq,
                    wall_second=wall_second,
                    db_header_timestamp=None,
                    data=payload,
                )
                if ok:
                    try:
                        from backend.historical_strike_table_archive import (
                            append_strike_archive_for_published_ladder,
                        )

                        append_strike_archive_for_published_ladder(
                            exchange=ex,
                            market=mkt,
                            wall_second=wall_second,
                            generation_seq=generation_seq,
                            ladder=payload,
                        )
                    except Exception as arch_exc:
                        log.warning(
                            "historical strike archive after publish failed sym=%s market=%s: %s",
                            sym,
                            mkt,
                            arch_exc,
                        )
                    try:
                        from backend.core.cycle_hot_tables import (
                            enqueue_strike_ladder_rows,
                        )

                        enqueue_strike_ladder_rows(
                            wall_second=wall_second,
                            ladder=payload,
                            market=mkt,
                            symbol=sym,
                        )
                    except Exception as cycle_exc:
                        log.warning(
                            "btc15m cycle strike append failed sym=%s market=%s: %s",
                            sym,
                            mkt,
                            cycle_exc,
                        )


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        sys.exit(0)
