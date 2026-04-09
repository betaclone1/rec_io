"""Resolve production DB / SSH hostname when operating from a dev machine (no literal droplet IP in code)."""

from __future__ import annotations

import os
from typing import Optional

_LOCAL = frozenset({"localhost", "127.0.0.1", "::1"})

# Public IPv4 for SSH + Postgres on current prod (droplet default in runbooks). Keep in
# sync with docs/PRODUCTION_HOST.md; used when REC_PROD_* is unset (e.g. Finder-launched GUI).
CANONICAL_PRODUCTION_PUBLIC_IPV4 = "165.22.13.146"


def _strip(key: str) -> Optional[str]:
    v = (os.getenv(key) or "").strip()
    return v or None


def get_production_db_host() -> Optional[str]:
    """
    Explicit non-loopback prod target. Set one of:
    - REC_PROD_DB_HOST (PostgreSQL hostname)
    - REC_PROD_SSH_HOST (often same machine as DB; used when DB host not set separately)
    """
    for key in ("REC_PROD_DB_HOST", "REC_PROD_SSH_HOST"):
        v = _strip(key)
        if v and v.lower() not in _LOCAL:
            return v
    return None


def resolve_production_db_host_for_gui() -> tuple[str, bool]:
    """
    Host for interactive tools (Analytics GUI): env first, else CANONICAL_PRODUCTION_PUBLIC_IPV4.

    Returns (host, from_explicit_env). from_explicit_env is True when REC_PROD_DB_HOST or
    REC_PROD_SSH_HOST was set and non-loopback.
    """
    explicit = get_production_db_host()
    if explicit:
        return explicit, True
    return CANONICAL_PRODUCTION_PUBLIC_IPV4, False


def get_legacy_script_db_host() -> str:
    """
    Fallback chain for older tests/scripts that used a hardcoded prod IP.
    Order: REC_PROD_DB_HOST, REC_PROD_SSH_HOST, POSTGRES_HOST, REC_DB_HOST, DB_HOST, then localhost.
    """
    for key in ("REC_PROD_DB_HOST", "REC_PROD_SSH_HOST", "POSTGRES_HOST", "REC_DB_HOST", "DB_HOST"):
        v = _strip(key)
        if v:
            return v
    return "localhost"
