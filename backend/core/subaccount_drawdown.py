"""
Per-subaccount drawdown halt controls on ``subaccounts_*`` / ``subaccounts_paper_*``.

Mirrors the system_settings drawdown columns, scoped to one Kalshi subaccount id.
"""

from __future__ import annotations

import logging
import re
from decimal import Decimal
from typing import Any, Optional, Tuple

from psycopg2 import sql

_LOG = logging.getLogger(__name__)

_DEFAULT_HALT = True
_DEFAULT_THRESHOLD_PCT = Decimal("50.00")

_SA_FQN_RE = re.compile(
    r"^users\.subaccounts(?:_paper)?_\d{4}$"
    r"|^users_(?P<s>\d{4})\.subaccounts(?:_paper)?_(?P=s)$"
)


def _split_fqn(fqn: str) -> Tuple[str, str]:
    parts = str(fqn).split(".", 1)
    if len(parts) != 2:
        raise ValueError(f"Invalid subaccounts fqn: {fqn}")
    return parts[0], parts[1]


def _allowed_subaccounts_fqn(subaccounts_table: str) -> bool:
    return bool(_SA_FQN_RE.match(str(subaccounts_table)))


def get_subaccount_drawdown_controls(
    cursor: Any,
    subaccounts_table: str,
    *,
    subaccount_id: int,
) -> Tuple[bool, Decimal]:
    """
    Return ``(drawdown_trading_halt, drawdown_reset_threshold_pct)`` for one subaccount.
    Missing row/columns → defaults (True, 50).
    """
    if not _allowed_subaccounts_fqn(subaccounts_table):
        return _DEFAULT_HALT, _DEFAULT_THRESHOLD_PCT
    try:
        sa_id = int(subaccount_id)
    except (TypeError, ValueError):
        return _DEFAULT_HALT, _DEFAULT_THRESHOLD_PCT

    sch, tbl = _split_fqn(subaccounts_table)
    ident = sql.SQL("{}.{}").format(sql.Identifier(sch), sql.Identifier(tbl))
    try:
        cursor.execute(
            sql.SQL(
                """
                SELECT drawdown_trading_halt, drawdown_reset_threshold_pct
                FROM {} WHERE id = %s
                """
            ).format(ident),
            (sa_id,),
        )
        row = cursor.fetchone()
    except Exception as exc:
        _LOG.debug(
            "get_subaccount_drawdown_controls failed table=%s id=%s: %s",
            subaccounts_table,
            sa_id,
            exc,
        )
        return _DEFAULT_HALT, _DEFAULT_THRESHOLD_PCT

    if not row:
        return _DEFAULT_HALT, _DEFAULT_THRESHOLD_PCT
    if isinstance(row, dict):
        halt = row.get("drawdown_trading_halt")
        pct = row.get("drawdown_reset_threshold_pct")
    else:
        halt, pct = row[0], row[1]
    halt_on = bool(halt) if halt is not None else _DEFAULT_HALT
    if pct is None:
        return halt_on, _DEFAULT_THRESHOLD_PCT
    try:
        return halt_on, Decimal(str(pct))
    except Exception:
        return halt_on, _DEFAULT_THRESHOLD_PCT


def set_subaccount_trading_halt_active_with_cursor(
    cursor: Any,
    subaccounts_table: str,
    *,
    subaccount_id: int,
    active: bool,
) -> int:
    if not _allowed_subaccounts_fqn(subaccounts_table):
        return 0
    sch, tbl = _split_fqn(subaccounts_table)
    ident = sql.SQL("{}.{}").format(sql.Identifier(sch), sql.Identifier(tbl))
    cursor.execute(
        sql.SQL(
            "UPDATE {} SET trading_halt_active = %s WHERE id = %s"
        ).format(ident),
        (bool(active), int(subaccount_id)),
    )
    return int(cursor.rowcount or 0)


def set_subaccount_drawdown_halt_snapshot_with_cursor(
    cursor: Any,
    subaccounts_table: str,
    *,
    subaccount_id: int,
    snapshot: Optional[dict],
) -> int:
    from psycopg2.extras import Json

    if not _allowed_subaccounts_fqn(subaccounts_table):
        return 0
    sch, tbl = _split_fqn(subaccounts_table)
    ident = sql.SQL("{}.{}").format(sql.Identifier(sch), sql.Identifier(tbl))
    val = Json(snapshot) if snapshot is not None else None
    cursor.execute(
        sql.SQL(
            "UPDATE {} SET drawdown_halt_monitor_snapshot = %s WHERE id = %s"
        ).format(ident),
        (val, int(subaccount_id)),
    )
    return int(cursor.rowcount or 0)


def get_subaccount_trading_halt_active_with_cursor(
    cursor: Any,
    subaccounts_table: str,
    *,
    subaccount_id: int,
) -> bool:
    if not _allowed_subaccounts_fqn(subaccounts_table):
        return False
    sch, tbl = _split_fqn(subaccounts_table)
    ident = sql.SQL("{}.{}").format(sql.Identifier(sch), sql.Identifier(tbl))
    try:
        cursor.execute(
            sql.SQL(
                "SELECT COALESCE(trading_halt_active, false) FROM {} WHERE id = %s"
            ).format(ident),
            (int(subaccount_id),),
        )
        row = cursor.fetchone()
    except Exception:
        return False
    if not row:
        return False
    return bool(row[0] if not isinstance(row, dict) else row.get("trading_halt_active"))
