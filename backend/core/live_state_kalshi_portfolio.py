"""
Redis hot-path store for Kalshi portfolio entities (positions, orders, fills).

Positions are ephemeral (current cycle only). Orders/fills hashes retain a rolling time window;
PostgreSQL remains historical source via spooled writes.
"""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from backend.core.kalshi_portfolio_records import (
    _SUBACCOUNT_DEFAULT,
    _strip_legacy_position_cost_fields,
    _ws_inner,
    normalize_fill_record,
    normalize_order_record,
    normalize_position_record,
)
from backend.core.live_state_cache import (
    KEY_PREFIX,
    TTL_SEC,
    _json_default,
    redis_client_optional,
)
from backend.trading_mode import _norm_slot

logger = logging.getLogger(__name__)

KIND_POSITIONS = "kalshi_positions"
KIND_ORDERS = "kalshi_orders"
KIND_FILLS = "kalshi_fills"


def live_state_kalshi_portfolio_enabled() -> bool:
    """Portfolio hot state is always on (not env-togglable). Redis availability is checked at use sites."""
    return True


def _retention_sec() -> float:
    try:
        hours = float(os.getenv("LIVE_STATE_KALSHI_PORTFOLIO_RETENTION_HOURS", "1"))
    except ValueError:
        hours = 1.0
    return max(0.25, hours) * 3600.0


def _record_epoch(ts: Any) -> Optional[float]:
    if ts is None:
        return None
    if isinstance(ts, (int, float)):
        return float(ts)
    s = str(ts).strip()
    if not s:
        return None
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except Exception:
        return None


def _within_retention(rec: Dict[str, Any], sort_field: str) -> bool:
    ep = _record_epoch(rec.get(sort_field) or rec.get("last_updated_ts"))
    if ep is None:
        return True
    return ep >= (time.time() - _retention_sec())


def tenant_kalshi_positions_key(user_no: str) -> str:
    slot = _norm_slot(str(user_no))
    return f"{KEY_PREFIX}:tenant:{slot}:kalshi:positions"


def tenant_kalshi_orders_key(user_no: str) -> str:
    slot = _norm_slot(str(user_no))
    return f"{KEY_PREFIX}:tenant:{slot}:kalshi:orders"


def tenant_kalshi_fills_key(user_no: str) -> str:
    slot = _norm_slot(str(user_no))
    return f"{KEY_PREFIX}:tenant:{slot}:kalshi:fills"


def _position_hash_field(ticker: str, subaccount: int = _SUBACCOUNT_DEFAULT) -> str:
    """Composite hash field for positions: ``{ticker}:{subaccount}``."""
    return f"{ticker}:{subaccount}"


def _monitor_row_for_kind(kind: str, rec: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    projector = {
        KIND_POSITIONS: position_row_for_monitor,
        KIND_ORDERS: order_row_for_monitor,
        KIND_FILLS: fill_row_for_monitor,
    }
    fn = projector.get(kind)
    if not fn:
        return None
    row = fn(rec)
    return row if row.get("row_id") is not None else None


def _publish_portfolio_updated(
    kind: str,
    user_no: str,
    *,
    field: Optional[str] = None,
    detail: str = "row",
    row: Optional[Dict[str, Any]] = None,
    rows: Optional[List[Dict[str, Any]]] = None,
    removes: Optional[List[str]] = None,
) -> None:
    from backend.core.live_state_cache import UPDATED_CHANNEL

    r = redis_client_optional()
    if not r:
        return
    key_map = {
        KIND_POSITIONS: tenant_kalshi_positions_key,
        KIND_ORDERS: tenant_kalshi_orders_key,
        KIND_FILLS: tenant_kalshi_fills_key,
    }
    fn = key_map.get(kind)
    if not fn:
        return
    key = fn(user_no)
    payload: Dict[str, Any] = {
        "type": "live_state_updated",
        "kind": kind,
        "key": key,
        "detail": detail,
    }
    if field is not None:
        payload["field"] = str(field)
    if row is not None:
        payload["row"] = row
    if rows is not None:
        payload["rows"] = rows
    if removes:
        payload["removes"] = [str(x) for x in removes if x]
    try:
        r.publish(UPDATED_CHANNEL, json.dumps(payload, default=_json_default))
    except Exception as exc:
        logger.debug("portfolio publish failed kind=%s: %s", kind, exc)


def _trim_hash(r, key: str, *, sort_field: str) -> None:
    """Drop rows older than the retention window."""
    try:
        raw_map = r.hgetall(key) or {}
    except Exception:
        return
    if not raw_map:
        return
    cutoff = time.time() - _retention_sec()
    for field, blob in raw_map.items():
        try:
            rec = json.loads(blob)
            ts = str(rec.get(sort_field) or rec.get("last_updated_ts") or "")
            ep = _record_epoch(ts)
        except (json.JSONDecodeError, TypeError):
            ep = None
        if ep is not None and ep < cutoff:
            try:
                r.hdel(key, field)
            except Exception:
                pass


def _hset_record(
    user_no: str,
    key: str,
    field: str,
    rec: Dict[str, Any],
    *,
    kind: str,
    publish: bool = True,
) -> bool:
    if not live_state_kalshi_portfolio_enabled():
        return False
    r = redis_client_optional()
    if not r:
        return False
    try:
        r.hset(key, field, json.dumps(rec, default=_json_default))
        r.expire(key, TTL_SEC)
        if publish:
            row = _monitor_row_for_kind(kind, rec)
            if row is not None:
                _publish_portfolio_updated(
                    kind,
                    user_no,
                    field=field,
                    detail="row",
                    row=row,
                )
        return True
    except Exception as exc:
        logger.warning("portfolio hset failed key=%s field=%s: %s", key, field, exc)
        return False


def upsert_position_from_ws(
    user_no: str,
    ws_outer: dict,
    *,
    last_updated_ts: Optional[str] = None,
) -> bool:
    msg = _ws_inner(ws_outer)
    rec = normalize_position_record(msg)
    if rec is None:
        return False
    key = tenant_kalshi_positions_key(user_no)
    ticker = rec.get("ticker") or ""
    if not ticker:
        return False
    field = _position_hash_field(ticker, rec.get("subaccount", _SUBACCOUNT_DEFAULT))
    if not rec.get("last_updated_ts") and last_updated_ts:
        rec["last_updated_ts"] = last_updated_ts
    rec["updated_at"] = time.time()
    return _hset_record(user_no, key, field, rec, kind=KIND_POSITIONS)


def remove_position(user_no: str, ticker: str, subaccount: int = _SUBACCOUNT_DEFAULT) -> bool:
    if not live_state_kalshi_portfolio_enabled():
        return False
    r = redis_client_optional()
    if not r or not ticker:
        return False
    key = tenant_kalshi_positions_key(user_no)
    field = _position_hash_field(str(ticker), subaccount)
    try:
        r.hdel(key, field)
        _publish_portfolio_updated(
            KIND_POSITIONS,
            user_no,
            field=field,
            detail="remove",
            removes=[field],
        )
        return True
    except Exception as exc:
        logger.warning("portfolio position remove failed ticker=%s sa=%s: %s", ticker, subaccount, exc)
        return False


def prune_positions_to_rest_tickers(user_no: str, rest_tickers: List[str]) -> int:
    """Drop hot-state rows whose ticker is absent from REST GET /portfolio/positions.

    Hash fields are ``{ticker}:{subaccount}`` -- we extract the ticker part
    for the membership check against the REST snapshot.
    """
    if not live_state_kalshi_portfolio_enabled():
        return 0
    r = redis_client_optional()
    if not r:
        return 0
    allowed = {str(t) for t in rest_tickers if t}
    key = tenant_kalshi_positions_key(user_no)
    try:
        raw_map = r.hgetall(key) or {}
    except Exception as exc:
        logger.warning("portfolio positions prune list failed: %s", exc)
        return 0
    stale: List[str] = []
    for field_raw in raw_map:
        field = str(field_raw)
        ticker = field.rsplit(":", 1)[0] if ":" in field else field
        if ticker not in allowed:
            stale.append(field)
    if not stale:
        return 0
    removed = 0
    for field in stale:
        try:
            if r.hdel(key, field):
                removed += 1
        except Exception as exc:
            logger.debug("portfolio position prune hdel failed field=%s: %s", field, exc)
    if removed:
        _publish_portfolio_updated(
            KIND_POSITIONS,
            user_no,
            detail="delta",
            removes=stale,
        )
    return removed


def portfolio_hot_retention_sec() -> float:
    """Rolling window for fills/orders hot hash (default 1 hour)."""
    return _retention_sec()


def replace_positions_baseline(user_no: str, market_positions: List[dict]) -> int:
    """Startup/REST snapshot: set hot positions hash to match GET /portfolio/positions."""
    if not live_state_kalshi_portfolio_enabled():
        return 0
    r = redis_client_optional()
    if not r:
        return 0
    key = tenant_kalshi_positions_key(user_no)
    now_iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    allowed: set[str] = set()
    upserted = 0
    monitor_rows: List[Dict[str, Any]] = []
    for raw in market_positions or []:
        rec = normalize_position_record(raw)
        if not rec:
            continue
        ticker = str(rec.get("ticker") or "")
        if not ticker:
            continue
        sa = rec.get("subaccount", _SUBACCOUNT_DEFAULT)
        field = _position_hash_field(ticker, sa)
        allowed.add(field)
        if not rec.get("last_updated_ts"):
            rec["last_updated_ts"] = now_iso
        rec["updated_at"] = time.time()
        if _hset_record(user_no, key, field, rec, kind=KIND_POSITIONS, publish=False):
            upserted += 1
            row = _monitor_row_for_kind(KIND_POSITIONS, rec)
            if row:
                monitor_rows.append(row)
    stale: List[str] = []
    try:
        raw_map = r.hgetall(key) or {}
        stale = [str(f) for f in raw_map if str(f) not in allowed]
        for f in stale:
            try:
                r.hdel(key, f)
            except Exception:
                pass
    except Exception as exc:
        logger.warning("portfolio positions baseline prune failed: %s", exc)
    if upserted or stale:
        _publish_portfolio_updated(
            KIND_POSITIONS,
            user_no,
            detail="baseline",
            rows=monitor_rows if monitor_rows else None,
            removes=stale if stale else None,
        )
    return upserted


def merge_fills_baseline(user_no: str, fills: List[dict]) -> int:
    """Startup/REST backfill: merge fills into hot hash (retention window applies)."""
    if not live_state_kalshi_portfolio_enabled():
        return 0
    r = redis_client_optional()
    if not r:
        return 0
    key = tenant_kalshi_fills_key(user_no)
    merged = 0
    monitor_rows: List[Dict[str, Any]] = []
    for raw in fills or []:
        rec = normalize_fill_record(raw)
        if not rec:
            continue
        if not _within_retention(rec, "created_time"):
            continue
        field = str(rec.get("trade_id") or "")
        if not field:
            continue
        if _hset_record(user_no, key, field, rec, kind=KIND_FILLS, publish=False):
            merged += 1
            row = _monitor_row_for_kind(KIND_FILLS, rec)
            if row:
                monitor_rows.append(row)
    if merged:
        _trim_hash(r, key, sort_field="created_time")
        _publish_portfolio_updated(
            KIND_FILLS,
            user_no,
            detail="baseline",
            rows=monitor_rows if monitor_rows else None,
        )
    return merged


def merge_orders_baseline(user_no: str, orders: List[dict]) -> int:
    """Startup/REST backfill: merge orders into hot hash (retention window applies)."""
    if not live_state_kalshi_portfolio_enabled():
        return 0
    r = redis_client_optional()
    if not r:
        return 0
    key = tenant_kalshi_orders_key(user_no)
    merged = 0
    monitor_rows: List[Dict[str, Any]] = []
    for raw in orders or []:
        rec = normalize_order_record(raw)
        if not rec:
            continue
        if not _within_retention(rec, "last_update_time"):
            continue
        field = str(rec.get("order_id") or "")
        if not field:
            continue
        if _hset_record(user_no, key, field, rec, kind=KIND_ORDERS, publish=False):
            merged += 1
            row = _monitor_row_for_kind(KIND_ORDERS, rec)
            if row:
                monitor_rows.append(row)
    if merged:
        _trim_hash(r, key, sort_field="last_update_time")
        _publish_portfolio_updated(
            KIND_ORDERS,
            user_no,
            detail="baseline",
            rows=monitor_rows if monitor_rows else None,
        )
    return merged


def upsert_fill_from_ws(user_no: str, ws_outer: dict) -> bool:
    rec = normalize_fill_record(_ws_inner(ws_outer))
    if not rec:
        return False
    key = tenant_kalshi_fills_key(user_no)
    return _hset_record(user_no, key, str(rec["trade_id"]), rec, kind=KIND_FILLS)


def upsert_order_from_ws(user_no: str, ws_outer: dict) -> bool:
    rec = normalize_order_record(_ws_inner(ws_outer))
    if not rec:
        return False
    key = tenant_kalshi_orders_key(user_no)
    return _hset_record(user_no, key, str(rec["order_id"]), rec, kind=KIND_ORDERS)


def _list_hash_records(
    user_no: str,
    key_fn,
    *,
    sort_field: str,
    retention_field: Optional[str] = None,
) -> List[Dict[str, Any]]:
    if not live_state_kalshi_portfolio_enabled():
        return []
    r = redis_client_optional()
    if not r:
        return []
    key = key_fn(user_no)
    try:
        raw_map = r.hgetall(key) or {}
    except Exception as exc:
        logger.debug("portfolio list failed: %s", exc)
        return []
    out: List[Dict[str, Any]] = []
    rf = retention_field or sort_field
    for blob in raw_map.values():
        try:
            rec = json.loads(blob)
            if isinstance(rec, dict):
                if retention_field and not _within_retention(rec, rf):
                    continue
                out.append(rec)
        except (json.JSONDecodeError, TypeError):
            continue
    out.sort(key=lambda d: str(d.get(sort_field) or ""), reverse=True)
    return out


def list_positions(user_no: str) -> List[Dict[str, Any]]:
    rows = _list_hash_records(user_no, tenant_kalshi_positions_key, sort_field="last_updated_ts")
    api_rows: List[Dict[str, Any]] = []
    for rec in rows:
        d = _strip_legacy_position_cost_fields(dict(rec))
        if d.get("position_fp") is not None:
            try:
                d["position"] = int(round(float(d["position_fp"])))
            except (TypeError, ValueError):
                pass
        api_rows.append(d)
    return api_rows


def get_order(user_no: str, order_id: str) -> Optional[Dict[str, Any]]:
    """Single order row from portfolio hot hash (WS-driven)."""
    if not live_state_kalshi_portfolio_enabled():
        return None
    oid = str(order_id or "").strip()
    if not oid:
        return None
    r = redis_client_optional()
    if not r:
        return None
    key = tenant_kalshi_orders_key(user_no)
    try:
        blob = r.hget(key, oid)
    except Exception as exc:
        logger.debug("portfolio order get failed order_id=%s: %s", oid, exc)
        return None
    if not blob:
        return None
    try:
        rec = json.loads(blob)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(rec, dict):
        return None
    if not _within_retention(rec, "last_update_time"):
        return None
    return _merge_order_with_fill_aggregate(user_no, rec)


def _fill_leg_cost_dollars(rec: Dict[str, Any]) -> float:
    try:
        cnt = float(rec.get("count_fp") or 0.0)
    except (TypeError, ValueError):
        return 0.0
    if cnt <= 0:
        return 0.0
    yp_raw = rec.get("yes_price_dollars")
    if yp_raw is None:
        return 0.0
    try:
        yp = float(yp_raw)
    except (TypeError, ValueError):
        return 0.0
    side = str(rec.get("outcome_side") or "").strip().lower()
    if side == "no":
        return cnt * (1.0 - yp)
    if side == "yes":
        return cnt * yp
    return cnt * yp


def _fill_leg_fee_dollars(rec: Dict[str, Any]) -> float:
    raw = rec.get("raw_json") if isinstance(rec.get("raw_json"), dict) else rec
    for key in ("fee_cost", "taker_fees_dollars", "maker_fees_dollars"):
        val = raw.get(key)
        if val is None:
            continue
        try:
            return float(val)
        except (TypeError, ValueError):
            continue
    return 0.0


def aggregate_fills_for_order(user_no: str, order_id: str) -> Dict[str, float]:
    """Sum fill legs in the fills hot hash for one Kalshi order_id."""
    oid = str(order_id or "").strip()
    out = {"fill_count": 0.0, "taker_fees": 0.0, "taker_fill_cost": 0.0}
    if not oid:
        return out
    for rec in list_fills(user_no):
        if str(rec.get("order_id") or "").strip() != oid:
            continue
        try:
            out["fill_count"] += float(rec.get("count_fp") or 0.0)
        except (TypeError, ValueError):
            pass
        out["taker_fees"] += _fill_leg_fee_dollars(rec)
        out["taker_fill_cost"] += _fill_leg_cost_dollars(rec)
    return out


def _merge_order_with_fill_aggregate(user_no: str, rec: Dict[str, Any]) -> Dict[str, Any]:
    """Confirm-ready order view: order hash row plus any fill legs not yet on the order row."""
    oid = str(rec.get("order_id") or "").strip()
    if not oid:
        return rec
    agg = aggregate_fills_for_order(user_no, oid)
    try:
        order_fill = float(rec.get("fill_count_fp") or 0.0)
    except (TypeError, ValueError):
        order_fill = 0.0
    if agg["fill_count"] <= order_fill + 1e-9:
        return rec
    merged = dict(rec)
    merged["fill_count_fp"] = agg["fill_count"]
    if agg["taker_fees"] > 0:
        merged["taker_fees_dollars"] = f"{agg['taker_fees']:.6f}"
    if agg["taker_fill_cost"] > 0:
        merged["taker_fill_cost_dollars"] = f"{agg['taker_fill_cost']:.6f}"
    try:
        initial = float(rec.get("initial_count_fp") or 0.0)
    except (TypeError, ValueError):
        initial = 0.0
    if initial > 0:
        merged["remaining_count_fp"] = max(0.0, initial - agg["fill_count"])
    return merged


def list_orders(user_no: str) -> List[Dict[str, Any]]:
    return _list_hash_records(
        user_no,
        tenant_kalshi_orders_key,
        sort_field="last_update_time",
        retention_field="last_update_time",
    )


def list_fills(user_no: str) -> List[Dict[str, Any]]:
    return _list_hash_records(
        user_no,
        tenant_kalshi_fills_key,
        sort_field="created_time",
        retention_field="created_time",
    )


def sum_fill_count_for_order(user_no: str, order_id: str) -> float:
    """Sum fill count_fp rows in the fills hot hash for one Kalshi order_id."""
    return aggregate_fills_for_order(user_no, order_id)["fill_count"]


def position_row_for_monitor(rec: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "row_id": rec.get("ticker"),
        "ticker": rec.get("ticker"),
        "subaccount": rec.get("subaccount", _SUBACCOUNT_DEFAULT),
        "position_fp": rec.get("position_fp"),
        "volume_fp": rec.get("volume_fp"),
        "position_cost_dollars": rec.get("position_cost_dollars"),
        "realized_pnl_dollars": rec.get("realized_pnl_dollars"),
        "last_updated_ts": rec.get("last_updated_ts"),
    }


def order_row_for_monitor(rec: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "row_id": rec.get("order_id"),
        "order_id": rec.get("order_id"),
        "ticker": rec.get("ticker"),
        "subaccount": rec.get("subaccount", _SUBACCOUNT_DEFAULT),
        "status": rec.get("status"),
        "orderbook_side": rec.get("orderbook_side"),
        "outcome_side": rec.get("outcome_side"),
        "initial_count": rec.get("initial_count_fp"),
        "fill_count": rec.get("fill_count_fp"),
        "remaining_count": rec.get("remaining_count_fp"),
        "yes_price_dollars": rec.get("yes_price_dollars"),
    }


def fill_row_for_monitor(rec: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "row_id": rec.get("trade_id"),
        "trade_id": rec.get("trade_id"),
        "ticker": rec.get("ticker"),
        "subaccount": rec.get("subaccount", _SUBACCOUNT_DEFAULT),
        "order_id": rec.get("order_id"),
        "orderbook_side": rec.get("orderbook_side"),
        "outcome_side": rec.get("outcome_side"),
        "count_fp": rec.get("count_fp"),
        "yes_price_dollars": rec.get("yes_price_dollars"),
        "created_time": rec.get("created_time"),
    }


def portfolio_monitor_row_for_field(kind: str, user_no: str, field: str) -> Optional[Dict[str, Any]]:
    if not field:
        return None
    key_map = {
        KIND_POSITIONS: tenant_kalshi_positions_key,
        KIND_ORDERS: tenant_kalshi_orders_key,
        KIND_FILLS: tenant_kalshi_fills_key,
    }
    projector = {
        KIND_POSITIONS: position_row_for_monitor,
        KIND_ORDERS: order_row_for_monitor,
        KIND_FILLS: fill_row_for_monitor,
    }
    key_fn = key_map.get(kind)
    proj = projector.get(kind)
    if not key_fn or not proj:
        return None
    r = redis_client_optional()
    if not r:
        return None
    try:
        raw = r.hget(key_fn(user_no), str(field))
        if not raw:
            return None
        rec = json.loads(raw)
        if not isinstance(rec, dict):
            return None
        return proj(rec)
    except Exception:
        return None
