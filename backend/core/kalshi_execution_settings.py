"""Kalshi order execution settings: TIF enum and limit/market policy (monitor + trade snapshot)."""

from __future__ import annotations

from typing import Any, Mapping, Optional, Tuple

# Kalshi Create Order API: time_in_force enum strings.
KALSHI_TIME_IN_FORCE_VALUES = frozenset(
    ("fill_or_kill", "immediate_or_cancel", "good_till_canceled")
)
# Our monitor ``order_type`` column: pricing policy (Kalshi request still uses type=limit).
EXECUTION_ORDER_TYPE_VALUES = frozenset(("limit", "market"))


def normalize_kalshi_time_in_force(raw: Any) -> Optional[str]:
    if raw is None:
        return None
    s = str(raw).strip().lower()
    return s if s in KALSHI_TIME_IN_FORCE_VALUES else None


def normalize_time_in_force_loose(raw: Any) -> Optional[str]:
    """Map API/legacy aliases (e.g. IOC) to Kalshi enum strings."""
    s = normalize_kalshi_time_in_force(raw)
    if s:
        return s
    u = str(raw or "").strip().upper()
    if u == "IOC":
        return "immediate_or_cancel"
    if u in ("FOK",):
        return "fill_or_kill"
    if u in ("GTC",):
        return "good_till_canceled"
    return None


def normalize_execution_order_type(raw: Any) -> Optional[str]:
    if raw is None:
        return None
    s = str(raw).strip().lower()
    return s if s in EXECUTION_ORDER_TYPE_VALUES else None


def validate_execution_fields(time_in_force: str, order_type: str) -> Tuple[bool, Optional[str]]:
    """Return (ok, error_detail)."""
    tif = normalize_kalshi_time_in_force(time_in_force)
    ot = normalize_execution_order_type(order_type)
    if tif is None:
        return False, "invalid_time_in_force"
    if ot is None:
        return False, "invalid_order_type"
    return True, None


def format_limit_dollars(price: float) -> str:
    return f"{float(price):.4f}"


def limit_price_for_executor_payload(
    *,
    order_type_policy: str,
    ticket_buy_price: Any,
) -> str:
    """Yes/No dollar string for Kalshi limit orders."""
    ot = normalize_execution_order_type(order_type_policy) or "market"
    if ot == "market":
        return "0.9900"
    try:
        px = float(ticket_buy_price)
    except (TypeError, ValueError):
        px = 0.0
    if px <= 0 or px >= 1:
        raise ValueError("limit_order_requires_buy_price_in_0_1")
    return format_limit_dollars(px)
