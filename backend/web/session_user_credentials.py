"""
Session-scoped user row from ``system.master_users`` (web tenant from middleware).
"""

from __future__ import annotations

import logging
from typing import Any, Dict

from backend.core.config.database import get_system_postgresql_connection
from backend.core.tenant_context import resolved_tenant_user_no_for_app

_LOG = logging.getLogger(__name__)


def fetch_session_master_user_credentials() -> Dict[str, Any]:
    """Display credentials for the bound HTTP tenant (four-digit slot)."""
    try:
        u = resolved_tenant_user_no_for_app()
        conn = get_system_postgresql_connection()
        if not conn:
            raise RuntimeError("Database connection failed")
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT user_id, first_name, last_name, email, phone, account_type, password_hash, name
                FROM system.master_users
                WHERE LPAD(TRIM(user_no::text), 4, '0') = %s
                LIMIT 1
                """,
                (u,),
            )
            result = cursor.fetchone()
        conn.close()
        if result:
            user_id, first_name, last_name, email, phone, account_type, password_hash, name = result
            parts = [p for p in (str(first_name or "").strip(), str(last_name or "").strip()) if p]
            disp = " ".join(parts) if parts else (str(name).strip() if name is not None else "")
            return {
                "username": user_id,
                "name": disp,
                "email": email,
                "phone": phone,
                "account_type": account_type,
                "password_hash": password_hash,
            }
    except Exception as e:
        _LOG.warning("session master_users credentials: %s", e)

    return {}
