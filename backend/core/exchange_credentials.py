"""
``system.master_users.exchange_credentials`` (required column) — which exchanges may use
authenticated API calls.

When ``kalshi`` is false, tenant-scoped workers must not perform signed Kalshi requests,
even if key files exist. Supervisor sets ``REC_PAPER_ONLY_USER`` from the same rule plus on-disk keys.
"""

from __future__ import annotations

import json
import os
import time
import re
from typing import Any, Dict, List, Optional, Sequence

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


def fetch_kalshi_enabled_map_for_user_nos(user_nos: Sequence[str]) -> Dict[str, Optional[bool]]:
    """
    One system DB round-trip for several slots (e.g. supervisor config generation).

    Keys are four-digit ``user_no`` strings. Value ``None`` means no row or NULL ``exchange_credentials``.
    """
    slots: List[str] = []
    for raw in user_nos:
        if not raw:
            continue
        u = str(raw).strip().zfill(4) if str(raw).strip().isdigit() else raw.strip()
        if _USER_NO_ENV_RE.match(u):
            slots.append(u)
    if not slots:
        return {}
    uniq = sorted(set(slots))
    from backend.core.config.database import get_system_postgresql_connection

    conn = get_system_postgresql_connection()
    if not conn:
        return {s: None for s in uniq}
    out: Dict[str, Optional[bool]] = {s: None for s in uniq}
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT LPAD(TRIM(user_no::text), 4, '0') AS slot, exchange_credentials
                FROM system.master_users
                WHERE LPAD(TRIM(user_no::text), 4, '0') IN %s
                """,
                (tuple(uniq),),
            )
            for slot, cred in cur.fetchall() or []:
                sk = str(slot).zfill(4) if slot is not None else ""
                if sk in out:
                    if cred is None:
                        out[sk] = None
                    else:
                        out[sk] = bool(normalize_exchange_credentials(cred)["kalshi"])
        return out
    finally:
        try:
            conn.close()
        except Exception:
            pass


def fetch_kalshi_enabled_for_user_no(user_no: str) -> Optional[bool]:
    """
    Read ``exchange_credentials->kalshi`` for ``user_no``.

    Returns ``None`` if there is no ``master_users`` row for the slot or ``exchange_credentials`` is NULL.
    Connection or schema errors propagate (no swallowing of PostgreSQL errors).
    """
    if not user_no or not _USER_NO_ENV_RE.match(user_no):
        return None
    m = fetch_kalshi_enabled_map_for_user_nos([user_no])
    return m.get(user_no)


def live_kalshi_trading_allowed_for_user_no(user_no: str) -> bool:
    """
    Live Kalshi is allowed when ``exchange_credentials.kalshi`` is true, or when the row is missing /
    NULL and prod ``kalshi-auth.txt`` exists for that slot (legacy file-only). Explicit ``false`` disables live.
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
