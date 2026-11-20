"""
Long-running worker: keep recent public-trade day CSVs + tail cycle/rolling
scores current (incremental hourly). Optional archive mode packages months
and uploads to Google Drive.

Supervisor program: ``public_trades_drive_sync``.

Isolation: no Redis, no monitors, no tenant trading DML. Public REST + disk
(+ Drive only when archive mode is on).
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
        archive_mode_enabled,
        hours_back,
        interval_sec,
        min_idle_sec,
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
    ap.add_argument(
        "--hours-back",
        type=float,
        default=None,
        help="Incremental window hours (default PUBLIC_TRADES_DRIVE_SYNC_HOURS_BACK / 2)",
    )
    ap.add_argument(
        "--archive",
        action="store_true",
        help="Full-day catchup + month package + Drive upload (heavy)",
    )
    ap.add_argument("--lookback-days", type=int, default=None, help="Archive-mode day lookback")
    ap.add_argument("--workers", type=int, default=None)
    ap.add_argument("--series", nargs="+", default=None)
    ap.add_argument(
        "--backfill-local-months",
        action="store_true",
        help="Package+upload every month that already has day CSVs on disk (seed Drive)",
    )
    args = ap.parse_args(argv)

    interval = interval_sec()
    idle_floor = min_idle_sec()
    mode = "archive" if (args.archive or archive_mode_enabled() or args.backfill_local_months) else "incremental"
    log.info(
        "starting mode=%s interval_sec=%.0f min_idle_sec=%.0f hours_back=%s once=%s",
        mode,
        interval,
        idle_floor,
        args.hours_back if args.hours_back is not None else hours_back(),
        args.once,
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
                hours=args.hours_back,
                workers=args.workers,
                dry_run_upload=args.dry_run_upload,
                skip_trades=args.skip_trades,
                skip_results=args.skip_results,
                skip_package=args.skip_package,
                skip_upload=args.skip_upload,
                skip_score=args.skip_score,
                backfill_local_months=args.backfill_local_months,
                archive=True if args.archive else None,
            )
            log.info("wake rc=%s at %s", rc, datetime.now(timezone.utc).isoformat())
        except Exception:
            log.exception("wake failed")
            rc = 1
        if args.once:
            return rc
        elapsed = time.monotonic() - started
        # Floor idle so a slow wake cannot tight-loop and pin CPU.
        wait = max(idle_floor, interval - elapsed)
        log.info(
            "sleeping %.0fs until next wake (elapsed=%.0fs floor=%.0fs)",
            wait,
            elapsed,
            idle_floor,
        )
        time.sleep(wait)


if __name__ == "__main__":
    sys.exit(main())
