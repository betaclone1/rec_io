"""
``system.master_users.exchange_credentials`` — which exchanges may use authenticated API calls.

When ``kalshi`` is false, tenant-scoped workers must not perform signed Kalshi requests,
even if key files exist. Supervisor sets ``REC_PAPER_ONLY_USER`` from the same rule plus on-disk keys.
"""

from __future__ import annotations

import json
import logging
import os
import time
import re
from typing import Any, Dict, Optional

_LOG = logging.getLogger(__name__)

DEFAULT_EXCHANGE_CREDENTIALS: Dict[str, bool] = {"kalshi": False, "polymarket": False}

_USER_NO_ENV_RE = re.compile(r"^\d{4}$")
_SCHEMA_RE = re.compile(r"^users_(\d{4})$", re.IGNORECASE)


def normalize_exchange_credentials(raw: Any) -> Dict[str, bool]:
    """Return ``{kalshi: bool, polymarket: bool}`` with defaults for missing keys."""
    data: Dict[str, Any]
    if raw is None:
        data = {}
    elif isinstance(raw, dict):
        data = raw
    elif isinstance(raw, str):
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return dict(DEFAULT_EXCHANGE_CREDENTIALS)
    else:
        try:
            data = dict(raw)
        except Exception:
            return dict(DEFAULT_EXCHANGE_CREDENTIALS)
    return {
        "kalshi": bool(data.get("kalshi")),
        "polymarket": bool(data.get("polymarket")),
    }


def tenant_user_no_from_worker_env() -> Optional[str]:
    """Resolve 4-digit slot from ``REC_USER_NO`` or ``REC_USER_SCHEMA``."""
    u = os.environ.get("REC_USER_NO", "").strip()
    if u and _USER_NO_ENV_RE.match(u):
        return u
    s = os.environ.get("REC_USER_SCHEMA", "").strip()
    m = _SCHEMA_RE.match(s)
    return m.group(1) if m else None


def _ensure_exchange_credentials_column(conn: Any) -> None:
    """Idempotent DDL for older DBs or drift vs ``schema_migrations`` (matches migration 20260410_2100)."""
    with conn.cursor() as cur:
        cur.execute(
            """
            ALTER TABLE system.master_users ADD COLUMN IF NOT EXISTS exchange_credentials JSONB
                NOT NULL DEFAULT '{"kalshi": false, "polymarket": false}'::jsonb
            """
        )
    conn.commit()


def ensure_system_master_users_exchange_credentials() -> bool:
    """
    Apply ``ADD COLUMN IF NOT EXISTS exchange_credentials`` on ``system.master_users``.

    Safe no-op when the column already exists. Use before any query that selects this column
    (e.g. admin listing) so schema matches migration ``20260410_2100`` even when ``schema_migrations``
    and reality diverged.
    """
    try:
        from backend.core.config.database import get_system_postgresql_connection

        conn = get_system_postgresql_connection()
        if not conn:
            return False
        try:
            _ensure_exchange_credentials_column(conn)
            return True
        finally:
            try:
                conn.close()
            except Exception:
                pass
    except Exception:
        return False


def _fetch_kalshi_flag_cursor(cur: Any, user_no: str) -> Optional[bool]:
    cur.execute(
        """
        SELECT exchange_credentials
        FROM system."master_users"
        WHERE LPAD(TRIM(user_no::text), 4, '0') = %s
        LIMIT 1
        """,
        (user_no,),
    )
    row = cur.fetchone()
    if not row or row[0] is None:
        return None
    norm = normalize_exchange_credentials(row[0])
    return bool(norm["kalshi"])


def fetch_kalshi_enabled_for_user_no(user_no: str) -> Optional[bool]:
    """
    Read ``exchange_credentials->kalshi`` for ``user_no``.

    Returns ``None`` if the row is missing or the query fails (callers may treat as unknown).
    """
    if not user_no or not _USER_NO_ENV_RE.match(user_no):
        return None
    try:
        from backend.core.config.database import get_system_postgresql_connection

        conn = get_system_postgresql_connection()
        if not conn:
            return None
        try:
            for attempt in (0, 1):
                try:
                    with conn.cursor() as cur:
                        return _fetch_kalshi_flag_cursor(cur, user_no)
                except Exception as exc:
                    err = str(exc).lower()
                    if (
                        attempt == 0
                        and "exchange_credentials" in err
                        and "does not exist" in err
                    ):
                        _LOG.debug(
                            "system.master_users.exchange_credentials missing; applying "
                            "ADD COLUMN IF NOT EXISTS (self-heal) on DB=%s",
                            _session_db_label(),
                        )
                        _ensure_exchange_credentials_column(conn)
                        continue
                    raise
        finally:
            try:
                conn.close()
            except Exception:
                pass
    except Exception as exc:
        # Paper-only tenants, missing column on old DBs, or transient DB errors: treat as
        # "Kalshi exchange flag unknown" (None). Not worth warning on every supervisor restart.
        err = str(exc).lower()
        _LOG.debug(
            "exchange_credentials read skipped for user_no=%s DB=%s (%s)",
            user_no,
            _session_db_label(),
            err.split("\n")[0][:200] if err else str(exc)[:200],
        )
        return None


def _session_db_label() -> str:
    """Best-effort label for logs (which database the worker is using)."""
    try:
        host = (os.environ.get("DB_HOST") or os.environ.get("REC_DB_HOST") or "").strip()
        name = (os.environ.get("DB_NAME") or os.environ.get("REC_DB_NAME") or "").strip()
        if host or name:
            return f"{host or '?'}/{name or '?'}"
    except Exception:
        pass
    return "?"


def live_kalshi_trading_allowed_for_user_no(user_no: str) -> bool:
    """
    Live Kalshi is allowed when ``exchange_credentials.kalshi`` is true, or (legacy) when the flag
    is unknown but prod ``kalshi-auth.txt`` exists for that slot. Explicit ``false`` disables live.
    """
    ke = fetch_kalshi_enabled_for_user_no(user_no)
    if ke is False:
        return False
    if ke is True:
        return True
    from backend.core.kalshi_auth_files import read_kalshi_prod_email_for_user_no

    return bool(read_kalshi_prod_email_for_user_no(user_no))


def kalshi_disabled_by_master_users_for_process() -> bool:
    """
    True if this worker's tenant has ``kalshi: false`` in ``master_users`` (no authenticated Kalshi).

    False if no tenant in env (leave global/other processes unchanged) or DB says kalshi true or unknown.
    """
    slot = tenant_user_no_from_worker_env()
    if not slot:
        return False
    enabled = fetch_kalshi_enabled_for_user_no(slot)
    if enabled is None:
        return False
    return not enabled


def block_forever_if_kalshi_authenticated_api_disallowed(
    logger: logging.Logger, service_name: str
) -> None:
    """
    If this tenant must not use signed Kalshi (user keys), log and sleep forever so supervisor
    keeps the process RUNNING instead of treating exit 0 as FATAL.

    Checks ``REC_PAPER_ONLY_USER`` (supervisor) then ``exchange_credentials.kalshi`` (DB).
    """
    if os.environ.get("REC_PAPER_ONLY_USER", "").strip().lower() in ("1", "true", "yes", "on"):
        logger.debug(
            "%s: REC_PAPER_ONLY_USER set; authenticated Kalshi API disabled for this tenant",
            service_name,
        )
        while True:
            time.sleep(3600)
    if kalshi_disabled_by_master_users_for_process():
        logger.debug(
            "%s: system.master_users.exchange_credentials.kalshi is false; "
            "authenticated Kalshi API disabled for this tenant",
            service_name,
        )
        while True:
            time.sleep(3600)
