"""
Active hourly monitors for the unified AES/ATS supervisor pool (users.monitor_list_0001).

Normalized market is `hourly` when `market` is blank or explicitly hourly (same convention as 15m discovery).
"""
from __future__ import annotations

import logging
from typing import Iterator, List, Tuple

from backend.core.config.database import get_postgresql_connection

_log = logging.getLogger(__name__)

_MARKET_HOURLY_SQL = (
    "LOWER(TRIM(COALESCE(NULLIF(TRIM(market), ''), 'hourly'))) = 'hourly'"
)


def iter_active_hourly_monitor_bindings() -> Iterator[Tuple[str, str]]:
    """Yield (user_number, monitor_id) for each active hourly monitor (table monitor_list_0001)."""
    for row in list_active_hourly_monitor_rows():
        yield row["user_number"], row["monitor_id"]


def list_active_hourly_monitor_rows() -> List[dict]:
    """Rows with user_number, monitor_id, db_id, name."""
    out: List[dict] = []
    try:
        conn = get_postgresql_connection()
        if not conn:
            return out
        with conn.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT id, name, symbol, COALESCE(NULLIF(TRIM(market), ''), 'hourly') AS market
                FROM users.monitor_list_0001
                WHERE status = 'active'
                  AND {_MARKET_HOURLY_SQL}
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
                        monitor_id = parts[2]
                sym_u = str(symbol or "BTC").strip().upper() or "BTC"
                mkt = str(market or "hourly").strip().lower()
                if mkt not in ("hourly", "15m"):
                    mkt = "hourly"
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
