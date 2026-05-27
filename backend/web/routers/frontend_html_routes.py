"""HTML shells and dev static fallbacks served by main_app (same-origin / session)."""

from __future__ import annotations

import logging
import os

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse

from backend.util.paths import get_frontend_dir
from backend.web.main_auth_gate import AUTH_ENABLED, query_token_auth_ok

_LOG = logging.getLogger("main_app")
frontend_dir = get_frontend_dir()

frontend_html_router = APIRouter(tags=["frontend_html"])


def _html_no_cache_headers() -> dict:
    return {
        "Cache-Control": "no-cache, no-store, must-revalidate",
        "Pragma": "no-cache",
        "Expires": "0",
    }


@frontend_html_router.get("/", response_class=HTMLResponse)
async def read_root():
    _LOG.debug("[AUTH] AUTH_ENABLED = %s", AUTH_ENABLED)
    if AUTH_ENABLED:
        _LOG.debug("[AUTH] Redirecting to login page")
        return RedirectResponse(url="/login")
    _LOG.debug("[AUTH] Serving main app directly (local development)")
    with open(f"{frontend_dir}/index.html", "r") as f:
        content = f.read()
        return HTMLResponse(
            content=content,
            headers={
                "Cache-Control": "no-cache, no-store, must-revalidate",
                "Pragma": "no-cache",
                "Expires": "0",
            },
        )


@frontend_html_router.get("/app", response_class=HTMLResponse)
async def serve_main_app(request: Request):
    if AUTH_ENABLED:
        if not query_token_auth_ok(request):
            return RedirectResponse(url="/login")
    with open(f"{frontend_dir}/index.html", "r") as f:
        content = f.read()
        return HTMLResponse(
            content=content,
            headers={
                "Cache-Control": "no-cache, no-store, must-revalidate",
                "Pragma": "no-cache",
                "Expires": "0",
            },
        )


@frontend_html_router.get("/login", response_class=HTMLResponse)
async def serve_login():
    try:
        with open(f"{frontend_dir}/login.html", "r") as f:
            content = f.read()
            return HTMLResponse(content=content, headers=_html_no_cache_headers())
    except FileNotFoundError:
        return HTMLResponse(content="<h1>Login</h1><p>Login page not found.</p>", status_code=404)


@frontend_html_router.get("/register", response_class=HTMLResponse)
async def serve_register():
    try:
        with open(os.path.join(frontend_dir, "register.html"), "r", encoding="utf-8") as f:
            content = f.read()
        return HTMLResponse(content=content, headers=_html_no_cache_headers())
    except FileNotFoundError:
        return HTMLResponse(
            content="<h1>Register</h1><p>register.html not found.</p>",
            status_code=404,
        )


@frontend_html_router.get("/register/verify", response_class=HTMLResponse)
async def serve_register_verify():
    try:
        with open(os.path.join(frontend_dir, "register-verify.html"), "r", encoding="utf-8") as f:
            content = f.read()
        return HTMLResponse(content=content, headers=_html_no_cache_headers())
    except FileNotFoundError:
        return HTMLResponse(
            content="<h1>Verify</h1><p>register-verify.html not found.</p>",
            status_code=404,
        )


@frontend_html_router.get("/register/application-submitted", response_class=HTMLResponse)
async def serve_register_application_submitted():
    try:
        with open(
            os.path.join(frontend_dir, "register-application-submitted.html"),
            "r",
            encoding="utf-8",
        ) as f:
            content = f.read()
        return HTMLResponse(content=content, headers=_html_no_cache_headers())
    except FileNotFoundError:
        return HTMLResponse(
            content="<h1>Application submitted</h1><p>register-application-submitted.html not found.</p>",
            status_code=404,
        )


@frontend_html_router.get("/favicon.ico")
async def serve_favicon():
    file_path = os.path.join(frontend_dir, "images", "icons", "fave.ico")
    if os.path.exists(file_path):
        return FileResponse(file_path)
    return {"error": "Favicon not found"}, 404


@frontend_html_router.get("/terminal-control.html", response_class=HTMLResponse)
async def serve_terminal_control():
    file_path = f"{frontend_dir}/terminal-control.html"
    if os.path.exists(file_path):
        with open(file_path, "r") as f:
            return HTMLResponse(content=f.read())
    return HTMLResponse(content="<h1>Terminal Control not found</h1>", status_code=404)


@frontend_html_router.get("/log-viewer.html", response_class=HTMLResponse)
async def serve_log_viewer():
    file_path = f"{frontend_dir}/log-viewer.html"
    if os.path.exists(file_path):
        with open(file_path, "r") as f:
            return HTMLResponse(content=f.read())
    return HTMLResponse(content="<h1>Log Viewer not found</h1>", status_code=404)


@frontend_html_router.get("/styles/{filename:path}")
async def serve_css(filename: str):
    file_path = f"{frontend_dir}/styles/{filename}"
    if os.path.exists(file_path):
        with open(file_path, "r") as f:
            content = f.read()
            return HTMLResponse(
                content=content,
                headers={
                    "Content-Type": "text/css",
                    "Cache-Control": "no-cache, no-store, must-revalidate",
                    "Pragma": "no-cache",
                    "Expires": "0",
                },
            )
    return HTMLResponse(content="CSS file not found", status_code=404)


@frontend_html_router.get("/js/{filename:path}")
async def serve_js(filename: str):
    file_path = f"{frontend_dir}/js/{filename}"
    if os.path.exists(file_path):
        with open(file_path, "r") as f:
            content = f.read()
            return HTMLResponse(
                content=content,
                headers={
                    "Content-Type": "application/javascript",
                    "Cache-Control": "no-cache, no-store, must-revalidate",
                    "Pragma": "no-cache",
                    "Expires": "0",
                },
            )
    return HTMLResponse(content="JS file not found", status_code=404)


@frontend_html_router.get("/hf_trade_monitor", response_class=HTMLResponse)
async def serve_hf_trade_monitor(request: Request):
    if AUTH_ENABLED:
        if not query_token_auth_ok(request):
            return RedirectResponse(url="/login")
    file_path = f"{frontend_dir}/tabs/hf_trade_monitor.html"
    if os.path.exists(file_path):
        with open(file_path, "r") as f:
            content = f.read()
            return HTMLResponse(
                content=content,
                headers={
                    "Cache-Control": "no-cache, no-store, must-revalidate",
                    "Pragma": "no-cache",
                    "Expires": "0",
                },
            )
    return HTMLResponse(content="HF Trade Monitor not found", status_code=404)


@frontend_html_router.get("/mobile/trade_monitor", response_class=HTMLResponse)
async def serve_mobile_trade_monitor(request: Request):
    if AUTH_ENABLED:
        if not query_token_auth_ok(request):
            return RedirectResponse(url="/login")
    file_path = f"{frontend_dir}/mobile/trade_monitor_mobile.html"
    if os.path.exists(file_path):
        with open(file_path, "r") as f:
            content = f.read()
            return HTMLResponse(
                content=content,
                headers={
                    "Cache-Control": "no-cache, no-store, must-revalidate",
                    "Pragma": "no-cache",
                    "Expires": "0",
                },
            )
    return HTMLResponse(content="Mobile trade monitor not found", status_code=404)


@frontend_html_router.get("/mobile/dashboard", response_class=HTMLResponse)
async def serve_mobile_dashboard(request: Request):
    if AUTH_ENABLED:
        if not query_token_auth_ok(request):
            return RedirectResponse(url="/login")
    file_path = f"{frontend_dir}/mobile/dashboard_mobile.html"
    if os.path.exists(file_path):
        with open(file_path, "r") as f:
            content = f.read()
            return HTMLResponse(
                content=content,
                headers={
                    "Cache-Control": "no-cache, no-store, must-revalidate",
                    "Pragma": "no-cache",
                    "Expires": "0",
                },
            )
    return HTMLResponse(content="Mobile dashboard not found", status_code=404)


@frontend_html_router.get("/mobile/dashboard_new", response_class=HTMLResponse)
async def serve_mobile_dashboard_new(request: Request):
    if AUTH_ENABLED:
        if not query_token_auth_ok(request):
            return RedirectResponse(url="/login")
    file_path = f"{frontend_dir}/mobile/dashboard_mobile.html"
    if os.path.exists(file_path):
        with open(file_path, "r") as f:
            content = f.read()
            return HTMLResponse(
                content=content,
                headers={
                    "Cache-Control": "no-cache, no-store, must-revalidate",
                    "Pragma": "no-cache",
                    "Expires": "0",
                },
            )
    return HTMLResponse(content="Mobile dashboard not found", status_code=404)


@frontend_html_router.get("/mobile/account_manager", response_class=HTMLResponse)
async def serve_mobile_account_manager(request: Request):
    if AUTH_ENABLED:
        if not query_token_auth_ok(request):
            return RedirectResponse(url="/login")
    file_path = f"{frontend_dir}/mobile/account_manager_mobile.html"
    if os.path.exists(file_path):
        with open(file_path, "r") as f:
            content = f.read()
            return HTMLResponse(
                content=content,
                headers={
                    "Cache-Control": "no-cache, no-store, must-revalidate",
                    "Pragma": "no-cache",
                    "Expires": "0",
                },
            )
    return HTMLResponse(content="Mobile account manager not found", status_code=404)


@frontend_html_router.get("/mobile", response_class=HTMLResponse)
async def serve_mobile_index(request: Request):
    if AUTH_ENABLED:
        if not query_token_auth_ok(request):
            return RedirectResponse(url="/login")
    file_path = f"{frontend_dir}/mobile/index.html"
    if os.path.exists(file_path):
        with open(file_path, "r") as f:
            content = f.read()
            return HTMLResponse(
                content=content,
                headers={
                    "Cache-Control": "no-cache, no-store, must-revalidate",
                    "Pragma": "no-cache",
                    "Expires": "0",
                },
            )
    return HTMLResponse(content="Mobile index not found", status_code=404)


@frontend_html_router.get("/mobile/index.html", response_class=HTMLResponse)
async def serve_mobile_index_html(request: Request):
    if AUTH_ENABLED:
        if not query_token_auth_ok(request):
            return RedirectResponse(url="/login")
    file_path = f"{frontend_dir}/mobile/index.html"
    if os.path.exists(file_path):
        with open(file_path, "r") as f:
            content = f.read()
            return HTMLResponse(
                content=content,
                headers={
                    "Cache-Control": "no-cache, no-store, must-revalidate",
                    "Pragma": "no-cache",
                    "Expires": "0",
                },
            )
    return HTMLResponse(content="Mobile index not found", status_code=404)


@frontend_html_router.get("/test-mobile")
async def test_mobile():
    return {"message": "Mobile test route works!"}


@frontend_html_router.get("/live-path-cache-monitor", response_class=HTMLResponse)
async def serve_live_path_cache_monitor():
    """Local dev UI: inspect any live_path / live_state Redis cache with WS updates."""
    file_path = f"{frontend_dir}/tabs/live_path_cache_monitor.html"
    if os.path.exists(file_path):
        with open(file_path, "r") as f:
            content = f.read()
            return HTMLResponse(
                content=content,
                headers={
                    "Cache-Control": "no-cache, no-store, must-revalidate",
                    "Pragma": "no-cache",
                    "Expires": "0",
                },
            )
    return HTMLResponse(content="Live path cache monitor not found", status_code=404)


@frontend_html_router.get("/active-trades-hot-path-test", response_class=HTMLResponse)
async def serve_active_trades_hot_path_test_redirect():
    """Legacy URL → generic monitor with active_trades preset."""
    return RedirectResponse(
        url="/live-path-cache-monitor?source=active_trades&user_no=0001",
        status_code=302,
    )


@frontend_html_router.get("/test_monitor_history_display.html", response_class=HTMLResponse)
async def serve_test_monitor_history_display():
    file_path = f"{frontend_dir}/test_monitor_history_display.html"
    if os.path.exists(file_path):
        with open(file_path, "r") as f:
            content = f.read()
            return HTMLResponse(
                content=content,
                headers={
                    "Cache-Control": "no-cache, no-store, must-revalidate",
                    "Pragma": "no-cache",
                    "Expires": "0",
                },
            )
    return HTMLResponse(content="Test page not found", status_code=404)


@frontend_html_router.get("/mobile/test")
async def test_mobile_path():
    return {"message": "Mobile path test route works!"}


@frontend_html_router.get("/mobile/user", response_class=HTMLResponse)
async def serve_mobile_user(request: Request):
    if AUTH_ENABLED:
        if not query_token_auth_ok(request):
            return RedirectResponse(url="/login")
    file_path = f"{frontend_dir}/mobile/user_mobile.html"
    if os.path.exists(file_path):
        with open(file_path, "r") as f:
            content = f.read()
            return HTMLResponse(
                content=content,
                headers={
                    "Cache-Control": "no-cache, no-store, must-revalidate",
                    "Pragma": "no-cache",
                    "Expires": "0",
                },
            )
    return HTMLResponse(content="Mobile user settings not found", status_code=404)


@frontend_html_router.get("/mobile/system", response_class=HTMLResponse)
async def serve_mobile_system(request: Request):
    if AUTH_ENABLED:
        if not query_token_auth_ok(request):
            return RedirectResponse(url="/login")
    file_path = f"{frontend_dir}/mobile/system_mobile.html"
    if os.path.exists(file_path):
        with open(file_path, "r") as f:
            content = f.read()
            return HTMLResponse(
                content=content,
                headers={
                    "Cache-Control": "no-cache, no-store, must-revalidate",
                    "Pragma": "no-cache",
                    "Expires": "0",
                },
            )
    return HTMLResponse(content="Mobile system page not found", status_code=404)


@frontend_html_router.get("/mobile/trade_history", response_class=HTMLResponse)
async def serve_mobile_trade_history(request: Request):
    if AUTH_ENABLED:
        if not query_token_auth_ok(request):
            return RedirectResponse(url="/login")
    file_path = f"{frontend_dir}/mobile/trade_history_mobile.html"
    if os.path.exists(file_path):
        with open(file_path, "r") as f:
            content = f.read()
            return HTMLResponse(
                content=content,
                headers={
                    "Cache-Control": "no-cache, no-store, must-revalidate",
                    "Pragma": "no-cache",
                    "Expires": "0",
                },
            )
    return HTMLResponse(content="Mobile trade history not found", status_code=404)
