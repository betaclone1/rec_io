"""Append-only position-risk audit (JSONL + optional Redis stream)."""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

logger = logging.getLogger(__name__)

DEFAULT_AUDIT_DIR = "backend/data/position_risk/audit"
REDIS_STREAM_KEY = os.getenv(
    "REC_POSITION_RISK_AUDIT_STREAM",
    "position_risk:audit",
)
REDIS_STREAM_MAXLEN = int(os.getenv("REC_POSITION_RISK_AUDIT_STREAM_MAXLEN", "20000"))


def _audit_root() -> Path:
    raw = os.getenv("REC_POSITION_RISK_AUDIT_DIR", DEFAULT_AUDIT_DIR)
    p = Path(raw)
    if not p.is_absolute():
        # Prefer repo-relative from CWD; engine usually started from repo root.
        p = Path.cwd() / p
    p.mkdir(parents=True, exist_ok=True)
    return p


def _trade_path(trade_id: int, tenant_slot: Optional[str] = None) -> Path:
    root = _audit_root()
    if tenant_slot:
        return root / f"{tenant_slot}_{int(trade_id)}.jsonl"
    return root / f"{int(trade_id)}.jsonl"


class PositionRiskAudit:
    """Append-only per-trade JSONL; optional Redis XADD fanout."""

    def __init__(self, *, enable_redis: bool = True) -> None:
        self._lock = threading.RLock()
        self._enable_redis = enable_redis
        self._redis = None

    def _redis_client(self):
        if not self._enable_redis:
            return None
        if self._redis is not None:
            return self._redis
        try:
            from backend.core.trading_redis_comms import redis_client_optional

            self._redis = redis_client_optional()
        except Exception as exc:
            logger.debug("position_risk audit redis unavailable: %s", exc)
            self._redis = None
        return self._redis

    def append(
        self,
        event_type: str,
        payload: Dict[str, Any],
        *,
        trade_id: Optional[int] = None,
        tenant_slot: Optional[str] = None,
    ) -> Dict[str, Any]:
        tid = int(trade_id if trade_id is not None else payload.get("trade_id") or 0)
        slot = tenant_slot if tenant_slot is not None else payload.get("tenant_slot")
        event: Dict[str, Any] = {
            "ts": time.time(),
            "ts_ms": int(time.time() * 1000),
            "event_type": str(event_type),
            "trade_id": tid,
            "tenant_slot": slot,
            **payload,
        }
        with self._lock:
            path = _trade_path(tid, str(slot) if slot else None)
            with open(path, "a", encoding="utf-8") as f:
                f.write(json.dumps(event, default=str) + "\n")
            # Also keep a global chronological index for queries without slot.
            idx = _audit_root() / "_all.jsonl"
            with open(idx, "a", encoding="utf-8") as f:
                f.write(json.dumps({"path": str(path.name), **event}, default=str) + "\n")
        self._maybe_xadd(event)
        return event

    def _maybe_xadd(self, event: Dict[str, Any]) -> None:
        r = self._redis_client()
        if r is None:
            return
        try:
            flat = {
                "event_type": str(event.get("event_type") or ""),
                "trade_id": str(event.get("trade_id") or ""),
                "tenant_slot": str(event.get("tenant_slot") or ""),
                "payload": json.dumps(event, default=str),
            }
            r.xadd(
                REDIS_STREAM_KEY,
                flat,
                maxlen=REDIS_STREAM_MAXLEN,
                approximate=True,
            )
        except Exception as exc:
            logger.debug("position_risk audit xadd failed: %s", exc)

    def query_by_trade_id(
        self,
        trade_id: int,
        *,
        tenant_slot: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        tid = int(trade_id)
        events: List[Dict[str, Any]] = []
        with self._lock:
            paths: List[Path] = []
            if tenant_slot:
                paths.append(_trade_path(tid, str(tenant_slot)))
            else:
                root = _audit_root()
                paths.extend(sorted(root.glob(f"*_{tid}.jsonl")))
                paths.append(_trade_path(tid, None))
            seen = set()
            for path in paths:
                if not path.exists() or str(path) in seen:
                    continue
                seen.add(str(path))
                with open(path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            obj = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        if int(obj.get("trade_id") or -1) != tid:
                            continue
                        events.append(obj)
        events.sort(key=lambda e: (float(e.get("ts") or 0), int(e.get("ts_ms") or 0)))
        if limit is not None and limit >= 0:
            return events[-limit:]
        return events

    def latest_actionable_decision(
        self,
        trade_id: int,
        *,
        tenant_slot: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        events = self.query_by_trade_id(trade_id, tenant_slot=tenant_slot)
        for ev in reversed(events):
            if ev.get("event_type") not in ("decision_emit", "pre_decision"):
                continue
            decision = ev.get("decision") or ev
            if decision.get("actionable") is True and not decision.get("shadow_only"):
                return decision
        return None


# Process-wide helper for ATS / engine
_default_audit: Optional[PositionRiskAudit] = None
_default_lock = threading.Lock()


def get_audit() -> PositionRiskAudit:
    global _default_audit
    with _default_lock:
        if _default_audit is None:
            _default_audit = PositionRiskAudit()
        return _default_audit
