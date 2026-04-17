"""Login/session and user profile routes for the read_api web data plane."""

from __future__ import annotations

import asyncio
import logging
import os
import secrets
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from psycopg2 import sql

from backend.core.config.database import get_system_postgresql_connection
from backend.core.tenant_context import resolved_tenant_user_no_for_app
from backend.web.auth_passwords import hash_password_bcrypt, verify_password_against_stored
from backend.web.auth_principals import (
    fetch_login_principal,
    fetch_master_user_by_slot,
    password_matches_principal,
    try_legacy_json_login,
)
from backend.util.registration_email import send_account_activated_email
from backend.core.master_user_supervisor_resync import (
    master_user_trading_active,
    resync_supervisor_after_master_users_db_change,
)
from backend.web.session_store import (
    delete_device_token,
    delete_token_everywhere,
    find_valid_token,
    load_device_tokens,
    save_device_tokens,
    save_token_for_user,
)

logger = logging.getLogger(__name__)

# Throttle for POST /api/user/activity (server-side; client also pings at this interval).
_UI_LAST_LOGIN_THROTTLE_MINUTES = 5

auth_router = APIRouter()
user_router = APIRouter()


def _normalize_master_user_no_slot(user_no: str) -> Optional[str]:
    slot = str(user_no or "").strip()
    if slot.isdigit() and len(slot) < 4:
        slot = slot.zfill(4)
    if len(slot) != 4 or not slot.isdigit():
        return None
    return slot


def _touch_master_users_last_login(user_no: str, *, throttle_minutes: Optional[int] = None) -> None:
    """
    Update ``system.master_users.last_login`` for the given four-digit slot.
    When ``throttle_minutes`` is set, skip the write if ``last_login`` is newer than that window.
    """
    slot = _normalize_master_user_no_slot(user_no)
    if not slot:
        return
    conn = get_system_postgresql_connection()
    if not conn:
        return
    try:
        with conn.cursor() as c:
            if throttle_minutes is None:
                c.execute(
                    """
                    UPDATE system.master_users
                    SET last_login = CURRENT_TIMESTAMP
                    WHERE LPAD(TRIM(user_no::text), 4, '0') = %s
                    """,
                    (slot,),
                )
            else:
                c.execute(
                    """
                    UPDATE system.master_users
                    SET last_login = CURRENT_TIMESTAMP
                    WHERE LPAD(TRIM(user_no::text), 4, '0') = %s
                      AND (
                        last_login IS NULL
                        OR last_login < NOW() - (%s * INTERVAL '1 minute')
                      )
                    """,
                    (slot, int(throttle_minutes)),
                )
        conn.commit()
    except Exception as e:
        logger.debug("[AUTH] last_login touch skipped: %s", e)
        try:
            conn.rollback()
        except Exception:
            pass
    finally:
        try:
            conn.close()
        except Exception:
            pass


def _legal_display_name(first: Any, last: Any) -> str:
    a = str(first).strip() if first is not None else ""
    b = str(last).strip() if last is not None else ""
    parts = [p for p in (a, b) if p]
    return " ".join(parts)


def _display_name_from_master(m: Dict[str, Any]) -> str:
    """Registry fields only: first+last, else ``name`` column; never ``user_id``."""
    nm = _legal_display_name(m.get("first_name"), m.get("last_name"))
    if nm:
        return nm
    full = m.get("name")
    return str(full).strip() if full is not None else ""


def public_profile_for_slot(user_no: str) -> tuple[str, Optional[Dict[str, Any]]]:
    """
    Single source: ``system.master_users`` for this four-digit slot.
    Returns (status, dict). status is 'ok', 'no_db', or 'not_found'.
    """
    conn = get_system_postgresql_connection()
    if not conn:
        return "no_db", None
    try:
        conn.close()
    except Exception:
        pass

    master = fetch_master_user_by_slot(user_no)
    if not master:
        return "not_found", None
    st = (master.get("status") or "").strip().lower()
    if st and st != "active":
        return "not_found", None

    return "ok", {
        "user_id": master.get("user_id"),
        "name": _display_name_from_master(master),
        "email": master.get("email"),
        "phone": master.get("phone"),
        "account_type": master.get("account_type"),
    }


@auth_router.post("/login")
async def login(request: Request):
    try:
        data = await request.json()
        username = (data.get("username") or "").strip()
        password = data.get("password") or ""
        remember_device = bool(data.get("rememberDevice", False))
    except Exception:
        return JSONResponse({"success": False, "error": "Invalid request"}, status_code=400)

    user_no: str | None = None
    principal = fetch_login_principal(username)
    matched_principal: Dict[str, Any] | None = None
    if principal and password_matches_principal(password, principal):
        user_no = principal["user_no"]
        matched_principal = principal
    if not user_no:
        user_no = try_legacy_json_login(username, password)
    if not user_no:
        logger.debug("[AUTH] Failed login for username=%s", username)
        return {"success": False, "error": "Invalid username or password"}

    if matched_principal:
        st = (matched_principal.get("status") or "").strip().lower()
        if st == "pending_email_verification":
            em = (matched_principal.get("email") or "").strip()
            return {
                "success": True,
                "pending_email_verification": True,
                "user_id": matched_principal.get("user_id"),
                "email": em or None,
            }
        if st == "pending_admin_approval":
            rd = matched_principal.get("registration_date")
            submitted_on = ""
            if rd is not None:
                if hasattr(rd, "strftime"):
                    submitted_on = rd.strftime("%Y-%m-%d %H:%M UTC")
                else:
                    submitted_on = str(rd).strip()
            fn = str(matched_principal.get("first_name") or "").strip()
            em = str(matched_principal.get("email") or "").strip()
            return {
                "success": True,
                "application_pending": True,
                "first_name": fn[:200],
                "email": em[:255],
                "submitted_on": submitted_on or datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
            }

    pst, profile = public_profile_for_slot(user_no)
    display_name = ""
    profile_user_id = None
    if pst == "ok" and profile:
        display_name = profile.get("name") or ""
        profile_user_id = profile.get("user_id")

    token = secrets.token_urlsafe(32)
    device_id = f"device_{secrets.token_hex(8)}"
    now_u = datetime.now(timezone.utc)
    expires = (
        (now_u + timedelta(days=30)) if remember_device else (now_u + timedelta(hours=24))
    )
    save_token_for_user(
        user_no,
        token,
        {
            "username": username,
            "created": now_u.isoformat(),
            "expires": expires.isoformat(),
        },
    )
    if remember_device:
        dt = load_device_tokens(user_no)
        dt[device_id] = {
            "username": username,
            "token": token,
            "created": now_u.isoformat(),
            "expires": (now_u + timedelta(days=365)).isoformat(),
        }
        save_device_tokens(user_no, dt)

    _touch_master_users_last_login(user_no, throttle_minutes=None)

    logger.debug("[AUTH] User %s logged in as tenant %s", username, user_no)
    return {
        "success": True,
        "token": token,
        "deviceId": device_id,
        "username": username,
        "name": display_name,
        "user_id": profile_user_id,
        "userNo": user_no,
    }


@auth_router.post("/verify")
async def verify(request: Request):
    try:
        data = await request.json()
        token = (data.get("token") or "").strip()
    except Exception:
        return {"authenticated": False}

    if token.startswith("local_dev_") and os.getenv("REC_ENVIRONMENT") != "production":
        return {
            "authenticated": True,
            "username": "local_dev",
            "name": "",
            "user_id": None,
            "userNo": None,
        }

    hit = find_valid_token(token)
    if not hit:
        return {"authenticated": False}
    user_no, rec = hit
    uname = (rec.get("username") or "").strip()

    pst, profile = public_profile_for_slot(user_no)
    display_name = ""
    uid_out = None
    if pst == "ok" and profile:
        display_name = profile.get("name") or ""
        uid_out = profile.get("user_id")

    return {
        "authenticated": True,
        "username": uname,
        "name": display_name,
        "user_id": uid_out,
        "userNo": user_no,
    }


@auth_router.post("/logout")
async def logout(request: Request):
    try:
        data = await request.json()
        token = (data.get("token") or "").strip()
        device_id = (data.get("deviceId") or "").strip()
    except Exception:
        return {"success": False, "error": "Invalid request"}

    user_no_for_device: str | None = None
    hit = find_valid_token(token)
    if hit:
        user_no_for_device = hit[0]
    delete_token_everywhere(token)
    if device_id and user_no_for_device:
        delete_device_token(user_no_for_device, device_id)
    return {"success": True}


@user_router.post("/activity")
async def record_ui_activity():
    """
    Record that the session user had the UI open. Updates ``last_login`` at most once per
    :data:`_UI_LAST_LOGIN_THROTTLE_MINUTES` (server-enforced); client should ping at the same cadence.
    """
    u = resolved_tenant_user_no_for_app()
    slot = _normalize_master_user_no_slot(u)
    if not slot:
        return JSONResponse(status_code=401, content={"error": "Not authenticated"})
    _touch_master_users_last_login(slot, throttle_minutes=_UI_LAST_LOGIN_THROTTLE_MINUTES)
    return {"ok": True}


@user_router.get("/info")
async def user_info():
    u = resolved_tenant_user_no_for_app()
    pst, profile = public_profile_for_slot(u)
    if pst == "no_db":
        return JSONResponse(
            status_code=503,
            content={"error": "Database unavailable"},
        )
    if pst == "not_found" or not profile:
        return JSONResponse(
            status_code=404,
            content={"error": "User not found", "user_no": u},
        )
    return {
        "user_id": profile["user_id"],
        "name": profile["name"],
        "email": profile["email"],
        "phone": profile["phone"],
        "account_type": profile["account_type"],
    }


def _session_is_master_admin(user_no: str) -> bool:
    pst, profile = public_profile_for_slot(user_no)
    if pst != "ok" or not profile:
        return False
    acct = (profile.get("account_type") or "").strip().lower()
    return acct == "master_admin"


def _json_safe_cell(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return value


_ADMIN_MASTER_USERS_SECRET_COLUMNS = frozenset(
    {"password_hash", "email_verification_code_hash"}
)

_ADMIN_MASTER_ACCOUNT_TYPES = frozenset(
    {"master_admin", "admin", "user_basic", "user_premium"}
)
_ADMIN_MASTER_STATUSES = frozenset(
    {
        "pending_email_verification",
        "pending_admin_approval",
        "active",
        "inactive",
    }
)


def _count_active_monitors_for_slot(cur: Any, user_no: Any) -> int:
    """Rows in ``users_<slot>.monitor_list_<slot>`` with ``status = 'active'``."""
    slot = _normalize_master_user_no_slot(str(user_no) if user_no is not None else "")
    if not slot:
        return 0
    schema = f"users_{slot}"
    table = f"monitor_list_{slot}"
    try:
        cur.execute(
            sql.SQL("SELECT COUNT(*) FROM {}.{} WHERE status = {}").format(
                sql.Identifier(schema),
                sql.Identifier(table),
                sql.Literal("active"),
            )
        )
        row = cur.fetchone()
        if not row or row[0] is None:
            return 0
        return int(row[0])
    except Exception:
        return 0


@user_router.get("/admin/master_users")
async def admin_master_users_rows():
    """All ``system.master_users`` rows (no password hashes). ``master_admin`` only."""
    u = resolved_tenant_user_no_for_app()
    if not _session_is_master_admin(u):
        return JSONResponse(status_code=403, content={"error": "Forbidden"})

    conn = get_system_postgresql_connection()
    if not conn:
        return JSONResponse(status_code=503, content={"error": "Database unavailable"})
    try:
        with conn.cursor() as cur:
            # SELECT * returns all current columns (legacy-only columns removed per migration 20260414_2100).
            cur.execute(
                """
                SELECT * FROM system.master_users
                ORDER BY
                    LPAD(TRIM(COALESCE(user_no::text, '')), 4, '0') NULLS LAST,
                    user_id
                """
            )
            colnames = [d[0] for d in (cur.description or [])]
            raw_rows = cur.fetchall()
        out = []
        for row in raw_rows:
            item: Dict[str, Any] = {}
            for i, key in enumerate(colnames):
                if key in _ADMIN_MASTER_USERS_SECRET_COLUMNS:
                    continue
                val = row[i]
                if key == "exchange_credentials":
                    item[key] = val
                else:
                    item[key] = _json_safe_cell(val)
            out.append(item)
        with conn.cursor() as cur2:
            for item in out:
                item["monitors"] = _count_active_monitors_for_slot(cur2, item.get("user_no"))
        return {"rows": out}
    except Exception as e:
        logger.warning("[AUTH] admin/master_users: %s", e)
        return JSONResponse(status_code=500, content={"error": "Query failed"})
    finally:
        try:
            conn.close()
        except Exception:
            pass


@user_router.patch("/admin/master_users")
async def admin_patch_master_user(request: Request):
    """Update ``account_type`` and/or ``status`` for one row. ``master_admin`` only."""
    u = resolved_tenant_user_no_for_app()
    if not _session_is_master_admin(u):
        return JSONResponse(status_code=403, content={"error": "Forbidden"})

    try:
        data = await request.json()
    except Exception:
        return JSONResponse(status_code=400, content={"error": "Invalid JSON"})

    target_raw = str(data.get("user_no") or "").strip()
    slot = _normalize_master_user_no_slot(target_raw)
    if not slot:
        return JSONResponse(status_code=400, content={"error": "user_no required"})

    acct_raw = data.get("account_type")
    st_raw = data.get("status")
    acct: Optional[str] = None
    st: Optional[str] = None
    if acct_raw is not None:
        acct = str(acct_raw).strip()
        if acct not in _ADMIN_MASTER_ACCOUNT_TYPES:
            return JSONResponse(
                status_code=400,
                content={"error": f"Invalid account_type: {acct!r}"},
            )
    if st_raw is not None:
        st = str(st_raw).strip()
        if st not in _ADMIN_MASTER_STATUSES:
            return JSONResponse(
                status_code=400,
                content={"error": f"Invalid status: {st!r}"},
            )
    if acct is None and st is None:
        return JSONResponse(
            status_code=400,
            content={"error": "Provide account_type and/or status"},
        )

    conn = get_system_postgresql_connection()
    if not conn:
        return JSONResponse(status_code=503, content={"error": "Database unavailable"})
    try:
        old_status: Optional[Any] = None
        activation_recipient: Optional[str] = None
        activation_first_name: str = ""
        if st is not None:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT status,
                           NULLIF(TRIM(COALESCE(email, '')), ''),
                           TRIM(COALESCE(first_name, ''))
                    FROM system.master_users
                    WHERE LPAD(TRIM(user_no::text), 4, '0') = %s
                    LIMIT 1
                    """,
                    (slot,),
                )
                row = cur.fetchone()
            if not row:
                return JSONResponse(status_code=404, content={"error": "User not found"})
            old_status = row[0]
            activation_recipient = row[1] if len(row) > 1 else None
            activation_first_name = (row[2] or "") if len(row) > 2 else ""

        sets: List[str] = []
        params: List[Any] = []
        if acct is not None:
            sets.append("account_type = %s")
            params.append(acct)
        if st is not None:
            sets.append("status = %s")
            params.append(st)
        sets.append("last_updated = CURRENT_TIMESTAMP")
        params.append(slot)
        sql = (
            "UPDATE system.master_users SET "
            + ", ".join(sets)
            + " WHERE LPAD(TRIM(user_no::text), 4, '0') = %s"
        )
        with conn.cursor() as cur:
            cur.execute(sql, tuple(params))
            n = cur.rowcount
        conn.commit()
        if not n:
            return JSONResponse(status_code=404, content={"error": "User not found"})

        resync_note: Optional[str] = None
        if st is not None:
            before = master_user_trading_active(old_status)
            after = master_user_trading_active(st)
            if before != after:
                ok, msg = await asyncio.to_thread(
                    resync_supervisor_after_master_users_db_change,
                    logger=logger,
                )
                resync_note = "ok" if ok else f"failed: {msg}"

        activation_email_note: Optional[str] = None
        if (
            st == "active"
            and str(old_status or "").strip().lower() == "pending_admin_approval"
            and activation_recipient
        ):
            try:
                await asyncio.to_thread(
                    send_account_activated_email,
                    activation_recipient,
                    first_name=activation_first_name,
                )
                activation_email_note = "sent"
            except Exception as exc:
                logger.warning("[AUTH] admin activation email to %s: %s", activation_recipient, exc)
                activation_email_note = f"failed: {exc}"

        out: Dict[str, Any] = {"ok": True, "user_no": slot}
        if resync_note is not None:
            out["supervisor_resync"] = resync_note
        if activation_email_note is not None:
            out["activation_email"] = activation_email_note
        return out
    except Exception as e:
        logger.warning("[AUTH] admin/master_users PATCH: %s", e)
        try:
            conn.rollback()
        except Exception:
            pass
        return JSONResponse(status_code=500, content={"error": "Update failed"})
    finally:
        try:
            conn.close()
        except Exception:
            pass


@user_router.post("/change-password")
async def change_password(request: Request):
    try:
        data = await request.json()
        current_password = data.get("currentPassword", "")
        new_password = data.get("newPassword", "")
    except Exception:
        return {"success": False, "error": "Invalid request"}
    u = resolved_tenant_user_no_for_app()
    conn = get_system_postgresql_connection()
    if not conn:
        return {"success": False, "error": "Database unavailable"}
    try:
        with conn.cursor() as c:
            c.execute(
                """
                SELECT password_hash FROM system.master_users
                WHERE LPAD(TRIM(user_no::text), 4, '0') = %s
                LIMIT 1
                """,
                (u,),
            )
            row = c.fetchone()
        if not row or not row[0]:
            return {"success": False, "error": "User not found"}
        ph = row[0]
        if not verify_password_against_stored(current_password, ph):
            return {"success": False, "error": "Current password is incorrect"}
        new_hash = hash_password_bcrypt(new_password)
        with conn.cursor() as c:
            c.execute(
                """
                UPDATE system.master_users
                SET password_hash = %s
                WHERE LPAD(TRIM(user_no::text), 4, '0') = %s
                """,
                (new_hash, u),
            )
            conn.commit()
        return {"success": True, "message": "Password updated successfully"}
    except Exception as e:
        logger.warning("[AUTH] change-password: %s", e)
        return {"success": False, "error": str(e)}
    finally:
        try:
            conn.close()
        except Exception:
            pass
