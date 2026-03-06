"""
Optional runtime measurement: fraction of CPU time spent in stdout write/flush (logging).

Enable with: MEASURE_LOG_CPU=1

When enabled, wraps sys.stdout so that time spent in write() and flush() is tracked.
Every 60 seconds a one-line summary is written to stderr, e.g.:
  LOG_CPU_MEASURE: 0.03  (3% of process CPU time was in logging)

Use this to see how much of symbol_price_watchdog / auto_entry_supervisor CPU is
from writing logs vs real work. Safe to leave disabled (no overhead).
"""

import os
import sys
import threading
import time


def install_stdout_timer(interval_seconds: int = 60):
    """Wrap sys.stdout to measure time spent in write/flush. Reports to stderr every interval_seconds."""
    if getattr(sys.stdout, "_log_cpu_timer_installed", False):
        return

    real_stdout = sys.stdout
    total_log_time = [0.0]  # list so closure can mutate
    last_report_time = [time.perf_counter()]

    class TimingStdout:
        _log_cpu_timer_installed = True

        def write(self, s):
            t0 = time.perf_counter()
            try:
                return real_stdout.write(s)
            finally:
                total_log_time[0] += time.perf_counter() - t0

        def flush(self):
            t0 = time.perf_counter()
            try:
                return real_stdout.flush()
            finally:
                total_log_time[0] += time.perf_counter() - t0

        def __getattr__(self, name):
            return getattr(real_stdout, name)

    sys.stdout = TimingStdout()

    def report_loop():
        while True:
            time.sleep(interval_seconds)
            now = time.perf_counter()
            elapsed = now - last_report_time[0]
            last_report_time[0] = now
            log_time = total_log_time[0]
            total_log_time[0] = 0.0
            if elapsed > 0 and log_time >= 0:
                pct = log_time / elapsed
                try:
                    sys.__stderr__.write(f"LOG_CPU_MEASURE: {pct:.4f}\n")
                    sys.__stderr__.flush()
                except Exception:
                    pass

    t = threading.Thread(target=report_loop, daemon=True)
    t.start()
