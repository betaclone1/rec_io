"""
Long-running worker: package closed cycle hot tables until every due cycle seals.

Supervisor program: ``cycle_packager``.

Wakes on a short backlog interval (default 5 min) so transient Kalshi delays /
429s / late settlement never leave cycles abandoned for an hour. Each wake runs
``package_due_cycles`` with multi-pass retries. Hot tables stay until seal.
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


def _backlog_interval_sec() -> float:
    """Seconds between packager wakes. Keep short — deferred seals must drain."""
    try:
        raw = _env_first(
            "CYCLE_PACKAGE_INTERVAL_SEC",
            "BTC15M_CYCLE_PACKAGE_INTERVAL_SEC",
            default="300",
        )
        return max(30.0, float(raw))
    except (TypeError, ValueError):
        return 300.0


def main() -> int:
    from backend.core.cycle_packager import package_due_cycles, package_root

    interval = _backlog_interval_sec()
    run_once = _env_first(
        "CYCLE_PACKAGE_ONCE", "BTC15M_CYCLE_PACKAGE_ONCE", default=""
    ).lower() in ("1", "true", "yes")
    # Legacy hourly-minute knob: if set and INTERVAL not set, keep old cadence
    # only when explicitly requesting hour-aligned wakes via INTERVAL>=3600.
    legacy_minute = _env_first(
        "CYCLE_PACKAGE_UTC_MINUTE",
        "BTC15M_CYCLE_PACKAGE_UTC_MINUTE",
        default="",
    )
    log.info(
        "starting package_root=%s interval_sec=%.0f legacy_utc_minute=%s",
        package_root(),
        interval,
        legacy_minute or "(unused)",
    )

    while True:
        started = time.monotonic()
        try:
            done = package_due_cycles()
            if done:
                log.info("packaged %s cycle(s)", len(done))
                for p in done:
                    log.info("  %s (%.1f KB)", p, p.stat().st_size / 1024.0)
            else:
                log.info("no cycles sealed this wake (%s)", datetime.now(timezone.utc).isoformat())
        except Exception:
            log.exception("package_due_cycles failed")
        if run_once:
            return 0
        elapsed = time.monotonic() - started
        wait = max(1.0, interval - elapsed)
        log.info("sleeping %.0fs until next backlog wake", wait)
        time.sleep(wait)


if __name__ == "__main__":
    sys.exit(main())
