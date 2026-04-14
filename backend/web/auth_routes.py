"""Login/session and user profile routes for the read_api web data plane."""

from __future__ import annotations

import logging
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from backend.core.config.database import get_system_postgresql_connection
from backend.core.tenant_context import resolved_tenant_user_no_for_app
from backend.web.auth_passwords import hash_password_bcrypt, verify_password_against_stored
from backend.web.auth_principals import (
    fetch_login_principal,
    fetch_master_user_by_slot,
    password_matches_principal,
    try_legacy_json_login,
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

auth_router = APIRouter()
user_router = APIRouter()


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
    if principal and password_matches_principal(password, principal):
        user_no = principal["user_no"]
    if not user_no:
        user_no = try_legacy_json_login(username, password)
    if not user_no:
        logger.debug("[AUTH] Failed login for username=%s", username)
        return {"success": False, "error": "Invalid username or password"}

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
