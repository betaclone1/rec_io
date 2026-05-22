"""
Redis hot-path store for open-position operational state (active_trades).

Canonical history remains ``users.trades_*`` in PostgreSQL.
See docs/live-data-architecture/live_state_cache_model.md.
"""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import date, datetime, time as time_type
from decimal import Decimal
from typing import Any, Dict, List, Optional, Sequence, Tuple

from backend.core.live_state_cache import (
    KEY_PREFIX,
    TTL_SEC,
    _json_default,
    redis_client_optional,
)
from backend.core.live_state_config import live_state_cache_enabled
from backend.trading_mode import _norm_slot

logger = logging.getLogger(__name__)

_TRACKED_STATUSES = frozenset({"active", "pending", "closing"})


def live_state_active_trades_enabled() -> bool:
    """Hot-path pool in Redis when live_state is on (default on)."""
    if not live_state_cache_enabled():
        return False
    raw = os.getenv("LIVE_STATE_ACTIVE_TRADES_ENABLED", "1").strip().lower()
    return raw in ("1", "true", "yes", "on")


def active_trades_pg_dual_write() -> bool:
    """When Redis is on, still mirror enroll/remove to PG pool tables (cutover safety)."""
    if not live_state_active_trades_enabled():
        return True
    raw = os.getenv("LIVE_STATE_ACTIVE_TRADES_PG_DUAL_WRITE", "0").strip().lower()
    return raw in ("1", "true", "yes", "on")


def tenant_active_trades_key(user_no: str) -> str:
    slot = _norm_slot(str(user_no))
    return f"{KEY_PREFIX}:tenant:{slot}:active_trades"


def _serialize_value(value: Any) -> Any:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if hasattr(value, "__float__") and not isinstance(value, (bool, int, float)):
        try:
            return float(value)
        except (TypeError, ValueError):
            pass
    return value


def normalize_trade_record(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize a trade dict for API / monitoring consumers."""
    out: Dict[str, Any] = {}
    for k, v in raw.items():
        out[k] = _serialize_value(v)
    tid = out.get("trade_id")
    if tid is not None:
        try:
            out["trade_id"] = int(tid)
        except (TypeError, ValueError):
            pass
    st = str(out.get("status") or "active").strip().lower()
    if not st:
        st = "active"
    out["status"] = st
    return out


def _publish_active_trades_updated(user_no: str, *, detail: str = "full") -> None:
    from backend.core.live_state_cache import UPDATED_CHANNEL

    r = redis_client_optional()
    if not r:
        return
    key = tenant_active_trades_key(user_no)
    try:
        msg = json.dumps(
            {
                "type": "live_state_updated",
                "kind": "active_trades",
                "key": key,
                "detail": str(detail or "full"),
            }
        )
        r.publish(UPDATED_CHANNEL, msg)
    except Exception as exc:
        logger.debug("active_trades publish failed: %s", exc)


def upsert_trade(user_no: str, trade: Dict[str, Any], *, publish: bool = True) -> bool:
    """Insert or replace one open-position record by trade_id."""
    if not live_state_active_trades_enabled():
        return False
    r = redis_client_optional()
    if not r:
        return False
    rec = normalize_trade_record(dict(trade))
    tid = rec.get("trade_id")
    if tid is None:
        return False
    now = datetime.utcnow().isoformat() + "Z"
    rec.setdefault("last_updated", now)
    rec.setdefault("created_at", rec.get("created_at") or now)
    key = tenant_active_trades_key(user_no)
    field = str(int(tid))
    try:
        r.hset(key, field, json.dumps(rec, default=_json_default))
        r.expire(key, TTL_SEC)
        if publish:
            _publish_active_trades_updated(user_no)
        return True
    except Exception as exc:
        logger.warning("active_trades upsert failed trade_id=%s: %s", tid, exc)
        return False


def update_trade_fields(
    user_no: str,
    trade_id: int,
    fields: Dict[str, Any],
    *,
    publish: bool = True,
) -> bool:
    """Merge monitoring fields into an existing record."""
    if not live_state_active_trades_enabled():
        return False
    existing = get_trade(user_no, trade_id)
    if not existing:
        return False
    existing.update({k: _serialize_value(v) for k, v in fields.items()})
    existing["last_updated"] = datetime.utcnow().isoformat() + "Z"
    return upsert_trade(user_no, existing, publish=publish)


def remove_trade(user_no: str, trade_id: int, *, publish: bool = True) -> bool:
    if not live_state_active_trades_enabled():
        return False
    r = redis_client_optional()
    if not r:
        return False
    key = tenant_active_trades_key(user_no)
    try:
        r.hdel(key, str(int(trade_id)))
        if publish:
            _publish_active_trades_updated(user_no)
        return True
    except Exception as exc:
        logger.warning("active_trades remove failed trade_id=%s: %s", trade_id, exc)
        return False


def get_trade(user_no: str, trade_id: int) -> Optional[Dict[str, Any]]:
    if not live_state_active_trades_enabled():
        return None
    r = redis_client_optional()
    if not r:
        return None
    raw = r.hget(tenant_active_trades_key(user_no), str(int(trade_id)))
    if not raw:
        return None
    try:
        data = json.loads(raw)
        return normalize_trade_record(data) if isinstance(data, dict) else None
    except json.JSONDecodeError:
        return None


def _status_ok(status: Optional[str], allowed: Sequence[str]) -> bool:
    st = str(status or "active").strip().lower() or "active"
    return st in allowed


def list_trades(
    user_no: str,
    *,
    monitor_id: Optional[str] = None,
    statuses: Optional[Sequence[str]] = None,
) -> List[Dict[str, Any]]:
    if not live_state_active_trades_enabled():
        return []
    r = redis_client_optional()
    if not r:
        return []
    allowed = tuple(statuses) if statuses else tuple(_TRACKED_STATUSES)
    try:
        raw_map = r.hgetall(tenant_active_trades_key(user_no)) or {}
    except Exception as exc:
        logger.debug("active_trades list failed: %s", exc)
        return []
    out: List[Dict[str, Any]] = []
    mid_filter = str(monitor_id).strip() if monitor_id is not None else None
    for _field, blob in raw_map.items():
        try:
            rec = normalize_trade_record(json.loads(blob))
        except (json.JSONDecodeError, TypeError):
            continue
        if not _status_ok(rec.get("status"), allowed):
            continue
        if mid_filter is not None and str(rec.get("monitor_id") or "").strip() != mid_filter:
            continue
        out.append(rec)

    def _sort_key(d: Dict[str, Any]) -> str:
        return str(d.get("created_at") or "")

    out.sort(key=_sort_key, reverse=True)
    return out


def count_tracked(
    user_no: str,
    *,
    monitor_id: Optional[str] = None,
    statuses: Optional[Sequence[str]] = None,
) -> int:
    return len(
        list_trades(user_no, monitor_id=monitor_id, statuses=statuses or _TRACKED_STATUSES)
    )


def pool_status_map(
    user_no: str,
    *,
    monitor_id: Optional[str] = None,
) -> Dict[int, str]:
    """trade_id -> normalized status for reconcile."""
    rows = list_trades(
        user_no,
        monitor_id=monitor_id,
        statuses=("pending", "active", "closing"),
    )
    out: Dict[int, str] = {}
    for rec in rows:
        tid = rec.get("trade_id")
        if tid is None:
            continue
        try:
            out[int(tid)] = str(rec.get("status") or "active").strip().lower()
        except (TypeError, ValueError):
            continue
    return out


def trade_record_from_trades_columns(
    columns: List[str],
    row: Tuple[Any, ...],
    *,
    monitor_id: str,
    status: str = "active",
) -> Dict[str, Any]:
    """Build a Redis record from a trades_* SELECT row."""
    data = dict(zip(columns, row))
    rec: Dict[str, Any] = {"monitor_id": str(monitor_id).strip(), "status": status}
    field_map = {
        "id": "trade_id",
        "ticket_id": "ticket_id",
        "date": "date",
        "time": "time",
        "strike": "strike",
        "side": "side",
        "buy_price": "buy_price",
        "position": "position",
        "contract": "contract",
        "ticker": "ticker",
        "symbol": "symbol",
        "market": "exchange",
        "exchange": "exchange",
        "trade_strategy": "trade_strategy",
        "symbol_open": "symbol_open",
        "momentum": "momentum",
        "prob": "prob",
        "fees": "fees",
        "diff": "diff",
    }
    for src, dst in field_map.items():
        if src in data and data[src] is not None:
            rec[dst] = data[src]
    if "trade_id" not in rec and "id" in data:
        rec["trade_id"] = data["id"]
    bp = rec.get("buy_price")
    if bp is not None:
        rec.setdefault("high_price", bp)
        rec.setdefault("low_price", bp)
    return normalize_trade_record(rec)


def export_hot_marks_for_trade_log(user_no: str) -> List[Dict[str, Any]]:
    """Marks for trade history UI — read directly from Redis active_trades (hot path)."""
    out: List[Dict[str, Any]] = []
    for rec in list_trades(user_no, statuses=("active",)):
        tid = rec.get("trade_id")
        if tid is None:
            continue
        try:
            tid_int = int(tid)
        except (TypeError, ValueError):
            continue
        mark: Dict[str, Any] = {"trade_id": tid_int}
        mcp = rec.get("current_close_price")
        if mcp is not None:
            try:
                mark["sell_price"] = round(1.0 - float(mcp), 6)
            except (TypeError, ValueError):
                pass
        cp = rec.get("current_pnl")
        if cp is not None and str(cp).strip() != "":
            try:
                mark["pnl"] = float(str(cp).replace(",", ""))
            except (TypeError, ValueError):
                pass
        # current_probability stays in Redis for ATS only; trade log prob is open-time frozen.
        if len(mark) > 1:
            out.append(mark)
    return out


def get_high_low_prices(user_no: str, trade_id: int) -> Tuple[Optional[float], Optional[float]]:
    rec = get_trade(user_no, trade_id)
    if not rec:
        return None, None
    hp, lp = rec.get("high_price"), rec.get("low_price")
    try:
        return (
            float(hp) if hp is not None else None,
            float(lp) if lp is not None else None,
        )
    except (TypeError, ValueError):
        return None, None
