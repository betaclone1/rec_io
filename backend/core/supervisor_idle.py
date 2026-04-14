"""Keep supervisor-managed workers alive when they have no work yet (empty monitor pool)."""

from __future__ import annotations

import logging
import time
from typing import Callable


def idle_forever_for_supervisor(
    reason: str,
    *,
    log: Callable[[str], None] | None = None,
    logger: logging.Logger | None = None,
) -> None:
    """
    Block forever with periodic sleep so supervisord sees a long-lived process.

    Use when a tenant-scoped unified AES/ATS has zero active monitors but should
    still stay RUNNING until monitors are added (or until SIGTERM).
    """
    msg = f"{reason}; sleeping idle hourly until SIGTERM"
    if logger is not None:
        logger.info("%s", msg)
    elif log is not None:
        log(msg)
    while True:
        time.sleep(3600)
