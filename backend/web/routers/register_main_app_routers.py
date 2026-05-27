"""Trading-mode hook wiring, static mounts, and include_router calls (order matters for overlaps)."""

from fastapi import FastAPI

from backend.web.configure_trading_mode_app import wire_trading_mode_for_main_app
from backend.web.main_app_static import mount_frontend_static
from backend.web.main_realtime import realtime_ws_router
from backend.web.routers.admin_routes import admin_router
from backend.web.routers.auto_entry_main_routes import auto_entry_main_router
from backend.web.routers.debug_hot_path_routes import debug_hot_path_router
from backend.web.routers.dashboard_read_proxy_routes import dashboard_read_proxy_router
from backend.web.routers.frontend_html_routes import frontend_html_router
from backend.web.routers.hft_routes import hft_router
from backend.web.routers.internal_service_proxy_routes import internal_service_proxy_router
from backend.web.routers.intuit_oauth_routes import intuit_oauth_router
from backend.web.routers.main_health_routes import main_health_router
from backend.web.routers.main_misc_routes import main_misc_router
from backend.web.routers.monitor_command_routes import monitor_command_router
from backend.web.routers.read_api_auth_proxy_routes import read_api_auth_proxy_router
from backend.web.routers.read_api_passthrough_routes import read_api_passthrough_router
from backend.web.routers.subaccount_routes import subaccount_router
from backend.web.trading_mode_routes import trading_mode_router


def register_main_app_routers(app: FastAPI) -> None:
    wire_trading_mode_for_main_app()
    mount_frontend_static(app)
    app.include_router(trading_mode_router, prefix="/api")
    app.include_router(intuit_oauth_router)
    app.include_router(realtime_ws_router)
    app.include_router(main_health_router)
    app.include_router(debug_hot_path_router)
    app.include_router(read_api_auth_proxy_router)
    app.include_router(frontend_html_router)
    app.include_router(admin_router)
    app.include_router(dashboard_read_proxy_router)
    app.include_router(read_api_passthrough_router)
    app.include_router(subaccount_router)
    app.include_router(monitor_command_router)
    app.include_router(internal_service_proxy_router)
    app.include_router(main_misc_router)
    app.include_router(hft_router)
    app.include_router(auto_entry_main_router)
