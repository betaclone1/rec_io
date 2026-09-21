"""
Combined flip-sell execution helpers.

Close of the stopped trade and open of the flip leg are independent trade rows, but
share one Kalshi buy of the opposite leg sized as close_qty + flip_qty. Fills allocate
close-first, then remainder to the flip open.
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple


FLIP_SELL_COMBINED_INTENT = "close_with_flip_sell"


def allocate_combined_flip_fills(
    total_fill: float,
    close_qty: float,
    flip_qty: float,
) -> Tuple[float, float]:
    """
    Split a single opposite-leg fill across close then flip.

    Returns (close_fill, flip_fill). Never negative; never exceeds requested qtys.
    """
    try:
        filled = float(total_fill or 0.0)
    except (TypeError, ValueError):
        filled = 0.0
    try:
        close_need = max(0.0, float(close_qty or 0.0))
    except (TypeError, ValueError):
        close_need = 0.0
    try:
        flip_need = max(0.0, float(flip_qty or 0.0))
    except (TypeError, ValueError):
        flip_need = 0.0

    if filled <= 0:
        return 0.0, 0.0

    close_fill = min(filled, close_need)
    remainder = max(0.0, filled - close_fill)
    flip_fill = min(remainder, flip_need)
    return close_fill, flip_fill


def allocate_combined_flip_fees(
    total_fees: float,
    close_fill: float,
    flip_fill: float,
) -> Tuple[float, float]:
    """Pro-rate order fees by filled contracts (close vs flip)."""
    try:
        fees = float(total_fees or 0.0)
    except (TypeError, ValueError):
        fees = 0.0
    try:
        c = max(0.0, float(close_fill or 0.0))
    except (TypeError, ValueError):
        c = 0.0
    try:
        f = max(0.0, float(flip_fill or 0.0))
    except (TypeError, ValueError):
        f = 0.0
    total = c + f
    if fees <= 0 or total <= 0:
        return 0.0, 0.0
    close_fees = round(fees * (c / total), 6)
    flip_fees = round(fees - close_fees, 6)
    return close_fees, flip_fees


def combined_order_count(close_qty: float, flip_qty: float) -> float:
    try:
        c = max(0.0, float(close_qty or 0.0))
    except (TypeError, ValueError):
        c = 0.0
    try:
        f = max(0.0, float(flip_qty or 0.0))
    except (TypeError, ValueError):
        f = 0.0
    return c + f


def close_fill_is_complete(close_fill: float, close_qty: float, *, eps: float = 0.02) -> bool:
    """True when allocated close fill covers the stopped position (Kalshi fp tolerance)."""
    try:
        return float(close_fill or 0.0) + float(eps) >= float(close_qty or 0.0)
    except (TypeError, ValueError):
        return False


def normalize_flip_sell_payload(raw: Any) -> Optional[Dict[str, Any]]:
    """Validate ATS/TM flip_sell block on a close request. None if absent/invalid."""
    if not isinstance(raw, dict):
        return None
    side = raw.get("side")
    if side is None or str(side).strip() == "":
        return None
    try:
        position = float(raw.get("position") or raw.get("count") or 0)
    except (TypeError, ValueError):
        return None
    if position < 1:
        return None
    out = dict(raw)
    out["side"] = str(side).strip().upper()
    if out["side"] in ("YES",):
        out["side"] = "Y"
    elif out["side"] in ("NO",):
        out["side"] = "N"
    out["position"] = max(1, int(round(position)))
    out["entry_method"] = str(raw.get("entry_method") or "flip_sell").strip().lower() or "flip_sell"
    return out
