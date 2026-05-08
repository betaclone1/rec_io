"""Shared auth flag and lightweight token check for main_app HTML and static routes."""

from __future__ import annotations

import os

from fastapi import Request

from backend.web.session_store import find_valid_token

AUTH_ENABLED = os.environ.get("AUTH_ENABLED", "false").lower() == "true"
if os.environ.get("REC_ENVIRONMENT") == "production":
    AUTH_ENABLED = True


def query_token_auth_ok(request: Request) -> bool:
    if not AUTH_ENABLED:
        return True
    token = (request.query_params.get("token") or "").strip()
    if not token:
        ck = request.cookies.get("rec_auth_token")
        token = (ck or "").strip()
    if not token:
        return False
    return find_valid_token(token) is not None
