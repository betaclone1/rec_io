"""Executable whole-cent liquidation walk for HWS position risk.

YES liquidates into YES bids.
NO liquidates into implied NO bids derived from canonical YES asks (1 - yes_ask),
using complementary_asks(..., side='yes') when possible.

Compares **gross** LVWAP to the operator floor; fee / slippage / net are separate fields.
Partial coverage is never treated as a valid normal VWAP.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

from backend.core.cycle_recon.measurements import complementary_asks


def _f(v: Any) -> Optional[float]:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _yes_bids(yes: Dict[str, str]) -> List[Tuple[float, float]]:
    bids: List[Tuple[float, float]] = []
    for px, qty in (yes or {}).items():
        p = _f(px)
        q = _f(qty)
        if p is None or q is None or p <= 0 or p >= 1 or q <= 0:
            continue
        bids.append((p, q))
    bids.sort(key=lambda x: -x[0])
    return bids


def _implied_no_bids_from_yes_asks(
    yes: Dict[str, str],
    no: Dict[str, str],
) -> List[Tuple[float, float]]:
    """Implied NO bid = 1 - YES ask; YES asks from complementary_asks(side=yes)."""
    yes_asks = complementary_asks(yes, no, "yes")
    levels: List[Tuple[float, float]] = []
    for ask, sz in yes_asks:
        bid = 1.0 - float(ask)
        if bid <= 0 or bid >= 1 or float(sz) <= 0:
            continue
        levels.append((bid, float(sz)))
    levels.sort(key=lambda x: -x[0])
    return levels


def executable_bid_levels(
    yes: Dict[str, str],
    no: Dict[str, str],
    side: str,
) -> List[Tuple[float, float]]:
    side_n = str(side).strip().lower()
    if side_n in ("y", "yes"):
        return _yes_bids(yes)
    return _implied_no_bids_from_yes_asks(yes, no)


def walk_executable_liquidation(
    yes: Dict[str, str],
    no: Dict[str, str],
    side: str,
    size: float,
    *,
    estimated_taker_fee_per_contract: Optional[float] = None,
    slippage_reserve: Optional[float] = None,
) -> Dict[str, Any]:
    """
    Walk executable depth for exact remaining size.

    Returns gross LVWAP only when full-size coverage is achieved.
    Fee / slippage / net are separate and never folded into gross.
    """
    size_f = float(size)
    levels = executable_bid_levels(yes, no, side)
    rem = size_f
    filled = 0.0
    notional = 0.0
    worst: Optional[float] = None
    best: Optional[float] = levels[0][0] if levels else None
    levels_consumed: List[Dict[str, float]] = []

    for px, q in levels:
        if rem <= 0:
            break
        take = min(rem, q)
        notional += px * take
        filled += take
        worst = px
        levels_consumed.append({"price": float(px), "size": float(take)})
        rem -= take

    full = size_f > 0 and filled + 1e-9 >= size_f
    gross_lvwap: Optional[float] = (
        round(notional / filled, 6) if (full and filled > 0) else None
    )
    fee = _f(estimated_taker_fee_per_contract)
    slip = _f(slippage_reserve)
    net_lvwap: Optional[float] = None
    if gross_lvwap is not None:
        net_lvwap = float(gross_lvwap)
        if fee is not None:
            net_lvwap -= fee
        if slip is not None:
            net_lvwap -= slip
        net_lvwap = round(net_lvwap, 6)

    return {
        "ok": full,
        "full_coverage": full,
        "reason": "ok" if full else "DEPTH_INSUFFICIENT",
        "gross_lvwap": gross_lvwap,
        "liquidation_vwap": gross_lvwap,  # alias: always gross
        "estimated_taker_fee": fee,
        "slippage_reserve": slip,
        "net_lvwap": net_lvwap,
        "filled": filled,
        "size": size_f,
        "best": best,
        "worst": worst,
        "worst_consumed_price": worst,
        "coverage": (filled / size_f) if size_f else None,
        "available": sum(q for _, q in levels),
        "levels_consumed": levels_consumed,
        "levels_consumed_count": len(levels_consumed),
    }


def walk_sell_into_bids(
    yes: Dict[str, str],
    no: Dict[str, str],
    side: str,
    size: float,
) -> Dict[str, Any]:
    """Backward-compatible thin wrapper used by Stage 1 shadow features."""
    out = walk_executable_liquidation(yes, no, side, size)
    return {
        "ok": bool(out.get("ok")),
        "vwap": out.get("gross_lvwap"),
        "filled": out.get("filled"),
        "best": out.get("best"),
        "worst": out.get("worst"),
        "coverage": out.get("coverage"),
        "available": out.get("available"),
        "reason": out.get("reason"),
    }
