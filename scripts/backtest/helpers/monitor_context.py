"""Resolve monitor_list row and strategy semantics for backtests."""

from __future__ import annotations

import re
from typing import Any, Mapping, Optional

# Align with backend/monitor_manager.py and trade_manager cycle logic.
_CYCLE_STRATEGY_SUBSTRINGS = ("Momentum Contain", "Momentum Breakout")


def parse_monitor_token(monitor: str) -> Optional[tuple[str, int]]:
    """
    Parse ``mon_0001_10023`` -> (user_number ``0001``, monitor id ``10023``).
    Returns None if the label does not match the expected pattern.
    """
    if not monitor:
        return None
    parts = str(monitor).split("_")
    if len(parts) < 3 or parts[0].lower() != "mon":
        return None
    user_number = parts[-2]
    mid_s = parts[-1]
    if not re.fullmatch(r"\d+", user_number) or not re.fullmatch(r"\d+", mid_s):
        return None
    return user_number, int(mid_s)


def monitor_list_table_name(user_number: str) -> str:
    if not re.fullmatch(r"\d+", user_number):
        raise ValueError(f"invalid user_number for monitor_list: {user_number!r}")
    return f"users.monitor_list_{user_number}"


def is_cycle_based_strategy(strategy: Optional[str]) -> bool:
    """Momentum Contain / Breakout: two-leg cycles; W/L from cycle aggregate PnL (see trade_manager)."""
    if not strategy:
        return False
    return any(s in strategy for s in _CYCLE_STRATEGY_SUBSTRINGS)


def fetch_monitor_settings(cur, user_number: str, monitor_id: int) -> Optional[dict[str, Any]]:
    """Load one row from ``monitor_list_<user>`` or None if missing."""
    table = monitor_list_table_name(user_number)
    cur.execute(
        f"""
        SELECT id, name, symbol, strategy, status, auto_trade, paper_trade
        FROM {table}
        WHERE id = %s
        """,
        (monitor_id,),
    )
    row = cur.fetchone()
    if not row:
        return None
    cols = [d[0] for d in cur.description]
    return dict(zip(cols, row))


def fetch_monitor_risk_settings(cur, user_number: str, monitor_id: int) -> Optional[dict[str, Any]]:
    """Columns needed for risk replay: sizing, loss prevention, optional regime pre-filter."""
    table = monitor_list_table_name(user_number)
    cur.execute(
        f"""
        SELECT
            id, name, symbol, strategy,
            position_size, position_type, multiplier,
            bankroll_allotment_total,
            current_max_pct_exposure,
            performance_based_allocation,
            win_streak_threshold, loss_prevention_toggle,
            regime_monitor_enabled, regime_window
        FROM {table}
        WHERE id = %s
        """,
        (monitor_id,),
    )
    row = cur.fetchone()
    if not row:
        return None
    cols = [d[0] for d in cur.description]
    return dict(zip(cols, row))


def format_monitor_settings_brief(m: Mapping[str, Any]) -> str:
    parts = [
        f"id={m.get('id')}",
        f"name={m.get('name')!r}",
        f"symbol={m.get('symbol')}",
        f"strategy={m.get('strategy')!r}",
        f"status={m.get('status')}",
        f"auto_trade={m.get('auto_trade')}",
        f"paper_trade={m.get('paper_trade')}",
    ]
    return "  " + "  ".join(parts)
