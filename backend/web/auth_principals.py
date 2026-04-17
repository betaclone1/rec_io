"""Resolve login principals from system.master_users and legacy fallbacks."""

from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, List, Optional

from backend.core.config.database import get_system_postgresql_connection
from backend.util.paths import get_data_dir

from backend.web.auth_passwords import verify_password_against_stored

_USER_DIR_RE = re.compile(r"^user_(\d{4})$")


def fetch_login_principal(user_id: str) -> Optional[Dict[str, Any]]:
    uid = (user_id or "").strip()
    if not uid:
        return None
    conn = get_system_postgresql_connection()
    if not conn:
        return None
    row = None
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT user_no, user_id, password_hash, first_name, last_name, email, phone,
                       account_type, status, registration_date
                FROM system.master_users
                WHERE lower(trim(user_id)) = lower(trim(%s))
                LIMIT 1
                """,
                (uid,),
            )
            row = cur.fetchone()
    except Exception:
        row = None
    finally:
        try:
            conn.close()
        except Exception:
            pass
    if not row:
        return None
    (
        user_no,
        db_uid,
        password_hash,
        first_name,
        last_name,
        email,
        phone,
        account_type,
        status,
        registration_date,
    ) = row
    st = (status or "").strip().lower()
    # Allow password check for active users and self-reg / approval pipeline states
    # (login.html redirects on pending_email_verification / application_pending).
    _LOGIN_STATUSES = frozenset(
        {"active", "pending_email_verification", "pending_admin_approval"}
    )
    if st and st not in _LOGIN_STATUSES:
        return None
    u_no = str(user_no).strip()
    if len(u_no) < 4 and u_no.isdigit():
        u_no = u_no.zfill(4)
    return {
        "user_no": u_no,
        "user_id": db_uid,
        "password_hash": password_hash,
        "first_name": first_name,
        "last_name": last_name,
        "email": email,
        "phone": phone,
        "account_type": account_type,
        "status": status,
        "registration_date": registration_date,
    }


def fetch_master_user_by_slot(user_no: str) -> Optional[Dict[str, Any]]:
    """Registry row for this four-digit slot (``system.master_users``)."""
    slot = str(user_no or "").strip()
    if slot.isdigit() and len(slot) < 4:
        slot = slot.zfill(4)
    if len(slot) != 4 or not slot.isdigit():
        return None
    conn = get_system_postgresql_connection()
    if not conn:
        return None
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT user_no, user_id, first_name, last_name, email, phone, account_type, status, name
                FROM system.master_users
                WHERE LPAD(TRIM(user_no::text), 4, '0') = %s
                LIMIT 1
                """,
                (slot,),
            )
            row = cur.fetchone()
        if not row:
            return None
        u_no, db_uid, fn, ln, email, phone, acct, status, name = row
        u_no_s = str(u_no).strip()
        if u_no_s.isdigit() and len(u_no_s) < 4:
            u_no_s = u_no_s.zfill(4)
        return {
            "user_no": u_no_s,
            "user_id": db_uid,
            "first_name": fn,
            "last_name": ln,
            "email": email,
            "phone": phone,
            "account_type": acct,
            "status": status,
            "name": name,
        }
    except Exception:
        return None
    finally:
        try:
            conn.close()
        except Exception:
            pass


def try_legacy_json_login(username: str, password: str) -> Optional[str]:
    """Dev-only: scan ``data/users/user_NNNN/user_info.json`` for matching plaintext credentials."""
    if os.getenv("REC_ENVIRONMENT") == "production":
        return None
    root = os.path.join(get_data_dir(), "users")
    if not os.path.isdir(root):
        return None
    for folder in sorted(os.listdir(root)):
        if not _USER_DIR_RE.match(folder):
            continue
        slot = _USER_DIR_RE.match(folder).group(1)
        path = os.path.join(root, folder, "user_info.json")
        if not os.path.isfile(path):
            continue
        try:
            with open(path, "r", encoding="utf-8") as f:
                info = json.load(f)
        except Exception:
            continue
        if not isinstance(info, dict):
            continue
        if info.get("user_id") == username and info.get("password") == password:
            return slot
    return None


def master_user_slots_ordered() -> List[str]:
    """Distinct four-digit slots from ``system.master_users`` (active or any)."""
    conn = get_system_postgresql_connection()
    if not conn:
        return []
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT DISTINCT LPAD(TRIM(user_no::text), 4, '0') AS u
                FROM system.master_users
                ORDER BY 1
                """
            )
            rows = cur.fetchall() or []
        out: List[str] = []
        for r in rows:
            if not r or not r[0]:
                continue
            s = str(r[0]).strip().zfill(4)
            if len(s) == 4 and s.isdigit():
                out.append(s)
        return out
    except Exception:
        return []
    finally:
        try:
            conn.close()
        except Exception:
            pass


def password_matches_principal(plain: str, principal: Dict[str, Any]) -> bool:
    return verify_password_against_stored(plain, principal.get("password_hash"))
