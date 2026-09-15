"""ATS PRE consume gate (always allowed; PRE never places orders)."""

from __future__ import annotations

from typing import Tuple


def assert_paper_consume_allowed(
    paper_trade: bool = True,
    mode: str = "paper",
) -> Tuple[bool, str]:
    """
    PRE close consume is allowed everywhere PRE decisions exist.

    paper_trade / mode args are retained for call-site compatibility and ignored.
    """
    _ = paper_trade, mode
    return True, "ok"


def paper_arm_enabled() -> bool:
    """Deprecated compatibility stub — always True."""
    return True


def ats_consume_enabled() -> bool:
    """Deprecated compatibility stub — always True."""
    return True
