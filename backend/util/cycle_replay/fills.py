"""
Paper-style taker fills from a reconstructed cycle-package orderbook.

Mirrors ``trade_manager`` paper IOC: walk asks up to
``limit_price_for_executor_payload(order_type, ticket_ask)`` —
market policy → 0.99, limit policy → ticket ask.
"""

from __future__ import annotations

from typing import Any, Mapping, Optional, Tuple

from backend.core.cycle_package import CycleTick
from backend.core.kalshi_execution_settings import limit_price_for_executor_payload
from backend.core.orderbook_strike_prices import project_taker_buy_from_levels
from backend.util.cycle_replay.trade_shape import normalize_trade_side, side_to_yes_no
from backend.util.cycle_replay.types import EntryEvent


def _position_from_settings(settings: Mapping[str, Any]) -> int:
    for key in ("total_position", "position", "position_size"):
        raw = settings.get(key)
        if raw is None or raw == "":
            continue
        try:
            n = int(raw)
        except (TypeError, ValueError):
            continue
        if n > 0:
            return n
    return 1


def _ioc_limit_price(settings: Mapping[str, Any], ticket_ask: float) -> Optional[float]:
    """
    Same limit as paper IOC / executor.

    Non-IOC TIFs return None (market-style full depth). IOC/FOK use
    ``limit_price_for_executor_payload`` so ``order_type=market`` → 0.99.
    """
    tif = str(settings.get("time_in_force") or "immediate_or_cancel").strip().lower()
    if tif not in ("immediate_or_cancel", "ioc", "fill_or_kill", "fok"):
        return None
    lim_s = limit_price_for_executor_payload(
        order_type_policy=str(settings.get("order_type") or "market"),
        ticket_buy_price=ticket_ask,
    )
    return float(lim_s)


def apply_paper_entry_fill(
    entry: EntryEvent,
    tick: CycleTick,
    settings: Mapping[str, Any],
) -> Tuple[Optional[EntryEvent], Optional[str]]:
    """
    Attach ladder VWAP fill to a gate-passed entry intent.

    Returns (filled_entry, None) on success, or (None, reject_reason) when the
    paper path would delete the pending trade (zero fill / min_fill).
    """
    position = _position_from_settings(settings)
    if (entry.detail or {}).get("half_size") or (entry.detail or {}).get("size_mode") == "half":
        position = max(1, int(round(position * 0.5)))
    ticket_ask = float(entry.ticket_ask if entry.ticket_ask is not None else entry.buy_price)
    side_yn = normalize_trade_side(entry.side)
    try:
        limit = _ioc_limit_price(settings, ticket_ask)
    except ValueError as e:
        return None, f"ioc_bad_limit:{e}"

    proj = project_taker_buy_from_levels(
        tick.yes_book,
        tick.no_book,
        side_to_yes_no(side_yn),
        position,
        limit_price=limit,
    )
    filled = int(proj.get("filled") or 0)
    fill_px = proj.get("initial_proj_price")
    fees = proj.get("initial_proj_fees")
    if filled <= 0 or fill_px is None:
        return None, f"ioc_zero_fill:{proj.get('reason')}"

    try:
        fill_f = float(fill_px)
    except (TypeError, ValueError):
        return None, "ioc_bad_fill_price"

    raw_min = settings.get("min_fill_price")
    if raw_min not in (None, ""):
        try:
            min_fill = float(raw_min)
        except (TypeError, ValueError):
            min_fill = 0.0
        if min_fill > 0 and fill_f + 1e-9 < min_fill:
            return (
                None,
                f"min_fill_price_rejected: estimated_fill={fill_f:.4f} min_fill_price={min_fill:.4f}",
            )

    detail = dict(entry.detail or {})
    detail.update(
        {
            "ticket_ask": ticket_ask,
            "fill_reason": proj.get("reason"),
            "available_contracts": proj.get("available_contracts"),
            "requested_position": position,
            "limit_price": limit,
            "order_type": settings.get("order_type") or "market",
            "time_in_force": settings.get("time_in_force") or "immediate_or_cancel",
        }
    )
    return (
        EntryEvent(
            timestamp=entry.timestamp,
            side=side_yn,
            ticket_ask=ticket_ask,
            buy_price=fill_f,
            filled=filled,
            fees=float(fees or 0.0),
            probability=entry.probability,
            ttc_seconds=entry.ttc_seconds,
            detail=detail,
        ),
        None,
    )
