"""Safety gates for position_risk_engine (observe + ATS consume)."""

from __future__ import annotations

import os
from typing import Optional, Tuple


# Canonical production markers (retained for diagnostics / optional callers).
PROD_PROJECT_ROOT_PREFIX = "/opt/rec_io_server"
PROD_DB_HOSTS = frozenset({"165.22.13.146"})


def _truthy(raw: Optional[str]) -> bool:
    return (raw or "").strip().lower() in ("1", "true", "yes", "on")


def looks_like_production_host() -> bool:
    """Best-effort production detection (informational; does not block PRE)."""
    if _truthy(os.getenv("REC_IS_PRODUCTION")):
        return True
    root = (os.getenv("REC_PROJECT_ROOT") or "").strip()
    if root.startswith(PROD_PROJECT_ROOT_PREFIX):
        return True
    cwd = os.getcwd()
    if cwd.startswith(PROD_PROJECT_ROOT_PREFIX):
        return True
    for key in ("REC_PROD_SSH_HOST", "REC_PROD_DB_HOST", "DB_HOST", "REC_DB_HOST"):
        val = (os.getenv(key) or "").strip()
        if not val:
            continue
        if val in PROD_DB_HOSTS:
            return True
        if key in ("REC_PROD_SSH_HOST", "REC_PROD_DB_HOST"):
            return True
    return False


def assert_safe_to_run_observe() -> Tuple[bool, str]:
    """PRE may run locally and on production (HWS Scalp VWAP authority)."""
    return True, "ok"


def assert_safe_for_paper_consume() -> Tuple[bool, str]:
    """ATS may consume PRE decisions locally and on production."""
    return True, "ok"
