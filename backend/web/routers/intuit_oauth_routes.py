"""
QuickBooks / Intuit OAuth on main_app edge.

Implementation lives in :mod:`backend.bookkeeper.intuit_oauth_routes`; this module
keeps all ``include_router`` sources under ``backend.web.routers``.
"""

from backend.bookkeeper.intuit_oauth_routes import router as intuit_oauth_router

__all__ = ["intuit_oauth_router"]
