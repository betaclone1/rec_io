"""
Long-running worker: catch up Kalshi public-trade day CSVs + market results,
package by asset/month, upload to Google Drive.

Supervisor program: ``public_trades_drive_sync``.

Isolation: no Redis, no monitors, no tenant trading DML. Public REST + disk + Drive only.
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import datetime, timezone

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [public_trades_drive_sync] %(message)s",
    force=True,
)
for _h in logging.root.handlers:
    try:
        if hasattr(_h, "stream") and hasattr(_h.stream, "reconfigure"):
            _h.stream.reconfigure(line_buffering=True)
    except Exception:
        pass
log = logging.getLogger("public_trades_drive_sync")


def main(argv: list[str] | None = None) -> int:
    from backend.core.public_trades_drive_sync import (
        interval_sec,
        run_once,
        sync_enabled,
    )

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--once", action="store_true", help="Single wake then exit")
    ap.add_argument("--dry-run-upload", action="store_true")
    ap.add_argument("--skip-trades", action="store_true")
    ap.add_argument("--skip-results", action="store_true")
    ap.add_argument("--skip-package", action="store_true")
    ap.add_argument("--skip-upload", action="store_true")
    ap.add_argument(
        "--skip-score",
        action="store_true",
        help="Skip upsert into historical_data.*_tail_backtest_cycles",
    )
    ap.add_argument("--lookback-days", type=int, default=None)
    ap.add_argument("--workers", type=int, default=None)
    ap.add_argument("--series", nargs="+", default=None)
    ap.add_argument(
        "--backfill-local-months",
        action="store_true",
        help="Package+upload every month that already has day CSVs on disk (seed Drive)",
    )
    args = ap.parse_args(argv)

    interval = interval_sec()
    log.info(
        "starting interval_sec=%.0f once=%s dry_run_upload=%s",
        interval,
        args.once,
        args.dry_run_upload,
    )

    while True:
        if not sync_enabled():
            if args.once:
                log.error(
                    "PUBLIC_TRADES_DRIVE_SYNC disabled / Drive OAuth missing; exit"
                )
                return 1
            log.warning(
                "sync disabled or Drive OAuth missing; sleeping %.0fs",
                interval,
            )
            time.sleep(interval)
            continue

        started = time.monotonic()
        try:
            rc = run_once(
                series=args.series,
                lookback=args.lookback_days,
                workers=args.workers,
                dry_run_upload=args.dry_run_upload,
                skip_trades=args.skip_trades,
                skip_results=args.skip_results,
                skip_package=args.skip_package,
                skip_upload=args.skip_upload,
                skip_score=args.skip_score,
                backfill_local_months=args.backfill_local_months,
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
