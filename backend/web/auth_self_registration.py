"""Self-service master user registration (POST only; HTML is served from main_app)."""

from __future__ import annotations

import asyncio
import logging
import re
import secrets
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

from fastapi import APIRouter, Request

from backend.core.config.database import get_system_postgresql_connection
from backend.util.registration_email import (
    registration_verification_email_configured,
    send_master_user_verification_email,
    send_new_user_application_submitted_alert,
)
from backend.web.auth_passwords import hash_password_bcrypt, verify_password_against_stored

logger = logging.getLogger(__name__)

self_reg_router = APIRouter()

_REGISTER_EMAIL = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
_PASSWORD_SPECIAL = re.compile(r"[!@#$%^&*()+\-=[\]{};:'\",.<>/?\\|`~]")


def _client_ip(request: Request) -> str:
    xff = (request.headers.get("x-forwarded-for") or "").split(",")[0].strip()
    if xff:
        return xff
    if request.client:
        return request.client.host or ""
    return ""


def _phone_digits(raw: str) -> str:
    return "".join(c for c in (raw or "") if c.isdigit())[:10]


def _validate_password(pw: str) -> str:
    if not pw:
        return "Required."
    if pw.strip() != pw or " " in pw:
        return "Must not contain spaces."
    if len(pw) < 7:
        return "Must be at least 7 characters."
    if not re.search(r"[a-zA-Z]", pw):
        return "Must include at least one letter."
    if not re.search(r"\d", pw):
        return "Must include at least one number."
    if not _PASSWORD_SPECIAL.search(pw):
        return "Must include at least one special character (!@#$%^&* etc.)."
    return ""


def _validate_register_fields(data: Dict[str, Any]) -> Tuple[Dict[str, str], Optional[str]]:
    """Returns (field_errors, None) or ({}, payload_dict_as_side_effect via return only errors)."""
    fe: Dict[str, str] = {}
    user_id = str(data.get("user_id") or "").strip()
    pw = data.get("password") or ""
    pw2 = data.get("password_confirm") or ""
    first = str(data.get("first_name") or "").strip()
    last = str(data.get("last_name") or "").strip()
    email = str(data.get("email") or "").strip()
    phone_raw = str(data.get("phone") or "")

    if not user_id:
        fe["user_id"] = "Required."
    elif len(user_id) > 50:
        fe["user_id"] = "Must be at most 50 characters."
    elif re.search(r"\s", user_id):
        fe["user_id"] = "Must not contain spaces."

    if not first:
        fe["first_name"] = "Required."
    if not last:
        fe["last_name"] = "Required."
    if first and last and len(f"{first} {last}") > 255:
        fe["last_name"] = "Combined first and last name must be at most 255 characters."

    if not email:
        fe["email"] = "Required."
    elif len(email) > 255:
        fe["email"] = "Must be at most 255 characters."
    elif not _REGISTER_EMAIL.match(email):
        fe["email"] = "Enter a valid email address."

    pd = _phone_digits(phone_raw)
    if len(pd) == 0:
        fe["phone"] = "Required."
    elif len(pd) != 10:
        fe["phone"] = "Enter a 10-digit US phone number."

    pe = _validate_password(str(pw))
    if pe:
        fe["password"] = pe
    if str(pw) != str(pw2):
        fe["password_confirm"] = "Must match password."

    return fe


def _next_user_no(cur) -> str:
    cur.execute(
        """
        SELECT COALESCE(MAX(CAST(LPAD(TRIM(user_no::text), 4, '0') AS INTEGER)), 0)
        FROM system.master_users
        """
    )
    row = cur.fetchone()
    n = int(row[0] or 0) + 1
    if n > 9999:
        raise RuntimeError("no free user_no slots")
    return f"{n:04d}"


@self_reg_router.post("/register")
async def self_register(request: Request):
    try:
        data = await request.json()
    except Exception:
        return {"success": False, "error": "Invalid request"}

    fe = _validate_register_fields(data)
    if fe:
        return {"success": False, "error": "Please correct the fields below.", "field_errors": fe}

    if not registration_verification_email_configured():
        return {
            "success": False,
            "error": "Email verification is not configured on this server (SMTP).",
        }

    user_id = str(data.get("user_id") or "").strip()
    pw = str(data.get("password") or "")
    first = str(data.get("first_name") or "").strip()
    last = str(data.get("last_name") or "").strip()
    email = str(data.get("email") or "").strip()
    phone_display = str(data.get("phone") or "").strip()
    name = (f"{first} {last}".strip() or user_id)[:255]
    pw_hash = hash_password_bcrypt(pw)
    code = f"{secrets.randbelow(900000) + 100000:06d}"
    code_hash = hash_password_bcrypt(code)
    ex_json = '{"kalshi": false, "polymarket": false}'

    conn = get_system_postgresql_connection()
    if not conn:
        return {"success": False, "error": "Database unavailable"}
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT 1 FROM system.master_users
                WHERE LOWER(TRIM(user_id)) = LOWER(TRIM(%s))
                LIMIT 1
                """,
                (user_id,),
            )
            if cur.fetchone():
                return {
                    "success": False,
                    "error": "That User ID is already taken.",
                    "field_errors": {"user_id": "That User ID is already taken."},
                }
            cur.execute(
                """
                SELECT 1 FROM system.master_users
                WHERE LOWER(TRIM(email)) = LOWER(TRIM(%s))
                LIMIT 1
                """,
                (email,),
            )
            if cur.fetchone():
                return {
                    "success": False,
                    "error": "An account with this email already exists.",
                    "sign_in_prompt": True,
                }

            slot = _next_user_no(cur)
            cur.execute(
                """
                INSERT INTO system.master_users (
                    user_no, user_id, name, first_name, last_name, email, phone,
                    password_hash, status, account_type, exchange_credentials,
                    email_verification_code_hash, email_verification_sent_at
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s,
                    %s, 'pending_email_verification', 'user_basic', %s::jsonb,
                    %s, NOW()
                )
                """,
                (
                    slot,
                    user_id,
                    name,
                    first or None,
                    last or None,
                    email,
                    phone_display[:50],
                    pw_hash,
                    ex_json,
                    code_hash,
                ),
            )
        conn.commit()
    except Exception as exc:
        logger.warning("[AUTH] register: %s", exc, exc_info=True)
        try:
            conn.rollback()
        except Exception:
            pass
        err_s = str(exc).lower()
        if "value too long for type character varying" in err_s:
            return {
                "success": False,
                "error": "Registration could not complete: a database column is too narrow for new accounts (often system.master_users.status). The operator should run pending migrations (e.g. 20260420_1000_system_master_users_registration_user_no) or run init_database once; see server log [AUTH] register for the exact error.",
            }
        return {"success": False, "error": "Registration failed."}
    finally:
        try:
            conn.close()
        except Exception:
            pass

    try:
        await asyncio.to_thread(
            send_master_user_verification_email,
            email,
            code=code,
            user_id=user_id,
            full_name=f"{first} {last}".strip(),
        )
    except Exception as exc:
        logger.warning("[AUTH] register verification email: %s", exc, exc_info=True)
        return {
            "success": False,
            "error": "Account was created but verification email could not be sent. Contact support.",
        }

    return {"success": True, "user_id": user_id}


@self_reg_router.post("/register/verify-email")
async def self_register_verify_email(request: Request):
    try:
        data = await request.json()
    except Exception:
        return {"success": False, "error": "Invalid request"}

    user_id = str(data.get("user_id") or "").strip()
    code = str(data.get("code") or "").strip()
    if not user_id or len(code) != 6 or not code.isdigit():
        return {
            "success": False,
            "error": "Invalid request",
            "field_errors": {"code": "Enter the 6-digit code from your email."},
        }

    conn = get_system_postgresql_connection()
    if not conn:
        return {"success": False, "error": "Database unavailable"}
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT user_no, status, email_verification_code_hash, email_verification_sent_at,
                       email, first_name, last_name, name, phone, account_type, registration_date
                FROM system.master_users
                WHERE LOWER(TRIM(user_id)) = LOWER(TRIM(%s))
                LIMIT 1
                """,
                (user_id,),
            )
            row = cur.fetchone()
        if not row:
            return {"success": False, "error": "User not found."}

        (
            user_no,
            status,
            code_hash,
            sent_at,
            em,
            fn,
            ln,
            nm,
            phone,
            acct,
            reg_date,
        ) = row
        st = (status or "").strip().lower()
        if st == "active":
            return {"success": True, "already_active": True}

        if st != "pending_email_verification":
            if st == "pending_admin_approval":
                return {
                    "success": True,
                    "application_pending": True,
                    "first_name": (fn or "")[:200],
                    "email": (em or "")[:255],
                    "submitted_on": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
                }
            return {"success": False, "error": "This account is not awaiting email verification."}

        if not code_hash or not sent_at:
            return {"success": False, "error": "No verification code is pending for this account."}

        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT 1 FROM system.master_users
                WHERE LOWER(TRIM(user_id)) = LOWER(TRIM(%s))
                  AND status = 'pending_email_verification'
                  AND email_verification_sent_at IS NOT NULL
                  AND email_verification_sent_at > NOW() - INTERVAL '24 hours'
                LIMIT 1
                """,
                (user_id,),
            )
            if not cur.fetchone():
                return {
                    "success": False,
                    "error": "This code has expired. Use Re-send to get a new code.",
                }

        if not verify_password_against_stored(code, code_hash):
            return {
                "success": False,
                "error": "Invalid code.",
                "field_errors": {"code": "Invalid code."},
            }

        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE system.master_users
                SET status = 'pending_admin_approval',
                    email_verification_code_hash = NULL,
                    email_verification_sent_at = NULL,
                    last_updated = CURRENT_TIMESTAMP
                WHERE LOWER(TRIM(user_id)) = LOWER(TRIM(%s))
                  AND status = 'pending_email_verification'
                """,
                (user_id,),
            )
        conn.commit()
    except Exception as exc:
        logger.warning("[AUTH] verify-email: %s", exc)
        try:
            conn.rollback()
        except Exception:
            pass
        return {"success": False, "error": "Verification failed."}
    finally:
        try:
            conn.close()
        except Exception:
            pass

    submitted = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    try:
        await asyncio.to_thread(
            send_new_user_application_submitted_alert,
            user_no=str(user_no).strip(),
            user_id=user_id,
            name=(nm or "")[:255],
            first_name=(fn or "")[:100],
            last_name=(ln or "")[:100],
            email=(em or "")[:255],
            phone=(phone or "")[:50],
            account_type=(acct or "user_basic")[:32],
            registration_date=reg_date,
            server_ip=_client_ip(request),
        )
    except Exception as exc:
        logger.warning("[AUTH] verify-email admin notify: %s", exc)

    return {
        "success": True,
        "application_pending": True,
        "first_name": (fn or "")[:200],
        "email": (em or "")[:255],
        "submitted_on": submitted,
    }


@self_reg_router.post("/register/resend-verification")
async def self_register_resend(request: Request):
    try:
        data = await request.json()
    except Exception:
        return {"success": False, "error": "Invalid request"}

    user_id = str(data.get("user_id") or "").strip()
    if not user_id:
        return {"success": False, "error": "User ID required."}

    if not registration_verification_email_configured():
        return {"success": False, "error": "Email is not configured on this server."}

    conn = get_system_postgresql_connection()
    if not conn:
        return {"success": False, "error": "Database unavailable"}
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT status, email, first_name, last_name, email_verification_sent_at
                FROM system.master_users
                WHERE LOWER(TRIM(user_id)) = LOWER(TRIM(%s))
                LIMIT 1
                """,
                (user_id,),
            )
            row = cur.fetchone()
        if not row:
            return {"success": False, "error": "User not found."}
        status, email, fn, ln, sent_at = row
        st = (status or "").strip().lower()
        if st == "active":
            return {"success": False, "already_active": True}
        if st == "pending_admin_approval":
            return {
                "success": True,
                "application_pending": True,
                "first_name": (fn or "")[:200],
                "email": (email or "")[:255],
                "submitted_on": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
            }
        if st != "pending_email_verification":
            return {"success": False, "error": "This account is not awaiting email verification."}

        code = f"{secrets.randbelow(900000) + 100000:06d}"
        code_hash = hash_password_bcrypt(code)
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE system.master_users
                SET email_verification_code_hash = %s,
                    email_verification_sent_at = NOW(),
                    last_updated = CURRENT_TIMESTAMP
                WHERE LOWER(TRIM(user_id)) = LOWER(TRIM(%s))
                  AND status = 'pending_email_verification'
                  AND (
                    email_verification_sent_at IS NULL
                    OR email_verification_sent_at <= NOW() - INTERVAL '60 seconds'
                  )
                RETURNING email
                """,
                (code_hash, user_id),
            )
            ret = cur.fetchone()
        if not ret:
            try:
                conn.rollback()
            except Exception:
                pass
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT email_verification_sent_at > NOW() - INTERVAL '60 seconds'
                    FROM system.master_users
                    WHERE LOWER(TRIM(user_id)) = LOWER(TRIM(%s))
                      AND status = 'pending_email_verification'
                    LIMIT 1
                    """,
                    (user_id,),
                )
                hot = cur.fetchone()
            if hot and hot[0]:
                return {
                    "success": False,
                    "error": "Please wait a minute before requesting another code.",
                }
            return {"success": False, "error": "Could not update verification code."}
        conn.commit()
    except Exception as exc:
        logger.warning("[AUTH] resend-verification: %s", exc)
        try:
            conn.rollback()
        except Exception:
            pass
        return {"success": False, "error": "Could not resend."}
    finally:
        try:
            conn.close()
        except Exception:
            pass

    try:
        await asyncio.to_thread(
            send_master_user_verification_email,
            (email or "").strip(),
            code=code,
            user_id=user_id,
            full_name=f"{(fn or '').strip()} {(ln or '').strip()}".strip(),
        )
    except Exception as exc:
        logger.warning("[AUTH] resend verification email: %s", exc)
        return {"success": False, "error": "Could not send email."}

    return {"success": True}
