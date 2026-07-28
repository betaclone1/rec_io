"""Normalize replay events to trades_* field shapes (Y/N side, closed/expired, etc.)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional

from backend.util.cycle_replay.types import EntryEvent, ExitEvent, ReplayPosition


def normalize_trade_side(side: Any) -> str:
    """Match trades.side storage: Y or N."""
    s = str(side or "").strip().lower()
    if s in ("y", "yes"):
        return "Y"
    if s in ("n", "no"):
        return "N"
    su = str(side or "").strip().upper()
    if su in ("Y", "N"):
        return su
    return su


def side_to_yes_no(side: Any) -> str:
    return "yes" if normalize_trade_side(side) == "Y" else "no"


def trade_row_from_position(
    *,
    ticker: str,
    position: ReplayPosition,
    market_result: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Flatten a replay position into trades_*-like keys for side-by-side compare.
    """
    e = position.entry
    x = position.exit
    side = normalize_trade_side(position.side or e.side)
    ticket = e.ticket_ask if e.ticket_ask is not None else e.buy_price

    row: Dict[str, Any] = {
        "ticker": ticker,
        "side": side,
        "buy_price": e.buy_price,
        "initial_price": ticket,
        "initial_proj_price": e.buy_price,
        "initial_proj_fees": e.fees,
        "position": e.filled,
        "fees": e.fees,
        "prob": e.probability,
        "entry_method": "auto_entry",
        "status": "open",
        "sell_price": None,
        "market_result": market_result,
        "win_loss": None,
        "close_method": None,
        "entry_time": _iso_z(e.timestamp),
        "entry_time_utc": _iso_z(e.timestamp),
        "closed_at": None,
        "closed_at_utc": None,
    }

    if x is not None:
        close_method = x.close_method or x.reason
        status = x.status or (
            "closed"
            if close_method
            in ("expired", "stop_loss_floor", "auto_stop_loss_floor")
            else "open"
        )
        closed = _iso_z(x.timestamp)
        row.update(
            {
                "status": status,
                "sell_price": x.sell_price,
                "market_result": x.market_result if x.market_result is not None else market_result,
                "win_loss": x.win_loss,
                "close_method": close_method,
                "closed_at": closed,
                "closed_at_utc": closed,
            }
        )
    return row


def _iso_z(dt: datetime) -> str:
    return dt.isoformat().replace("+00:00", "Z")
