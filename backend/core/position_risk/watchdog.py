"""Independent local watchdog for uncovered positions, stalls, book/Redis trouble."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import List, Optional, Set

from backend.core.position_risk.enroll import EnrolledPosition
from backend.core.position_risk.lease import LeaseRegistry, ProtectionState


@dataclass
class WatchdogAlarm:
    severity: str  # info|warn|critical
    code: str
    message: str
    mono: float = field(default_factory=time.monotonic)
    key: Optional[str] = None


class ProtectionWatchdog:
    def __init__(
        self,
        leases: LeaseRegistry,
        *,
        heartbeat_stall_ms: float = 750.0,
        critical_stall_ms: float = 2000.0,
        uncovered_critical_ms: float = 1000.0,
    ) -> None:
        self.leases = leases
        self.heartbeat_stall_ms = heartbeat_stall_ms
        self.critical_stall_ms = critical_stall_ms
        self.uncovered_critical_ms = uncovered_critical_ms
        self._lock = threading.RLock()
        self._alarms: List[WatchdogAlarm] = []
        self._seen_open_mono: dict[str, float] = {}
        self._redis_ok = True
        self._last_redis_error: Optional[str] = None

    def note_redis(self, ok: bool, error: Optional[str] = None) -> None:
        with self._lock:
            self._redis_ok = ok
            self._last_redis_error = error
            if not ok:
                self._alarms.append(
                    WatchdogAlarm(
                        "critical",
                        "redis_trouble",
                        error or "redis unavailable",
                    )
                )

    def evaluate(self, open_positions: List[EnrolledPosition]) -> List[WatchdogAlarm]:
        now = time.monotonic()
        fresh: List[WatchdogAlarm] = []
        open_keys = {p.key() for p in open_positions}
        with self._lock:
            for key in list(self._seen_open_mono.keys()):
                if key not in open_keys:
                    del self._seen_open_mono[key]
            for pos in open_positions:
                key = pos.key()
                self._seen_open_mono.setdefault(key, now)
                lease = self.leases.get(key)
                if lease is None:
                    age_ms = (now - self._seen_open_mono[key]) * 1000.0
                    sev = "critical" if age_ms >= self.uncovered_critical_ms else "warn"
                    fresh.append(
                        WatchdogAlarm(
                            sev,
                            "uncovered_open_hws",
                            f"TM open HWS without lease age_ms={age_ms:.0f}",
                            key=key,
                        )
                    )
                    continue
                if lease.last_heartbeat_mono is None:
                    fresh.append(
                        WatchdogAlarm(
                            "warn",
                            "actor_no_heartbeat",
                            "lease enrolled but never heartbeated",
                            key=key,
                        )
                    )
                    continue
                stall = (now - lease.last_heartbeat_mono) * 1000.0
                if stall >= self.critical_stall_ms:
                    fresh.append(
                        WatchdogAlarm(
                            "critical",
                            "actor_stall",
                            f"heartbeat stall_ms={stall:.0f}",
                            key=key,
                        )
                    )
                elif stall >= self.heartbeat_stall_ms:
                    fresh.append(
                        WatchdogAlarm(
                            "warn",
                            "actor_stall",
                            f"heartbeat stall_ms={stall:.0f}",
                            key=key,
                        )
                    )
                if lease.state in (ProtectionState.DEGRADED, ProtectionState.RESYNCING):
                    fresh.append(
                        WatchdogAlarm(
                            "warn",
                            f"lease_{lease.state.value.lower()}",
                            lease.reason or lease.state.value,
                            key=key,
                        )
                    )
            if not self._redis_ok:
                fresh.append(
                    WatchdogAlarm(
                        "critical",
                        "redis_trouble",
                        self._last_redis_error or "redis unavailable",
                    )
                )
            self._alarms = (self._alarms + fresh)[-200:]
        return fresh

    def recent_alarms(self, limit: int = 50) -> List[dict]:
        with self._lock:
            return [
                {
                    "severity": a.severity,
                    "code": a.code,
                    "message": a.message,
                    "key": a.key,
                    "age_ms": (time.monotonic() - a.mono) * 1000.0,
                }
                for a in self._alarms[-limit:]
            ]
