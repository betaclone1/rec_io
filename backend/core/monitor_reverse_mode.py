"""Monitor REVERSE mode helpers (opposite-side dispatch, display naming)."""

from __future__ import annotations

from typing import Any, Dict, Optional


def flip_side(side: Optional[str]) -> Optional[str]:
    s = (side or "").strip().lower()
    if s in ("yes", "y"):
        return "no"
    if s in ("no", "n"):
        return "yes"
    return side


def effective_trade_strategy(base_strategy: Optional[str], reverse: bool) -> str:
    base = (base_strategy or "").strip() or "Hourly HTC"
    if reverse:
        return f"Reverse {base}"
    return base


def find_strike_row(strike_table_data: Optional[dict], ticker: Optional[str]) -> Optional[dict]:
    if not strike_table_data or not ticker:
        return None
    for row in strike_table_data.get("strikes") or []:
        if row.get("ticker") == ticker:
            return row
    return None


def apply_reverse_to_strike_data(
    strike_data: Dict[str, Any],
    strike_table_data: Optional[dict],
    *,
    reverse: bool,
) -> Dict[str, Any]:
    """Flip side/buy_price/diff for opposite-leg execution when reverse is enabled."""
    if not reverse:
        return strike_data
    sd = dict(strike_data)
    opp = flip_side(sd.get("side"))
    sd["side"] = opp
    row = find_strike_row(strike_table_data, sd.get("ticker"))
    if row and opp:
        if opp == "no":
            ask = row.get("no_ask_dollars")
            diff = row.get("no_diff")
        else:
            ask = row.get("yes_ask_dollars")
            diff = row.get("yes_diff")
        if ask is not None:
            sd["buy_price"] = float(ask)
        if diff is not None:
            sd["diff"] = diff
    return sd


def executed_side_for_dedupe(side: Optional[str], *, reverse: bool) -> Optional[str]:
    if reverse:
        return flip_side(side)
    return side


def resolve_trade_strategy_for_insert(
    trade_strategy: Optional[str],
    monitor_state: Optional[dict],
) -> str:
    """Persist ``Reverse {strategy}`` on trades when monitor reverse mode is enabled."""
    raw = (trade_strategy or "").strip()
    if monitor_state and monitor_state.get("reverse"):
        base = raw or (monitor_state.get("strategy") or "").strip() or "Hourly HTC"
        if base.startswith("Reverse "):
            return base
        return effective_trade_strategy(base, True)
    return raw or "Hourly HTC"
