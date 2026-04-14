"""
Shim: login principal resolution lives in :mod:`backend.web.auth_principals`.
"""

from __future__ import annotations

from backend.web.auth_principals import (  # noqa: F401
    fetch_login_principal,
    password_matches_principal,
    try_legacy_json_login,
)

__all__ = [
    "fetch_login_principal",
    "password_matches_principal",
    "try_legacy_json_login",
]
