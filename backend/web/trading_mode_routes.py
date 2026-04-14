"""
HTTP routes for global live/paper trading mode and tenant-scoped UI labels.

Side effects (WebSocket broadcast, monitor ripple) are injected from ``main`` via
:func:`configure_trading_mode_hooks` to avoid circular imports.

Per-tenant responses are cached briefly in Redis (see :mod:`backend.core.trading_mode_ui_cache`);
revision bumps on successful mode change.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Callable, Coroutine, Dict, Optional

from fastapi import APIRouter
from starlette.responses import Response

from backend.core.exchange_credentials import live_kalshi_trading_allowed_for_user_no
from backend.core.kalshi_auth_files import read_kalshi_prod_email_for_user_no
from backend.core.tenant_context import resolved_tenant_user_no_for_app
from backend.core.trading_mode_ui_cache import (
    trading_mode_ui_cache_bump_revision,
    trading_mode_ui_cache_get,
    trading_mode_ui_cache_set,
)
from backend.trading_mode import get_trading_mode, set_trading_mode as persist_trading_mode
from backend.util.paths import get_data_dir
from backend.web.session_user_credentials import fetch_session_master_user_credentials

_LOG = logging.getLogger(__name__)

trading_mode_router = APIRouter(tags=["trading_mode"])

_broadcast_trading_mode: Optional[Callable[[str], Coroutine[Any, Any, None]]] = None
_ripple_bankroll_to_monitors: Optional[Callable[[], Coroutine[Any, Any, None]]] = None


def configure_trading_mode_hooks(
    *,
    broadcast_trading_mode: Callable[[str], Coroutine[Any, Any, None]],
    ripple_bankroll_to_monitors: Callable[[], Coroutine[Any, Any, None]],
) -> None:
    global _broadcast_trading_mode, _ripple_bankroll_to_monitors
    _broadcast_trading_mode = broadcast_trading_mode
    _ripple_bankroll_to_monitors = ripple_bankroll_to_monitors


def _api_no_store_headers(response: Response) -> None:
    response.headers["Cache-Control"] = "private, no-store, max-age=0, must-revalidate"
    response.headers["Pragma"] = "no-cache"


def build_trading_mode_api_payload(user_no: str) -> Dict[str, Any]:
    """JSON body for ``GET /api/trading_mode`` (tenant-scoped labels, global mode)."""
    live_ok = live_kalshi_trading_allowed_for_user_no(user_no)
    tm = get_trading_mode()
    if not live_ok and tm == "live":
        tm = "paper"
    gp = tm == "paper"
    live_label = "LIVE"
    paper_label = "PAPER"
    try:
        e = read_kalshi_prod_email_for_user_no(user_no) if live_ok else None
        bad = ("no email", "no credentials", "error reading")
        if e and not any(b in str(e).lower() for b in bad):
            live_label = f"LIVE - {e}"
    except Exception:
        pass
    try:
        creds = fetch_session_master_user_credentials()
        name = (creds or {}).get("name")
        if name:
            paper_label = f"PAPER - {name}"
    except Exception:
        pass
    return {
        "trading_mode": tm,
        "global_paper_mode": gp,
        "live_label": live_label,
        "paper_label": paper_label,
        "live_trading_available": live_ok,
    }


@trading_mode_router.get("/trading_mode")
async def get_trading_mode_endpoint(response: Response) -> Dict[str, Any]:
    _api_no_store_headers(response)
    u = resolved_tenant_user_no_for_app()
    cached = trading_mode_ui_cache_get(u)
    if cached is not None:
        return cached
    payload = build_trading_mode_api_payload(u)
    trading_mode_ui_cache_set(u, payload)
    return payload


@trading_mode_router.post("/set_trading_mode")
async def set_trading_mode_endpoint(payload: dict) -> Dict[str, Any]:
    mode = (payload or {}).get("trading_mode")
    m = (mode or "").strip().lower()
    slot = resolved_tenant_user_no_for_app()
    if m == "live" and not live_kalshi_trading_allowed_for_user_no(slot):
        return {
            "status": "error",
            "message": "Live trading is not enabled for this account (paper only).",
        }
    norm, err = persist_trading_mode(mode)
    if err:
        return {"status": "error", "message": err}
    trading_mode_ui_cache_bump_revision()
    if _broadcast_trading_mode is not None:
        await _broadcast_trading_mode(norm)
    if _ripple_bankroll_to_monitors is not None:
        await _ripple_bankroll_to_monitors()
    return {"status": "ok", "trading_mode": norm, "global_paper_mode": norm == "paper"}


@trading_mode_router.get("/get_kalshi_email")
async def get_kalshi_email_endpoint() -> Dict[str, str]:
    """Prod Kalshi email from on-disk auth for the logged-in tenant."""
    try:
        slot = resolved_tenant_user_no_for_app().strip().zfill(4)
        email = read_kalshi_prod_email_for_user_no(slot)
        if email:
            return {"email": email}
        auth_file = os.path.join(
            get_data_dir(),
            "users",
            f"user_{slot}",
            "credentials",
            "kalshi-credentials",
            "prod",
            "kalshi-auth.txt",
        )
        if os.path.exists(auth_file):
            return {"email": "No email found in credentials"}
        return {"email": "No credentials found"}
    except Exception as e:
        _LOG.warning("get_kalshi_email: %s", e)
        return {"email": "Error reading credentials"}
