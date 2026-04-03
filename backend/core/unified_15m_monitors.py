"""
Active 15m monitors for the unified AES/ATS supervisor pool (users.monitor_list_0001).
"""
from __future__ import annotations

import logging
from typing import Iterator, List, Tuple

from backend.core.config.database import get_postgresql_connection

_log = logging.getLogger(__name__)


def iter_active_15m_monitor_bindings() -> Iterator[Tuple[str, str]]:
    """Yield (user_number, monitor_id) for each active 15m monitor (table monitor_list_0001)."""
    for row in list_active_15m_monitor_rows():
        yield row["user_number"], row["monitor_id"]


def list_active_15m_monitor_rows() -> List[dict]:
    """Rows with user_number, monitor_id, db_id, name, symbol, market."""
    out: List[dict] = []
    try:
        conn = get_postgresql_connection()
        if not conn:
            return out
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, name, symbol, COALESCE(NULLIF(TRIM(market), ''), 'hourly') AS market
                FROM users.monitor_list_0001
                WHERE status = 'active'
                  AND LOWER(TRIM(COALESCE(NULLIF(TRIM(market), ''), 'hourly'))) = '15m'
                ORDER BY id
                """
            )
            for mid, name, symbol, market in cursor.fetchall():
                user_number = "0001"
                monitor_id = str(mid)
                if name and str(name).startswith("mon_"):
                    parts = str(name).split("_")
                    if len(parts) >= 3:
                        user_number = parts[1]
                sym_u = str(symbol or "BTC").strip().upper() or "BTC"
                mkt = str(market or "15m").strip().lower()
                if mkt != "15m":
                    mkt = "15m"
                out.append(
                    {
                        "user_number": user_number,
                        "monitor_id": monitor_id,
                        "db_id": str(mid),
                        "name": name,
                        "symbol": sym_u,
                        "market": mkt,
                    }
                )
        conn.close()
    except Exception:
        pass
    return out
