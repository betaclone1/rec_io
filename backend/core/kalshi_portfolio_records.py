"""
Shared normalization and PostgreSQL upserts for Kalshi portfolio WS/REST payloads.
"""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any, Dict, Optional, Tuple


def fp_to_numeric(v: Any) -> Optional[Decimal]:
    if v is None or (isinstance(v, str) and v.strip() == ""):
        return None
    try:
        return Decimal(str(v))
    except Exception:
        return None


def direction_from_api_dict(raw: dict) -> Tuple[Optional[str], Optional[str]]:
    if not raw:
        return None, None
    outcome = (
        raw.get("outcome_side")
        or raw.get("side")
        or raw.get("purchased_side")
        or ""
    )
    outcome = str(outcome).strip().lower() or None
    if outcome not in ("yes", "no"):
        outcome = None
    book = (raw.get("book_side") or raw.get("orderbook_side") or "")
    book = str(book).strip().lower() or None
    if not book and outcome in ("yes", "no"):
        book = "bid" if outcome == "yes" else "ask"
    return outcome, book


def _ws_inner(msg: Any) -> dict:
    if isinstance(msg, dict) and isinstance(msg.get("msg"), dict):
        return msg["msg"]
    return msg if isinstance(msg, dict) else {}


def _serialize_value(value: Any) -> Any:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return value


def centi_cents_to_dollars(v: Any) -> Optional[float]:
    """Kalshi WS monetary fields are integer centi-cents (1/10_000 of a dollar)."""
    s = centi_cents_to_dollar_str(v)
    if s is None:
        return None
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


def centi_cents_to_dollar_str(v: Any) -> Optional[str]:
    if v is None or (isinstance(v, str) and v.strip() == ""):
        return None
    try:
        d = (Decimal(str(v)) / Decimal(10000)).normalize()
        s = format(d, "f")
        if "." in s:
            s = s.rstrip("0").rstrip(".")
        return s or "0"
    except (TypeError, ValueError, ArithmeticError):
        return None


_SUBACCOUNT_DEFAULT = 1


def _extract_subaccount(raw: dict) -> int:
    """Return integer subaccount from raw WS/REST payload.

    Kalshi uses ``subaccount`` on fills/positions and ``subaccount_number``
    on orders.  Missing / None → primary (1).
    """
    v = raw.get("subaccount")
    if v is None:
        v = raw.get("subaccount_number")
    if v is None:
        return _SUBACCOUNT_DEFAULT
    try:
        return int(v)
    except (TypeError, ValueError):
        return _SUBACCOUNT_DEFAULT


def _fp_display(raw: dict, position_fp: Optional[Decimal]) -> Any:
    for k in ("position_fp", "position"):
        if k in raw and isinstance(raw.get(k), str):
            s = str(raw[k]).strip()
            if s != "":
                return s
    if position_fp is None:
        return "0"
    s = format(position_fp.normalize(), "f")
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s or "0"


def _position_dollar_field(
    raw: dict,
    *,
    dollars_keys: Tuple[str, ...],
    centi_keys: Tuple[str, ...],
) -> Optional[Any]:
    for k in dollars_keys:
        if k not in raw:
            continue
        v = raw.get(k)
        if v is None or v == "":
            continue
        if isinstance(v, (list, tuple, dict)):
            continue
        if isinstance(v, str):
            return v
        try:
            d = Decimal(str(v)).normalize()
            s = format(d, "f")
            if "." in s:
                s = s.rstrip("0").rstrip(".")
            return s or "0"
        except (TypeError, ValueError, ArithmeticError):
            return str(v)
    for k in centi_keys:
        if k not in raw:
            continue
        s = centi_cents_to_dollar_str(raw.get(k))
        if s is not None:
            return s
    return None


_LEGACY_POSITION_COST_KEYS = frozenset(
    {"market_exposure", "market_exposure_dollars", "position_cost"}
)


def _strip_legacy_position_cost_fields(d: Dict[str, Any]) -> Dict[str, Any]:
    """REST/legacy keys are not part of portfolio hot-state vocabulary."""
    for k in _LEGACY_POSITION_COST_KEYS:
        d.pop(k, None)
    return d


def _finalize_position_record(out: Dict[str, Any]) -> Dict[str, Any]:
    """Flat position with no cost in payload → explicit zero position_cost_dollars."""
    try:
        flat = abs(float(out.get("position_fp") or 0)) < 1e-9
    except (TypeError, ValueError):
        flat = False
    if flat and out.get("position_cost_dollars") is None:
        out["position_cost_dollars"] = "0"
    preserve = {
        "position_fp",
        "position_cost_dollars",
        "realized_pnl_dollars",
        "fees_paid_dollars",
        "total_traded_dollars",
    }
    finalized = {
        k: (v if k in preserve else _serialize_value(v))
        for k, v in out.items()
    }
    return _strip_legacy_position_cost_fields(finalized)


def normalize_position_record(raw: dict) -> Optional[Dict[str, Any]]:
    if not raw:
        return None
    raw = dict(raw)
    # REST GET /portfolio/positions exposes market_exposure_dollars; WS uses position_cost_dollars.
    if not raw.get("position_cost_dollars") and raw.get("market_exposure_dollars"):
        raw["position_cost_dollars"] = raw["market_exposure_dollars"]
    ticker = raw.get("ticker") or raw.get("market_ticker")
    if not ticker:
        return None
    if "KXMAYORNYCPARTY" in str(ticker):
        return None
    position_fp = fp_to_numeric(raw.get("position_fp"))
    if position_fp is None and raw.get("position") is not None:
        position_fp = fp_to_numeric(raw.get("position"))
    out: Dict[str, Any] = {
        "ticker": str(ticker),
        "subaccount": _extract_subaccount(raw),
        "last_updated_ts": raw.get("last_updated_ts"),
        "total_traded_dollars": _position_dollar_field(
            raw, dollars_keys=("total_traded_dollars",), centi_keys=()
        ),
        "position_cost_dollars": _position_dollar_field(
            raw,
            dollars_keys=("position_cost_dollars",),
            centi_keys=("position_cost",),
        ),
        "realized_pnl_dollars": _position_dollar_field(
            raw,
            dollars_keys=("realized_pnl_dollars",),
            centi_keys=("realized_pnl",),
        ),
        "fees_paid_dollars": _position_dollar_field(
            raw, dollars_keys=("fees_paid_dollars",), centi_keys=("fees_paid",)
        ),
        "total_traded_fp": _serialize_value(fp_to_numeric(raw.get("total_traded_fp"))),
        "position_fp": _fp_display(raw, position_fp),
        "position": raw.get("position"),
        "raw_json": raw if isinstance(raw.get("raw_json"), dict) else raw,
    }
    return _finalize_position_record(out)


def normalize_fill_record(raw: dict) -> Optional[Dict[str, Any]]:
    if not raw:
        return None
    trade_id = raw.get("trade_id")
    if not trade_id:
        return None
    out_side, ob_side = direction_from_api_dict(raw)
    return {
        "trade_id": str(trade_id),
        "ticker": raw.get("ticker") or raw.get("market_ticker"),
        "order_id": raw.get("order_id"),
        "subaccount": _extract_subaccount(raw),
        "outcome_side": out_side,
        "orderbook_side": ob_side,
        "action": raw.get("action"),
        "count_fp": _serialize_value(fp_to_numeric(raw.get("count_fp"))),
        "yes_price_dollars": raw.get("yes_price_dollars") or raw.get("yes_price_fixed"),
        "no_price_dollars": raw.get("no_price_dollars") or raw.get("no_price_fixed"),
        "is_taker": bool(raw.get("is_taker")) if raw.get("is_taker") is not None else None,
        "created_time": raw.get("created_time"),
        "raw_json": raw,
    }


def normalize_order_record(raw: dict) -> Optional[Dict[str, Any]]:
    if not raw:
        return None
    order_id = raw.get("order_id")
    if not order_id:
        return None
    out_side, ob_side = direction_from_api_dict(raw)
    def _order_count(fp_key: str, int_key: str) -> Any:
        v = fp_to_numeric(raw.get(fp_key))
        if v is None:
            v = fp_to_numeric(raw.get(int_key))
        return _serialize_value(v)

    return {
        "order_id": str(order_id),
        "user_id": raw.get("user_id"),
        "ticker": raw.get("ticker"),
        "subaccount": _extract_subaccount(raw),
        "status": raw.get("status"),
        "action": raw.get("action"),
        "outcome_side": out_side,
        "orderbook_side": ob_side,
        "type": raw.get("type"),
        "yes_price_dollars": raw.get("yes_price_dollars"),
        "no_price_dollars": raw.get("no_price_dollars"),
        "initial_count_fp": _order_count("initial_count_fp", "initial_count"),
        "remaining_count_fp": _order_count("remaining_count_fp", "remaining_count"),
        "fill_count_fp": _order_count("fill_count_fp", "fill_count"),
        "created_time": raw.get("created_time"),
        "expiration_time": raw.get("expiration_time"),
        "last_update_time": raw.get("last_update_time"),
        "client_order_id": raw.get("client_order_id"),
        "order_group_id": raw.get("order_group_id"),
        "queue_position": raw.get("queue_position"),
        "self_trade_prevention_type": raw.get("self_trade_prevention_type"),
        "maker_fees_dollars": raw.get("maker_fees_dollars"),
        "taker_fees_dollars": raw.get("taker_fees_dollars"),
        "maker_fill_cost_dollars": raw.get("maker_fill_cost_dollars"),
        "taker_fill_cost_dollars": raw.get("taker_fill_cost_dollars"),
        "raw_json": raw,
    }


def upsert_fill_row(cur, fills_tbl: str, rec: Dict[str, Any]) -> None:
    msg = rec.get("raw_json") if isinstance(rec.get("raw_json"), dict) else rec
    cur.execute(
        f"""
        INSERT INTO {fills_tbl}
        (trade_id, ticker, order_id, subaccount, outcome_side, orderbook_side, action, count_fp,
         yes_price_dollars, no_price_dollars, is_taker, created_time, raw_json)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        ON CONFLICT (trade_id) DO UPDATE SET
            ticker = EXCLUDED.ticker,
            order_id = EXCLUDED.order_id,
            subaccount = EXCLUDED.subaccount,
            outcome_side = EXCLUDED.outcome_side,
            orderbook_side = EXCLUDED.orderbook_side,
            action = EXCLUDED.action,
            count_fp = EXCLUDED.count_fp,
            yes_price_dollars = EXCLUDED.yes_price_dollars,
            no_price_dollars = EXCLUDED.no_price_dollars,
            is_taker = EXCLUDED.is_taker,
            created_time = EXCLUDED.created_time,
            raw_json = EXCLUDED.raw_json
        """,
        (
            rec.get("trade_id"),
            rec.get("ticker"),
            rec.get("order_id"),
            rec.get("subaccount", _SUBACCOUNT_DEFAULT),
            rec.get("outcome_side"),
            rec.get("orderbook_side"),
            rec.get("action"),
            fp_to_numeric(rec.get("count_fp")),
            rec.get("yes_price_dollars"),
            rec.get("no_price_dollars"),
            rec.get("is_taker"),
            rec.get("created_time"),
            json.dumps(msg),
        ),
    )


def upsert_order_row(cur, orders_tbl: str, rec: Dict[str, Any]) -> None:
    msg = rec.get("raw_json") if isinstance(rec.get("raw_json"), dict) else rec
    cur.execute(
        f"""
        INSERT INTO {orders_tbl}
        (order_id, user_id, ticker, subaccount, status, action, outcome_side, orderbook_side, type,
         yes_price_dollars, no_price_dollars,
         initial_count_fp, remaining_count_fp, fill_count_fp,
         created_time, expiration_time, last_update_time, client_order_id, order_group_id, queue_position,
         self_trade_prevention_type,
         maker_fees_dollars, taker_fees_dollars, maker_fill_cost_dollars, taker_fill_cost_dollars,
         raw_json)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        ON CONFLICT (order_id) DO UPDATE SET
            status = EXCLUDED.status,
            action = EXCLUDED.action,
            subaccount = EXCLUDED.subaccount,
            outcome_side = EXCLUDED.outcome_side,
            orderbook_side = EXCLUDED.orderbook_side,
            ticker = EXCLUDED.ticker,
            type = EXCLUDED.type,
            yes_price_dollars = EXCLUDED.yes_price_dollars,
            no_price_dollars = EXCLUDED.no_price_dollars,
            initial_count_fp = EXCLUDED.initial_count_fp,
            remaining_count_fp = EXCLUDED.remaining_count_fp,
            fill_count_fp = EXCLUDED.fill_count_fp,
            created_time = EXCLUDED.created_time,
            expiration_time = EXCLUDED.expiration_time,
            last_update_time = EXCLUDED.last_update_time,
            client_order_id = EXCLUDED.client_order_id,
            order_group_id = EXCLUDED.order_group_id,
            queue_position = EXCLUDED.queue_position,
            self_trade_prevention_type = EXCLUDED.self_trade_prevention_type,
            maker_fees_dollars = EXCLUDED.maker_fees_dollars,
            taker_fees_dollars = EXCLUDED.taker_fees_dollars,
            maker_fill_cost_dollars = EXCLUDED.maker_fill_cost_dollars,
            taker_fill_cost_dollars = EXCLUDED.taker_fill_cost_dollars,
            raw_json = EXCLUDED.raw_json,
            updated_at = CURRENT_TIMESTAMP
        """,
        (
            rec.get("order_id"),
            rec.get("user_id"),
            rec.get("ticker"),
            rec.get("subaccount", _SUBACCOUNT_DEFAULT),
            rec.get("status"),
            rec.get("action"),
            rec.get("outcome_side"),
            rec.get("orderbook_side"),
            rec.get("type"),
            rec.get("yes_price_dollars"),
            rec.get("no_price_dollars"),
            fp_to_numeric(rec.get("initial_count_fp")),
            fp_to_numeric(rec.get("remaining_count_fp")),
            fp_to_numeric(rec.get("fill_count_fp")),
            rec.get("created_time"),
            rec.get("expiration_time"),
            rec.get("last_update_time"),
            rec.get("client_order_id"),
            rec.get("order_group_id"),
            rec.get("queue_position"),
            rec.get("self_trade_prevention_type"),
            rec.get("maker_fees_dollars"),
            rec.get("taker_fees_dollars"),
            rec.get("maker_fill_cost_dollars"),
            rec.get("taker_fill_cost_dollars"),
            json.dumps(msg),
        ),
    )
