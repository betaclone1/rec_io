"""
Active non-15m monitors for the unified AES/ATS hourly strike pool.

Uses a legacy ``users.monitor_list_<slot>`` name in SQL as a tenant-rewrite template (see unified_15m_monitors).
"""
from __future__ import annotations

import logging
from typing import Iterator, List, Tuple

from backend.core.config.database import get_postgresql_connection
from backend.core.port_config import default_pool_user_number
from backend.core.tenant_legacy_sql import legacy_users_monitor_list

_log = logging.getLogger(__name__)

_MARKET_NOT_15M_SQL = (
    "LOWER(TRIM(COALESCE(NULLIF(TRIM(market), ''), 'hourly'))) <> '15m'"
)


def iter_active_hourly_monitor_bindings() -> Iterator[Tuple[str, str]]:
    """Yield (user_number, monitor_id) for each active hourly monitor on this worker's tenant."""
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
            ml = legacy_users_monitor_list(default_pool_user_number())
            cursor.execute(
                f"""
                SELECT id, name, symbol, COALESCE(NULLIF(TRIM(market), ''), 'hourly') AS market
                FROM {ml}
                WHERE status = 'active'
                  AND {_MARKET_NOT_15M_SQL}
                ORDER BY id
                """
            )
            worker = default_pool_user_number()
            for mid, name, symbol, _market in cursor.fetchall():
                user_number = worker
                monitor_id = str(mid)
                sym_u = str(symbol or "BTC").strip().upper() or "BTC"
                out.append(
                    {
                        "user_number": user_number,
                        "monitor_id": monitor_id,
                        "db_id": str(mid),
                        "name": name,
                        "symbol": sym_u,
                        "market": "hourly",
                    }
                )
        conn.close()
    except Exception:
        pass
    return out
