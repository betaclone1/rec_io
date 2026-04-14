"""
Send transactional email for master_users self-registration (verification code).

Uses Gmail SMTP with an app password. Configure:
  REC_ALERTS_SMTP_HOST     (default smtp.gmail.com)
  REC_ALERTS_SMTP_PORT     (default 587)
  REC_ALERTS_SMTP_USER     (default rec.io.alerts@gmail.com)
  REC_ALERTS_SMTP_PASSWORD (required to send unless file below; Google app password)
  REC_ALERTS_SMTP_PASSWORD_FILE (optional; first line = password, avoids env embedding)
  REC_ALERTS_SMTP_FROM     (optional From header; defaults to REC_ALERTS_SMTP_USER)
  REC_ALERTS_ADMIN_NOTIFY_EMAIL (optional; inbox for new-user application alerts after
    email verification; default rec.io.alerts@gmail.com)
  REC_PUBLIC_BASE_URL (optional; overrides default https://rec-io.com for verification links
    in email, e.g. http://localhost:3000 for local testing)

If none of the above are set, a repo-local file is tried (gitignored):
  backend/data/secrets/rec_alerts_smtp_password.txt  — single line, Gmail app password

Legacy: system_monitor / cascading_failure_detector used scripts/user_notifications.py
(Gmail SMTP to SMS); that module was removed and call sites are commented DISABLED.
"""

from __future__ import annotations

import html
import os
import smtplib
import ssl
from datetime import date, datetime
from email.message import EmailMessage
from urllib.parse import quote

# Verification links in outbound email always use this origin unless REC_PUBLIC_BASE_URL is set.
_VERIFICATION_EMAIL_SITE_ORIGIN_DEFAULT = "https://rec-io.com"


def _normalize_smtp_secret(raw: str) -> str:
    """
    Trim file/env noise and strip interior whitespace. Gmail app passwords are 16
    characters; Google often displays them with spaces, which must be removed for SMTP.
    """
    if not raw:
        return ""
    s = raw.strip()
    if s.startswith("\ufeff"):
        s = s.lstrip("\ufeff").strip()
    first = (s.splitlines()[0] or "").strip()
    return "".join(c for c in first if not c.isspace())


def _default_smtp_password_file_path() -> str:
    try:
        from backend.util.paths import get_project_root

        return os.path.join(
            get_project_root(),
            "backend",
            "data",
            "secrets",
            "rec_alerts_smtp_password.txt",
        )
    except Exception:
        return ""


def _smtp_password() -> str:
    direct = _normalize_smtp_secret(os.getenv("REC_ALERTS_SMTP_PASSWORD") or "")
    if direct:
        return direct
    path = (os.getenv("REC_ALERTS_SMTP_PASSWORD_FILE") or "").strip()
    if path:
        try:
            with open(path, "r", encoding="utf-8") as f:
                got = _normalize_smtp_secret(f.read() or "")
                if got:
                    return got
        except OSError:
            pass
    default_path = _default_smtp_password_file_path()
    if default_path and os.path.isfile(default_path):
        try:
            with open(default_path, "r", encoding="utf-8") as f:
                return _normalize_smtp_secret(f.read() or "")
        except OSError:
            pass
    return ""


def _smtp_config():
    host = (os.getenv("REC_ALERTS_SMTP_HOST") or "smtp.gmail.com").strip()
    port = int((os.getenv("REC_ALERTS_SMTP_PORT") or "587").strip())
    user = (os.getenv("REC_ALERTS_SMTP_USER") or "rec.io.alerts@gmail.com").strip()
    password = _smtp_password()
    from_addr = (os.getenv("REC_ALERTS_SMTP_FROM") or user).strip()
    return host, port, user, password, from_addr


def registration_verification_email_configured() -> bool:
    return bool(_smtp_password())


def _smtp_password_or_raise() -> tuple[str, str, int, str, str]:
    """Return (host, port, user, password, from_addr); raise if password missing."""
    host, port, user, password, from_addr = _smtp_config()
    if not password:
        raise RuntimeError(
            "SMTP password missing: env REC_ALERTS_SMTP_PASSWORD, REC_ALERTS_SMTP_PASSWORD_FILE, "
            "or backend/data/secrets/rec_alerts_smtp_password.txt"
        )
    return host, port, user, password, from_addr


def registration_verification_page_url(
    *, user_id: str, recipient_email: str | None = None
) -> str | None:
    """
    Absolute URL to the email-verification page on the public site.
    REC_PUBLIC_BASE_URL overrides the default https://rec-io.com.
    Optional recipient_email is appended so the page can show where the code was sent.
    """
    base = (os.getenv("REC_PUBLIC_BASE_URL") or "").strip().rstrip("/")
    if not base:
        base = _VERIFICATION_EMAIL_SITE_ORIGIN_DEFAULT
    uid = (user_id or "").strip()
    if not uid:
        return None
    q = f"user_id={quote(uid, safe='')}"
    em = (recipient_email or "").strip()
    if em:
        q += f"&email={quote(em, safe='')}"
    return f"{base}/register/verify?{q}"


def send_plaintext_alerts_email(to_email: str, subject: str, body: str) -> None:
    """Send one plain-text message using REC_ALERTS SMTP settings."""
    host, port, user, password, from_addr = _smtp_password_or_raise()
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = to_email
    msg.set_content(body)
    context = ssl.create_default_context()
    with smtplib.SMTP(host, port, timeout=30) as server:
        server.starttls(context=context)
        server.login(user, password)
        server.send_message(msg)


def _activation_login_href_and_label() -> tuple[str, str]:
    """Public login URL for activation email; REC_PUBLIC_BASE_URL for local testing."""
    base = (os.getenv("REC_PUBLIC_BASE_URL") or "").strip().rstrip("/")
    if base:
        return base, base
    return "https://www.rec-io.com", "www.rec-io.com"


def send_account_activated_email(
    to_email: str, *, first_name: str = ""
) -> None:
    """
    Notify a user that an admin approved their account (``pending_admin_approval`` → ``active``).

    Uses the same REC_ALERTS SMTP stack as registration verification.
    """
    href, link_label = _activation_login_href_and_label()
    subject = "Your Rec-io.com Account Has Been Approved"
    fn = (first_name or "").strip()
    greeting_plain = f"{fn},\n\n" if fn else ""
    greeting_html = (
        f"<p>{html.escape(fn)},</p>\n"
        if fn
        else ""
    )
    plain = (
        f"{greeting_plain}"
        "Your rec-io.com has been activated. "
        f"Please visit {href} to log in.\n"
    )
    html_body = (
        "<!DOCTYPE html><html><body>"
        f"{greeting_html}"
        "<p>Your rec-io.com has been activated.</p>"
        "<p>Please visit "
        f'<a href="{html.escape(href, quote=True)}">{html.escape(link_label)}</a> '
        "to log in.</p>"
        "</body></html>"
    )
    host, port, user, password, from_addr = _smtp_password_or_raise()
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = to_email
    msg.set_content(plain)
    msg.add_alternative(html_body, subtype="html")
    context = ssl.create_default_context()
    with smtplib.SMTP(host, port, timeout=30) as server:
        server.starttls(context=context)
        server.login(user, password)
        server.send_message(msg)


def send_alerts_smtp_test_email(to_email: str) -> None:
    """Smoke-test REC_ALERTS SMTP (same config as registration verification)."""
    send_plaintext_alerts_email(
        to_email,
        "rec.io alerts — SMTP test",
        "This is a test message from scripts/send_test_alerts_email.py.\n\n"
        "If you received this, REC_ALERTS SMTP credentials are working.\n",
    )


def _admin_notify_email() -> str:
    """Inbox for new-user application alerts (after email verification)."""
    return (os.getenv("REC_ALERTS_ADMIN_NOTIFY_EMAIL") or "rec.io.alerts@gmail.com").strip()


def send_new_user_application_submitted_alert(
    *,
    user_no: str,
    user_id: str,
    name: str,
    first_name: str,
    last_name: str,
    email: str,
    phone: str,
    account_type: str,
    registration_date: date | datetime | None,
    server_ip: str,
) -> None:
    """Notify admins that a registrant verified email and awaits approval."""
    to_addr = _admin_notify_email()
    subject = "New user account application (email verified)"
    reg = registration_date.isoformat(sep=" ", timespec="seconds") if registration_date else ""
    sip = server_ip or ""
    body = (
        "A new user completed email verification and is pending admin approval.\n\n"
        f"User no:        {user_no}\n"
        f"User ID:        {user_id}\n"
        f"Name:           {name or ''}\n"
        f"First name:     {first_name or ''}\n"
        f"Last name:      {last_name or ''}\n"
        f"Email:          {email or ''}\n"
        f"Phone:          {phone or ''}\n"
        f"Account type:   {account_type or ''}\n"
        f"Registered:     {reg}\n"
        f"Client IP:      {sip}\n"
        "\n"
        "Set system.master_users.status to 'active' when approved.\n"
    )
    send_plaintext_alerts_email(to_addr, subject, body)


def send_master_user_verification_email(
    to_email: str,
    *,
    code: str,
    user_id: str,
    full_name: str = "",
) -> None:
    """
    Send a 6-digit verification code. Raises on SMTP/auth errors or missing password.
    Includes a link to https://rec-io.com/register/verify (or REC_PUBLIC_BASE_URL).
    """
    subject = "Verify your rec.io account"
    greeting = f"Hi {full_name}," if (full_name or "").strip() else "Hi,"
    vurl = registration_verification_page_url(
        user_id=user_id, recipient_email=(to_email or "").strip() or None
    )
    link_block = (
        f"\n\nOpen this link to enter your code:\n{vurl}\n"
        if vurl
        else "\n\nOpen the verification page on https://rec-io.com and enter this code.\n"
    )
    body = (
        f"{greeting}\n\n"
        f"Your verification code is: {code}\n\n"
        f"This code expires in 24 hours. If you did not create an account for User ID "
        f"{user_id!r}, you can ignore this message."
        f"{link_block}"
        f"— rec.io alerts"
    )
    send_plaintext_alerts_email(to_email, subject, body)
