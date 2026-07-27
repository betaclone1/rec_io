"""
Long-running worker: package closed cycle hot tables on a UTC hourly schedule.

Supervisor program: ``cycle_packager``.
"""

from __future__ import annotations

import logging
import os
import sys
import time
from datetime import datetime, timezone

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [cycle_packager] %(message)s",
)
log = logging.getLogger("cycle_packager")


def _env_first(*names: str, default: str = "") -> str:
    for name in names:
        raw = os.getenv(name)
        if raw is not None and str(raw).strip() != "":
            return str(raw).strip()
    return default


def _sleep_until_next_hour_utc(*, minute: int = 5) -> None:
    """Wake at HH:{minute}:00 UTC (default :05 so cycles have grace after :00)."""
    from datetime import timedelta

    now = datetime.now(timezone.utc)
    target_min = max(0, min(59, int(minute)))
    target = now.replace(minute=target_min, second=0, microsecond=0)
    if target <= now:
        target = target + timedelta(hours=1)
    wait = max(1.0, (target - now).total_seconds())
    log.info("sleeping %.0fs until %s", wait, target.isoformat())
    time.sleep(wait)


def main() -> int:
    from backend.core.cycle_packager import package_due_cycles, package_root

    minute = int(
        _env_first(
            "CYCLE_PACKAGE_UTC_MINUTE",
            "BTC15M_CYCLE_PACKAGE_UTC_MINUTE",
            default="5",
        )
    )
    run_once = _env_first(
        "CYCLE_PACKAGE_ONCE", "BTC15M_CYCLE_PACKAGE_ONCE", default=""
    ).lower() in ("1", "true", "yes")
    log.info("starting package_root=%s utc_minute=%s", package_root(), minute)

    while True:
        if not run_once:
            _sleep_until_next_hour_utc(minute=minute)
        try:
            done = package_due_cycles()
            if done:
                log.info("packaged %s cycle(s)", len(done))
                for p in done:
                    log.info("  %s (%.1f KB)", p, p.stat().st_size / 1024.0)
            else:
                log.info("no cycles ready to package")
        except Exception:
            log.exception("package_due_cycles failed")
        if run_once:
            return 0


if __name__ == "__main__":
    sys.exit(main())
