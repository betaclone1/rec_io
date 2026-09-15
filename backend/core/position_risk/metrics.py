"""Latency / resource histograms for Stage 1 observation."""

from __future__ import annotations

import threading
import time
from collections import defaultdict
from typing import Dict, List, Optional


def percentile(sorted_vals: List[float], p: float) -> Optional[float]:
    if not sorted_vals:
        return None
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    k = (len(sorted_vals) - 1) * (p / 100.0)
    f = int(k)
    c = min(f + 1, len(sorted_vals) - 1)
    if f == c:
        return sorted_vals[f]
    return sorted_vals[f] + (sorted_vals[c] - sorted_vals[f]) * (k - f)


class LatencyTracker:
    def __init__(self, max_samples: int = 5000) -> None:
        self._lock = threading.RLock()
        self._samples: Dict[str, List[float]] = defaultdict(list)
        self._max = max_samples
        self._started = time.time()

    def record(self, name: str, ms: float) -> None:
        with self._lock:
            buf = self._samples[name]
            buf.append(float(ms))
            if len(buf) > self._max:
                del buf[: len(buf) - self._max]

    def summary(self) -> Dict[str, dict]:
        with self._lock:
            out = {}
            for name, vals in self._samples.items():
                s = sorted(vals)
                out[name] = {
                    "n": len(s),
                    "p50_ms": percentile(s, 50),
                    "p95_ms": percentile(s, 95),
                    "p99_ms": percentile(s, 99),
                    "max_ms": s[-1] if s else None,
                }
            return out
