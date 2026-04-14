"""
Per-request API tenant. Canonical implementation: :mod:`backend.web.tenant_asgi`.
"""

from __future__ import annotations

from backend.web.tenant_asgi import (  # noqa: F401
    WebRequestTenantMiddleware,
    WebTenantMiddleware,
    get_web_api_user_no,
)

__all__ = [
    "WebRequestTenantMiddleware",
    "WebTenantMiddleware",
    "get_web_api_user_no",
]
