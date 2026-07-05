"""Opaque proxies from main_app to read_api for auth and user profile (same-origin cookies)."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Request
from starlette.responses import Response

from backend.core.port_config import get_port
from backend.web.read_api_proxy import as_starlette_response, proxy_read_api_raw

_LOG = logging.getLogger("main_app")
READ_API_BASE_URL = f"http://127.0.0.1:{get_port('read_api')}"

read_api_auth_proxy_router = APIRouter(tags=["auth_proxy"])


async def _forward(
    request: Request, method: str, path: str, body: bytes | None = None
) -> Response:
    r = await proxy_read_api_raw(request, method, path, READ_API_BASE_URL, _LOG, body)
    return await as_starlette_response(r)


@read_api_auth_proxy_router.post("/api/auth/login")
async def login(request: Request):
    body = await request.body()
    return await _forward(request, "POST", "/api/auth/login", body)


@read_api_auth_proxy_router.post("/api/auth/verify")
async def verify_auth(request: Request):
    body = await request.body()
    return await _forward(request, "POST", "/api/auth/verify", body)


@read_api_auth_proxy_router.post("/api/auth/logout")
async def logout(request: Request):
    body = await request.body()
    return await _forward(request, "POST", "/api/auth/logout", body)


@read_api_auth_proxy_router.post("/api/auth/register")
async def auth_register(request: Request):
    body = await request.body()
    return await _forward(request, "POST", "/api/auth/register", body)


@read_api_auth_proxy_router.post("/api/auth/register/verify-email")
async def auth_register_verify_email(request: Request):
    body = await request.body()
    return await _forward(request, "POST", "/api/auth/register/verify-email", body)


@read_api_auth_proxy_router.post("/api/auth/register/resend-verification")
async def auth_register_resend_verification(request: Request):
    body = await request.body()
    return await _forward(request, "POST", "/api/auth/register/resend-verification", body)


@read_api_auth_proxy_router.get("/api/user/info")
async def get_user_info(request: Request):
    return await _forward(request, "GET", "/api/user/info")


@read_api_auth_proxy_router.get("/api/user/admin/master_users")
async def get_admin_master_users(request: Request):
    return await _forward(request, "GET", "/api/user/admin/master_users")


@read_api_auth_proxy_router.patch("/api/user/admin/master_users")
async def patch_admin_master_users(request: Request):
    body = await request.body()
    return await _forward(request, "PATCH", "/api/user/admin/master_users", body)


@read_api_auth_proxy_router.get("/api/user/admin/master_events")
async def get_admin_master_events(request: Request):
    path = "/api/user/admin/master_events"
    if request.url.query:
        path = f"{path}?{request.url.query}"
    return await _forward(request, "GET", path)


@read_api_auth_proxy_router.get("/api/user/admin/master_events/categories")
async def get_admin_master_event_categories(request: Request):
    return await _forward(request, "GET", "/api/user/admin/master_events/categories")


@read_api_auth_proxy_router.post("/api/user/change-password")
async def change_password(request: Request):
    body = await request.body()
    return await _forward(request, "POST", "/api/user/change-password", body)


@read_api_auth_proxy_router.post("/api/user/activity")
async def post_user_activity(request: Request):
    body = await request.body()
    return await _forward(request, "POST", "/api/user/activity", body)
