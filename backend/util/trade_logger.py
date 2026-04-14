"""Trade log lines in PostgreSQL (per-tenant ``trade_logs_<slot>``).

SQL uses the template ``users.trade_logs_0001``; :class:`~backend.core.tenant_context.TenantConnection`
rewrites it to ``users_<slot>.trade_logs_<slot>`` for workers and API-bound connections.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

from backend.core.config.database import get_postgresql_connection

# Template table name only — never target another slot literally in SQL strings.
_TRADE_LOGS_TABLE_SQL = "users.trade_logs_0001"


def _effective_trade_log_user_id(explicit: Optional[str]) -> str:
    """Row ``user_id`` column: explicit, else HTTP session slot, else worker tenant, else 0001."""
    if explicit is not None and str(explicit).strip():
        e = str(explicit).strip()
        if e.startswith("user_"):
            return e
        if e.isdigit() and len(e) == 4:
            return f"user_{e}"
        return e
    try:
        from backend.web.tenant_asgi import get_web_api_user_no

        w = get_web_api_user_no()
        if w:
            w = str(w).strip()
            return w if w.startswith("user_") else f"user_{w}"
    except Exception:
        pass
    try:
        from backend.core.tenant_context import get_worker_tenant_context

        return f"user_{get_worker_tenant_context().user_no}"
    except Exception:
        pass
    return "user_0001"


def log_trade_event(
    ticket_id: str,
    message: str,
    service: str = "unknown",
    user_id: Optional[str] = None,
) -> None:
    """
    Log trade events to this process/API tenant's trade_logs table.

    Args:
        ticket_id: Ticket id for the trade
        message: Log message
        service: Source service name (e.g. trade_manager, trade_executor)
        user_id: Optional ``user_NNNN`` for the row; if omitted, resolved from tenant context
    """
    try:
        timestamp = datetime.now(ZoneInfo("America/New_York"))
        user_for_row = _effective_trade_log_user_id(user_id)

        conn = get_postgresql_connection()
        if not conn:
            print(f"Failed to log trade event: {message}")
            return

        with conn.cursor() as cursor:
            cursor.execute(
                f"""
                INSERT INTO {_TRADE_LOGS_TABLE_SQL}
                (ticket_id, message, timestamp, service, user_id)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (ticket_id, message, timestamp, service, user_for_row),
            )
            conn.commit()

        conn.close()

        formatted_time = timestamp.strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{formatted_time}] {service.upper()} Ticket {ticket_id[-5:]}: {message}")

    except Exception as e:
        print(f"Error logging trade event: {e}")


def get_trade_logs(
    ticket_id: Optional[str] = None,
    service: Optional[str] = None,
    limit: int = 100,
    user_id: Optional[str] = None,
):
    """
    Read trade logs for the current API tenant (or explicit user_id / worker tenant).

    Returns:
        List of dicts with ticket_id, message, timestamp, service
    """
    try:
        user_for_filter = _effective_trade_log_user_id(user_id)

        conn = get_postgresql_connection()
        if not conn:
            return []

        query = (
            f"SELECT ticket_id, message, timestamp, service FROM {_TRADE_LOGS_TABLE_SQL} "
            "WHERE user_id = %s"
        )
        params: list = [user_for_filter]

        if ticket_id:
            query += " AND ticket_id = %s"
            params.append(ticket_id)

        if service:
            query += " AND service = %s"
            params.append(service)

        query += " ORDER BY timestamp DESC LIMIT %s"
        params.append(limit)

        with conn.cursor() as cursor:
            cursor.execute(query, params)
            results = cursor.fetchall()

        conn.close()

        return [
            {
                "ticket_id": row[0],
                "message": row[1],
                "timestamp": row[2].isoformat() if row[2] else None,
                "service": row[3],
            }
            for row in results
        ]

    except Exception as e:
        print(f"Error retrieving trade logs: {e}")
        return []
