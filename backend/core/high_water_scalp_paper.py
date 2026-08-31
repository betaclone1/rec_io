"""Paper High Water Scalp: simulate resting GTC fills from the live Redis book.

Paper cannot rest a Kalshi GTC. ATS walks the same Redis orderbook used for
paper IOC and estimates fills at ``1 - limit_close_price``. Missing/stale
book → skip (no invented price). Simulated GTC fills carry ``close_fee=0``
(maker rest).
"""

from __future__ import annotations

from typing import Any, Optional

from backend.core.high_water_scalp import simulate_paper_resting_gtc
from backend.core.orderbook_strike_prices import load_fresh_orderbook_levels


def evaluate_paper_resting_gtc(
    ticker: Optional[str],
    owned_side: Optional[str],
    limit_close_price,
    remaining: float,
    last_available: float,
) -> dict[str, Any]:
    """Load a fresh Redis book and return a paper GTC fill decision."""
    yes_levels, no_levels, reason = load_fresh_orderbook_levels(str(ticker or "").strip())
    if yes_levels is None or no_levels is None:
        return {
            "ok": False,
            "reason": reason,
            "available": None,
            "fill_qty": 0.0,
            "opp_vwap": None,
            "owned_sell_vwap": None,
            "close_fee": None,
            "reset_last": False,
        }
    return simulate_paper_resting_gtc(
        yes_levels,
        no_levels,
        owned_side,
        limit_close_price,
        remaining,
        last_available,
    )
