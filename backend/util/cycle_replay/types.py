from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, Optional


@dataclass
class EntryEvent:
    timestamp: datetime
    side: str  # trades.side: Y or N
    buy_price: float  # filled VWAP after paper ladder walk (trades.buy_price)
    probability: float
    ttc_seconds: int
    ticket_ask: Optional[float] = None  # gate ask / initial_price before fill
    filled: Optional[int] = None  # trades.position
    fees: Optional[float] = None  # trades.fees / initial_proj_fees (open leg estimate)
    detail: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ExitEvent:
    timestamp: datetime
    reason: str  # stop_loss_floor | expired | still_open
    sell_price: Optional[float] = None
    status: str = "closed"  # trades.status
    close_method: Optional[str] = None  # trades.close_method (expired, …)
    market_result: Optional[str] = None  # yes|no
    win_loss: Optional[str] = None  # W|L
    detail: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ReplayPosition:
    side: str  # Y or N
    entry: EntryEvent
    exit: Optional[ExitEvent] = None
