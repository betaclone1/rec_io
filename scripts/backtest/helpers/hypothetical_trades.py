"""
Recompute fees, PnL, and return % for trades under hypothetical position/prices.

Fee model matches ``backend/trade_manager.estimate_kalshi_taker_fee`` (taker-only,
open at buy_price, close at 1 - sell_price for the fee leg).
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta
from typing import Any, Mapping, Optional

try:
    from zoneinfo import ZoneInfo
except ImportError:
    ZoneInfo = None  # type: ignore


def estimate_kalshi_taker_fee(position: int, price: float) -> float:
    """One-leg taker fee: 0.07 * C * P * (1-P), rounded up to cents (trade_manager)."""
    if position is None or position <= 0 or price is None or price <= 0 or price >= 1:
        return 0.0
    raw = 0.07 * position * price * (1.0 - price)
    return math.ceil(raw * 100) / 100


def total_taker_fees_hypothetical(position: int, buy_price: float, sell_price: float) -> float:
    """Open leg at buy_price; close leg price for fee = (1 - sell_price)."""
    o = estimate_kalshi_taker_fee(position, float(buy_price))
    c = estimate_kalshi_taker_fee(position, 1.0 - float(sell_price))
    return round(o + c, 2)


def open_to_next_boundary_minutes(
    created_at: datetime,
    tz_name: str,
    *,
    grid_15m: bool,
) -> Optional[float]:
    """Minutes until next hourly or 15m boundary in ``tz_name`` (matches trade_filters SQL)."""
    if ZoneInfo is None or created_at is None:
        return None
    z = ZoneInfo(tz_name)
    if created_at.tzinfo is None:
        return None
    local = created_at.astimezone(z)
    if grid_15m:
        h = local.replace(minute=0, second=0, microsecond=0)
        q = local.minute // 15
        nxt = h + timedelta(minutes=15 * (q + 1))
    else:
        nxt = local.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    delta = nxt - local
    return delta.total_seconds() / 60.0


def recompute_closed_trade_hypothetical(
    row: Mapping[str, Any],
    *,
    position: int,
    buy_price: Optional[float] = None,
    sell_price: Optional[float] = None,
) -> Optional[dict[str, Any]]:
    """
    Returns dict with hypo_fees, hypo_pnl, hypo_ret_pct, hypo_ret_pct_base, hypo_roi_pct, hypo_win_loss
    or None if row cannot be closed PnL (missing prices/position).
    """
    st = (row.get("status") or "").strip().lower()
    if st not in ("closed", "settled"):
        return None
    bp = buy_price if buy_price is not None else row.get("buy_price")
    sp = sell_price if sell_price is not None else row.get("sell_price")
    if bp is None or sp is None or position is None or position <= 0:
        return None
    bp_f, sp_f = float(bp), float(sp)
    fees = total_taker_fees_hypothetical(position, bp_f, sp_f)
    buy_v = bp_f * position
    sell_v = sp_f * position
    pnl = round(sell_v - buy_v - fees, 2)
    bankroll = row.get("bankroll")
    mtb = row.get("mtb_base_value")
    ret_pct = None
    ret_pct_base = None
    roi_pct = None
    if bankroll is not None and float(bankroll) > 0:
        ret_pct = round((pnl / (float(bankroll) / 100.0)) * 100, 5)
    if mtb is not None and float(mtb) > 0:
        ret_pct_base = round((pnl / (float(mtb) / 100.0)) * 100, 5)
    if buy_v > 0:
        roi_pct = round((pnl / buy_v) * 100.0, 5)
    wl = "W" if pnl > 0 else ("L" if pnl < 0 else "D")
    return {
        "hypo_fees": fees,
        "hypo_pnl": pnl,
        "hypo_ret_pct": ret_pct,
        "hypo_ret_pct_base": ret_pct_base,
        "hypo_roi_pct": roi_pct,
        "hypo_win_loss": wl,
    }


def apply_overrides(
    row: Mapping[str, Any],
    *,
    position: Optional[int] = None,
    buy_price: Optional[float] = None,
    sell_price: Optional[float] = None,
    paper_trade: Optional[bool] = None,
) -> dict[str, Any]:
    """Shallow copy row as dict with scalar overrides."""
    d = dict(row)
    if position is not None:
        d["position"] = position
    if buy_price is not None:
        d["buy_price"] = buy_price
    if sell_price is not None:
        d["sell_price"] = sell_price
    if paper_trade is not None:
        d["paper_trade"] = paper_trade
    return d
