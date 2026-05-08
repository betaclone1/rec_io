"""Tenant + CORS middleware for main_app."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.util.paths import get_host
from backend.web.main_app_cors import main_app_cors_allow_origins
from backend.web.tenant_asgi import WebTenantMiddleware


def install_main_app_middleware(app: FastAPI, main_app_port: int) -> None:
    app.add_middleware(WebTenantMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=main_app_cors_allow_origins(get_host(), main_app_port),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
