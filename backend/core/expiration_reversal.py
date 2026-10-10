"""Expiration Reversal: Expiration Scalp entries as paper/test signals, live-capable flips.

Entry, gates, and exits are identical to Expiration Scalp. Every original entry is
recorded ``paper_trade=TRUE`` / ``test_filter=TRUE`` regardless of monitor flags.
A stop-loss-floor auto stop always flips (``flip_sell_floor`` is forced TRUE for this
strategy). The flip row follows the monitor's own ``paper_trade`` / ``test_filter``:
paper monitor -> paper non-test flip; live monitor -> live flip executed on Kalshi as a
standalone open (the paper parent close never touches the venue).
"""

from __future__ import annotations

from typing import Any, Optional

STRATEGY_NAME = "Expiration Reversal"


def _strategy_base_name(strategy: Optional[str]) -> str:
    raw = str(strategy or "").strip()
    if raw.startswith("Reverse "):
        raw = raw[len("Reverse ") :].strip()
    return raw


def is_expiration_reversal(strategy: Optional[str]) -> bool:
    return _strategy_base_name(strategy) == STRATEGY_NAME


def _flag(v: Any) -> bool:
    if isinstance(v, str):
        return v.strip().lower() in ("true", "1", "yes")
    return bool(v) if v is not None else False


def flip_execution_flags(monitor_paper_trade: Any, monitor_test_filter: Any) -> tuple[bool, bool]:
    """(paper_trade, test_filter) for an ER flip row from the monitor's own flags.

    ``test_filter`` implies paper (same rule as ``insert_trade``).
    """
    test_filter = _flag(monitor_test_filter)
    paper_trade = _flag(monitor_paper_trade) or test_filter
    return paper_trade, test_filter
