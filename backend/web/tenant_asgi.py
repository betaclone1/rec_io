"""
Pure ASGI middleware: bind session token to ContextVar for tenant DB access.
Supports HTTP and WebSocket. Do not use BaseHTTPMiddleware (Starlette task boundary issues).

Tenant is derived only from a valid session token: ``token`` query param, ``Authorization: Bearer``,
``Cookie: rec_auth_token=...`` (preferred for WebSocket upgrades; browsers send it reliably on
same-origin handshakes), or (for WebSocket) ``Sec-WebSocket-Protocol`` when a value validates as a token.

**Tenant API access:** by default every ``/api/*`` path except the auth allowlist requires a valid
session token (401 if missing). The allowlist includes login/verify/logout and self-service
registration (``POST /api/auth/register`` and related). There is no implicit “default user” for
HTTP APIs. To temporarily restore legacy anonymous ``/api/*`` in local tooling only, set
``REC_ALLOW_ANONYMOUS_API=1``.

Processes that serve user data should also set ``REC_STRICT_SESSION_TENANT_FOR_DB=1`` so
:func:`backend.core.config.database.get_postgresql_connection` refuses process-default tenant
fallback when no session is bound (see :mod:`backend.core.tenant_context`).
"""

from __future__ import annotations

import contextvars
import os
import re
from typing import List, Optional
from urllib.parse import parse_qs, unquote

from starlette.types import ASGIApp, Receive, Scope, Send

from backend.web.session_store import find_valid_token

_web_api_user_no: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "rec_web_api_user_no", default=None
)

_USER_NO_RE = re.compile(r"^\d{4}$")


def get_web_api_user_no() -> Optional[str]:
    """Four-digit slot from the current HTTP/WebSocket request, if middleware bound one."""
    return _web_api_user_no.get()


def resolve_session_user_no_from_asgi_scope(scope: Scope) -> Optional[str]:
    """Same resolution as middleware (valid token only). For WebSocket handlers before accept."""
    return _resolve_user_no(scope)


def _parse_query(scope: Scope) -> dict:
    raw = scope.get("query_string") or b""
    try:
        return parse_qs(raw.decode("utf-8"), keep_blank_values=True)
    except Exception:
        return {}


def _token_from_cookie(scope: Scope) -> str:
    """
    Read ``rec_auth_token`` from the ``Cookie`` header (URL-decoded value).

    Browsers attach cookies to same-origin WebSocket upgrades automatically; this is the
    most reliable auth carrier for ``/ws/*`` across browsers (query params are flaky).
    """
    for k, v in scope.get("headers") or []:
        if k.lower() != b"cookie":
            continue
        try:
            raw = v.decode("latin-1")
        except Exception:
            continue
        for part in raw.split(";"):
            piece = part.strip()
            if not piece:
                continue
            low = piece.lower()
            if not low.startswith("rec_auth_token="):
                continue
            val = piece.split("=", 1)[1].strip()
            try:
                return unquote(val).strip()
            except Exception:
                return val.strip()
    return ""


def _sec_websocket_protocol_parts(scope: Scope) -> List[str]:
    """Client-requested subprotocols from the upgrade request (comma-separated per RFC 6455)."""
    parts: List[str] = []
    for k, v in scope.get("headers") or []:
        if k.lower() != b"sec-websocket-protocol":
            continue
        try:
            raw = v.decode("latin-1").strip()
        except Exception:
            continue
        for seg in raw.split(","):
            s = seg.strip()
            if s:
                parts.append(s)
    return parts


def valid_token_from_sec_websocket_protocol(scope: Scope) -> Optional[str]:
    """
    If the client offered a subprotocol value that is a valid session token, return that exact
    string so the server can echo it in ``Sec-WebSocket-Protocol`` on accept.
    """
    for p in _sec_websocket_protocol_parts(scope):
        if find_valid_token(p):
            return p
    return None


def _token_from_scope(scope: Scope) -> str:
    qs = _parse_query(scope)
    toks = qs.get("token") or []
    qs_tok = str(toks[0]).strip() if toks and str(toks[0]).strip() else ""

    auth_tok = ""
    for k, v in scope.get("headers") or []:
        if k.lower() != b"authorization":
            continue
        try:
            auth = v.decode("latin-1").strip()
        except Exception:
            continue
        if auth.lower().startswith("bearer "):
            t = auth[7:].strip()
            if t:
                auth_tok = t
                break

    cookie_tok = _token_from_cookie(scope)

    # WebSocket: browsers send Cookie reliably on same-origin upgrades; query params are often
    # dropped or mishandled. Prefer cookie, then query, then Sec-WebSocket-Protocol.
    if scope.get("type") == "websocket":
        if cookie_tok:
            return cookie_tok
        if qs_tok:
            return qs_tok
        t = valid_token_from_sec_websocket_protocol(scope)
        return t if t else ""

    # HTTP: explicit query and Bearer win over cookie (API clients; avoids stale cookie shadowing).
    if qs_tok:
        return qs_tok
    if auth_tok:
        return auth_tok
    if cookie_tok:
        return cookie_tok
    return ""


def _resolve_user_no(scope: Scope) -> Optional[str]:
    """Valid session only. Invalid or missing token → None."""
    token = _token_from_scope(scope)
    if not token:
        return None
    hit = find_valid_token(token)
    if hit:
        raw = str(hit[0]).strip()
        if raw.isdigit() and len(raw) <= 4:
            raw = raw.zfill(4)
        return raw if _USER_NO_RE.match(raw) else None
    return None


def _http_path_allowed_without_tenant(path: str, method: str) -> bool:
    m = (method or "GET").upper()
    if m == "OPTIONS":
        return True
    if path == "/health":
        return True
    if path in ("/docs", "/redoc", "/openapi.json"):
        return True
    if path.startswith("/api/auth/login") and m == "POST":
        return True
    if path.startswith("/api/auth/verify") and m == "POST":
        return True
    if path.startswith("/api/auth/logout") and m == "POST":
        return True
    # Self-service master user registration (HTML on main_app; POST proxied to read_api).
    if path.startswith("/api/auth/register") and m == "POST":
        return True
    # Global deploy label (Redis); not tenant-specific. read_api serves this on :3050 where
    # session cookies from main_app (:3000) are not sent — must stay anonymous-safe.
    if path == "/api/system/release_version" and m == "GET":
        return True
    # Kalshi orderbook UI snapshot (Redis); no tenant row. Trade monitor on :3000 fetches :3050
    # without session cookies — same pattern as release_version.
    if path == "/api/orderbook" and m == "GET":
        return True
    if path == "/api/trade-monitor/orderbook" and m == "GET":
        return True
    if path == "/api/trade-monitor/strike-ladder" and m == "GET":
        return True
    if path == "/api/live_strike_ladder_bootstrap" and m == "GET":
        return True
    if path == "/api/live_symbol_spot_bootstrap" and m == "GET":
        return True
    if path == "/api/trade-monitor/orderbook_watch" and m == "POST":
        return True
    return False


def _reject_anonymous_api_requests() -> bool:
    """
    When True, /api/* without a valid session token gets 401 (except the auth allowlist).

    Default is always reject (no implicit default tenant for browsers or API clients).
    Set REC_ALLOW_ANONYMOUS_API=1 only for legacy local scripts that cannot send a session.
    """
    if os.environ.get("REC_ALLOW_ANONYMOUS_API", "").strip().lower() in (
        "1",
        "true",
        "yes",
    ):
        return False
    return True


def _http_path_requires_authenticated_tenant(path: str, method: str) -> bool:
    """Paths that must resolve a valid session token (same as /api/* minus auth allowlist)."""
    m = (method or "GET").upper()
    if m == "OPTIONS":
        return False
    if path.startswith("/api/"):
        return not _http_path_allowed_without_tenant(path, method)
    if path == "/trades" or path.startswith("/trades/"):
        return True
    return False


async def _send_json_401(send: Send) -> None:
    body = b'{"detail":"Not authenticated"}'
    await send(
        {
            "type": "http.response.start",
            "status": 401,
            "headers": [
                (b"content-type", b"application/json; charset=utf-8"),
                (b"content-length", str(len(body)).encode("ascii")),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})


class WebTenantMiddleware:
    """Starlette/FastAPI middleware: set tenant ContextVar for HTTP and WebSocket."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return

        path = scope.get("path") or ""
        method = scope.get("method", "GET") or "GET"

        if scope["type"] == "http":
            # Avoid synchronous token filesystem scan on hot paths (static assets, /health, …).
            # Only resolve session when the route requires an authenticated tenant (or optional
            # anonymous /api when REC_ALLOW_ANONYMOUS_API is set).
            if not _http_path_requires_authenticated_tenant(path, method):
                await self.app(scope, receive, send)
                return
            user_no = _resolve_user_no(scope)
            if user_no is None and _reject_anonymous_api_requests():
                await _send_json_401(send)
                return
            if user_no is None:
                await self.app(scope, receive, send)
                return
            tok = _web_api_user_no.set(user_no)
            try:
                await self.app(scope, receive, send)
            finally:
                _web_api_user_no.reset(tok)
            return

        user_no = _resolve_user_no(scope)
        if user_no is None:
            await self.app(scope, receive, send)
            return
        tok = _web_api_user_no.set(user_no)
        try:
            await self.app(scope, receive, send)
        finally:
            _web_api_user_no.reset(tok)


# Backward-compatible name used elsewhere in the codebase
WebRequestTenantMiddleware = WebTenantMiddleware


def attach_request_user_no(request) -> None:
    """Set ContextVar from a Starlette Request (tests)."""
    from starlette.requests import Request

    if not isinstance(request, Request):
        return
    scope = request.scope
    user_no = _resolve_user_no(scope)
    if user_no is not None:
        _web_api_user_no.set(user_no)
