"""Per-position PROTECTED leases and heartbeats (observe-only)."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional

from backend.core.position_risk.enroll import EnrolledPosition


class ProtectionState(str, Enum):
    ENROLLING = "ENROLLING"
    PROTECTED = "PROTECTED"
    DEGRADED = "DEGRADED"
    RESYNCING = "RESYNCING"
    UNCOVERED = "UNCOVERED"  # watchdog-only: TM open without lease


@dataclass
class PositionLease:
    key: str
    tenant_slot: str
    trade_id: int
    ticker: str
    state: ProtectionState
    enrolled_mono: float
    protected_mono: Optional[float] = None
    last_heartbeat_mono: Optional[float] = None
    last_feature_mono: Optional[float] = None
    last_seq: Optional[int] = None
    enroll_latency_ms: Optional[float] = None
    reason: str = ""

    def heartbeat(self, *, reason: str = "ok") -> None:
        now = time.monotonic()
        self.last_heartbeat_mono = now
        if self.state == ProtectionState.ENROLLING:
            self.state = ProtectionState.PROTECTED
            self.protected_mono = now
            if self.enroll_latency_ms is None:
                self.enroll_latency_ms = (now - self.enrolled_mono) * 1000.0
        if self.state in (ProtectionState.DEGRADED, ProtectionState.RESYNCING) and reason == "ok":
            self.state = ProtectionState.PROTECTED
        self.reason = reason

    def mark_degraded(self, reason: str) -> None:
        self.state = ProtectionState.DEGRADED
        self.reason = reason
        self.last_heartbeat_mono = time.monotonic()

    def mark_resyncing(self, reason: str) -> None:
        self.state = ProtectionState.RESYNCING
        self.reason = reason
        self.last_heartbeat_mono = time.monotonic()


class LeaseRegistry:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._leases: Dict[str, PositionLease] = {}

    def reconcile(self, positions: List[EnrolledPosition]) -> Dict[str, PositionLease]:
        """Deterministic enroll/re-enroll from TM open set; drop closed keys."""
        with self._lock:
            now = time.monotonic()
            wanted = {p.key(): p for p in positions}
            for key in list(self._leases.keys()):
                if key not in wanted:
                    del self._leases[key]
            for key, pos in wanted.items():
                if key not in self._leases:
                    self._leases[key] = PositionLease(
                        key=key,
                        tenant_slot=pos.tenant_slot,
                        trade_id=pos.trade_id,
                        ticker=pos.ticker,
                        state=ProtectionState.ENROLLING,
                        enrolled_mono=now,
                        reason="enrolling",
                    )
                else:
                    # Keep lease; refresh ticker if rotated (should not)
                    self._leases[key].ticker = pos.ticker
            return dict(self._leases)

    def get(self, key: str) -> Optional[PositionLease]:
        with self._lock:
            return self._leases.get(key)

    def all(self) -> List[PositionLease]:
        with self._lock:
            return list(self._leases.values())

    def snapshot(self) -> List[dict]:
        with self._lock:
            out = []
            now = time.monotonic()
            for lease in self._leases.values():
                out.append(
                    {
                        "key": lease.key,
                        "tenant_slot": lease.tenant_slot,
                        "trade_id": lease.trade_id,
                        "ticker": lease.ticker,
                        "state": lease.state.value,
                        "enroll_latency_ms": lease.enroll_latency_ms,
                        "heartbeat_age_ms": (
                            None
                            if lease.last_heartbeat_mono is None
                            else (now - lease.last_heartbeat_mono) * 1000.0
                        ),
                        "feature_age_ms": (
                            None
                            if lease.last_feature_mono is None
                            else (now - lease.last_feature_mono) * 1000.0
                        ),
                        "last_seq": lease.last_seq,
                        "reason": lease.reason,
                    }
                )
            return out
