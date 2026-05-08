"""main_app logger: EST timestamp, flush stdout, single handler for supervisor capture."""

import logging
import sys
from zoneinfo import ZoneInfo as _main_tz


def _main_est_formatter():
    class _ESTF(logging.Formatter):
        def formatTime(self, record, datefmt=None):
            from datetime import datetime

            dt = datetime.fromtimestamp(record.created, tz=_main_tz("America/New_York"))
            s = dt.strftime("%Y-%m-%dT%H:%M:%S")
            z = dt.strftime("%z")
            return s + (z[:3] + ":" + z[3:] if len(z) >= 5 else z)

    return _ESTF(fmt="%(asctime)s %(levelname)s [%(name)s] %(message)s")


class _MainFlushHandler(logging.StreamHandler):
    def emit(self, record):
        super().emit(record)
        self.flush()


def get_main_app_logger() -> logging.Logger:
    logr = logging.getLogger("main_app")
    if logr.handlers:
        return logr
    h = _MainFlushHandler(sys.stdout)
    h.setFormatter(_main_est_formatter())
    logr.addHandler(h)
    logr.setLevel(logging.INFO)
    return logr
