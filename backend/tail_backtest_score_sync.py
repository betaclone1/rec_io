"""
Long-running worker: exact-cent LT/UT cycle scoring + rolling rates + symbols_list scores.

Supervisor program: ``tail_backtest_score_sync``.

Isolation: no Redis, no monitors, no tenant trading DML, no Drive archive/upload.
May lightly refresh day CSVs + market-result cache for the lookback window.
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import datetime, timezone

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [tail_backtest_score_sync] %(message)s",
    force=True,
)
for _h in logging.root.handlers:
    try:
        if hasattr(_h, "stream") and hasattr(_h.stream, "reconfigure"):
            _h.stream.reconfigure(line_buffering=True)
    except Exception:
        pass
log = logging.getLogger("tail_backtest_score_sync")


def main(argv: list[str] | None = None) -> int:
    from backend.core.tail_backtest_score_sync import (
        interval_sec,
        run_once,
        sync_enabled,
    )

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--once", action="store_true", help="Single wake then exit")
    ap.add_argument("--skip-trades", action="store_true")
    ap.add_argument("--skip-results", action="store_true")
    ap.add_argument("--lookback-days", type=int, default=None)
    ap.add_argument("--workers", type=int, default=None)
    ap.add_argument("--series", nargs="+", default=None)
    args = ap.parse_args(argv)

    interval = interval_sec()
    log.info(
        "starting interval_sec=%.0f once=%s",
        interval,
        args.once,
    )

    while True:
        if not sync_enabled():
            if args.once:
                log.error("TAIL_BACKTEST_SCORE_SYNC disabled; exit")
                return 1
            log.warning("score sync disabled; sleeping %.0fs", interval)
            time.sleep(interval)
            continue

        started = time.monotonic()
        try:
            rc = run_once(
                series=args.series,
                lookback=args.lookback_days,
                workers=args.workers,
                skip_trades=args.skip_trades,
                skip_results=args.skip_results,
            )
            log.info("wake rc=%s at %s", rc, datetime.now(timezone.utc).isoformat())
        except Exception:
            log.exception("wake failed")
            rc = 1
        if args.once:
            return rc
        elapsed = time.monotonic() - started
        wait = max(1.0, interval - elapsed)
        log.info("sleeping %.0fs until next wake", wait)
        time.sleep(wait)


if __name__ == "__main__":
    sys.exit(main())
