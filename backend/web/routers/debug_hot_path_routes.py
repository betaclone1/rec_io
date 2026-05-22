"""Legacy import path — routes live in live_path_cache_monitor_routes."""

from backend.web.routers.live_path_cache_monitor_routes import live_path_cache_monitor_router

debug_hot_path_router = live_path_cache_monitor_router
