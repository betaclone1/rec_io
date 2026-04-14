"""
Active 15m monitors for the unified AES/ATS supervisor pool.

SQL uses ``users.monitor_list_0001`` as a template; :class:`~backend.core.tenant_context.TenantConnection`
rewrites it to the worker's ``users_<slot>.monitor_list_<slot>``.
"""
from __future__ import annotations

import logging
from typing import Iterator, List, Tuple

from backend.core.config.database import get_postgresql_connection
from backend.core.port_config import default_pool_user_number

_log = logging.getLogger(__name__)


def iter_active_15m_monitor_bindings() -> Iterator[Tuple[str, str]]:
    """Yield (user_number, monitor_id) for each active 15m monitor on this worker's tenant."""
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
            worker = default_pool_user_number()
            for mid, name, symbol, market in cursor.fetchall():
                # Rows already come from this process tenant; bind AES/ATS with worker slot (not name parse).
                user_number = worker
                monitor_id = str(mid)
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
