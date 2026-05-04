"""
QuickBooks / Intuit OAuth 2.0 browser flow for production HTTPS redirects.

Use when Intuit requires a public https:// redirect URI (localhost is rejected).

- GET /oauth/intuit/start — redirect to Intuit (requires REC_INTUIT_OAUTH_STATE_SECRET;
  in production also REC_INTUIT_OAUTH_ADMIN_SECRET and matching ?secret=).

- GET /oauth/intuit/callback — exchange code for tokens, show .env lines (HTML).

Local testing: run main app, expose with ngrok, set Intuit redirect URI to
https://<ngrok-host>/oauth/intuit/callback and optionally set
REC_INTUIT_OAUTH_REDIRECT_URI to that full URL if forwarded Host/proto are wrong.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import time
from pathlib import Path
from typing import Literal
from dotenv import dotenv_values
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from backend.bookkeeper.quickbooks import (
    build_authorization_url,
    exchange_authorization_code,
)
from backend.util.paths import get_quickbooks_credentials_dir

logger = logging.getLogger(__name__)

router = APIRouter(tags=["intuit-oauth"])

STATE_TTL_SEC = 900
CALLBACK_PATH = "/oauth/intuit/callback"


def _state_secret() -> bytes:
    raw = os.environ.get("REC_INTUIT_OAUTH_STATE_SECRET", "").strip()
    if not raw:
        raise HTTPException(
            status_code=503,
            detail="Set REC_INTUIT_OAUTH_STATE_SECRET (long random string) for OAuth state signing.",
        )
    return raw.encode("utf-8")


def build_signed_state(user_no: str, environment: str) -> str:
    now = int(time.time())
    payload = {
        "user_no": user_no,
        "environment": environment,
        "exp": now + STATE_TTL_SEC,
    }
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    sig = hmac.new(_state_secret(), body, hashlib.sha256).hexdigest()
    b64 = base64.urlsafe_b64encode(body).decode("ascii").rstrip("=")
    return f"{b64}.{sig}"


def parse_signed_state(state: str) -> dict[str, str | int]:
    try:
        enc, sig = state.split(".", 1)
        pad = "=" * (-len(enc) % 4)
        body = base64.urlsafe_b64decode((enc + pad).encode("ascii"))
        expected = hmac.new(_state_secret(), body, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, sig):
            raise ValueError("signature")
        payload = json.loads(body.decode("utf-8"))
        if int(payload["exp"]) < int(time.time()):
            raise ValueError("expired")
        u = str(payload.get("user_no") or "").strip()
        e = str(payload.get("environment") or "").strip().lower()
        if not u or e not in ("sandbox", "production"):
            raise ValueError("payload")
        return {"user_no": u, "environment": e}
    except HTTPException:
        raise
    except Exception as e:
        logger.warning("Intuit OAuth: invalid state (%s)", e)
        raise HTTPException(status_code=400, detail="Invalid or expired OAuth state.") from e


def effective_redirect_uri(request: Request) -> str:
    fixed = os.environ.get("REC_INTUIT_OAUTH_REDIRECT_URI", "").strip()
    if fixed:
        return fixed.rstrip("/")
    proto = (request.headers.get("x-forwarded-proto") or request.url.scheme or "https").split(
        ","
    )[0].strip()
    host = (request.headers.get("x-forwarded-host") or request.headers.get("host") or "").split(
        ","
    )[0].strip()
    if not host:
        raise HTTPException(
            status_code=500,
            detail="Cannot build redirect_uri (missing Host). Set REC_INTUIT_OAUTH_REDIRECT_URI.",
        )
    return f"{proto}://{host}{CALLBACK_PATH}"


def _intuit_client_credentials(cred_dir: Path) -> tuple[str, str]:
    path = cred_dir / ".env"
    if not path.is_file():
        raise HTTPException(status_code=400, detail=f"Missing QuickBooks env file: {path}")
    env = dotenv_values(path)
    cid = (env.get("INTUIT_CLIENT_ID") or "").strip()
    sec = (env.get("INTUIT_CLIENT_SECRET") or "").strip()
    if not cid or not sec:
        raise HTTPException(
            status_code=400,
            detail="INTUIT_CLIENT_ID and INTUIT_CLIENT_SECRET required in quickbooks .env",
        )
    return cid, sec


def _require_start_authorization(secret: str | None) -> None:
    expected = os.environ.get("REC_INTUIT_OAUTH_ADMIN_SECRET", "").strip()
    is_prod = os.getenv("REC_ENVIRONMENT", "").strip().lower() == "production"
    if is_prod:
        if not expected:
            raise HTTPException(
                status_code=503,
                detail="Set REC_INTUIT_OAUTH_ADMIN_SECRET for /oauth/intuit/start in production.",
            )
        if secret != expected:
            raise HTTPException(status_code=403, detail="Invalid or missing secret.")
        return
    if expected and secret != expected:
        raise HTTPException(status_code=403, detail="Invalid or missing secret.")


@router.get("/oauth/intuit/start")
async def intuit_oauth_start(
    request: Request,
    user_no: str = Query("0001", min_length=4, max_length=4, pattern=r"^\d{4}$"),
    environment: Literal["sandbox", "production"] = Query("production"),
    secret: str | None = Query(None),
) -> RedirectResponse:
    _require_start_authorization(secret)
    _state_secret()  # validate config early
    cred_dir = Path(get_quickbooks_credentials_dir(user_no))
    client_id, _ = _intuit_client_credentials(cred_dir)
    st = build_signed_state(user_no, environment)
    redirect_uri = effective_redirect_uri(request)
    url = build_authorization_url(client_id, redirect_uri, st)
    logger.info(
        "Intuit OAuth: redirecting user_no=%s environment=%s redirect_uri=%s",
        user_no,
        environment,
        redirect_uri,
    )
    return RedirectResponse(url=url, status_code=302)


@router.get(CALLBACK_PATH)
async def intuit_oauth_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    realmId: str | None = Query(None),
    error: str | None = None,
    error_description: str | None = None,
) -> HTMLResponse:
    if error:
        msg = _escape(str(error_description or error))
        return HTMLResponse(
            content=_html_page(
                "QuickBooks authorization failed",
                f"<p>{msg}</p>",
                ok=False,
            ),
            status_code=400,
        )
    if not code or not state or not realmId:
        raise HTTPException(
            status_code=400,
            detail="Missing code, state, or realmId from Intuit redirect.",
        )
    payload = parse_signed_state(state)
    user_no = str(payload["user_no"])
    environment = str(payload["environment"])
    cred_dir = Path(get_quickbooks_credentials_dir(user_no))
    client_id, client_secret = _intuit_client_credentials(cred_dir)
    redirect_uri = effective_redirect_uri(request)
    try:
        tokens = exchange_authorization_code(
            client_id,
            client_secret,
            code,
            redirect_uri,
        )
    except RuntimeError as e:
        logger.warning("Intuit OAuth token exchange failed: %s", e)
        return HTMLResponse(
            content=_html_page(
                "Token exchange failed",
                f"<pre>{_escape(str(e))}</pre>",
                ok=False,
            ),
            status_code=502,
        )
    refresh = tokens.get("refresh_token") or ""
    if not refresh:
        return HTMLResponse(
            content=_html_page(
                "Unexpected token response",
                f"<pre>{_escape(repr(tokens))}</pre>",
                ok=False,
            ),
            status_code=502,
        )
    lines = [
        f"QBO_ENVIRONMENT={environment}",
        f"QBO_REALM_ID={realmId}",
        f"INTUIT_REFRESH_TOKEN={refresh}",
    ]
    body = "\n".join(lines)
    cred_file = cred_dir / ".env"
    instructions = (
        f"<p>Add or merge these into <code>{_escape(str(cred_file))}</code> "
        "(keep your existing INTUIT_CLIENT_ID and INTUIT_CLIENT_SECRET).</p>"
    )
    return HTMLResponse(
        content=_html_page(
            "QuickBooks connected",
            f"{instructions}<pre>{_escape(body)}</pre>",
            ok=True,
        ),
        status_code=200,
    )


def _escape(s: str) -> str:
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _html_page(title: str, inner: str, *, ok: bool) -> str:
    status = "Success" if ok else "Error"
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><title>{_escape(title)}</title></head>
<body>
<h1>{_escape(title)}</h1>
<p><strong>{status}</strong></p>
{inner}
</body></html>"""
