"""
Argparse helpers for operator scripts that touch ``users_NNNN`` (see docs/TENANT_TOUCH_REGISTRY.md).
"""

from __future__ import annotations

import argparse
import os
import re


def add_user_no_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--user-no",
        metavar="NNNN",
        help="4-digit trading user (schema users_NNNN). In multi-user mode, required unless REC_USER_NO is set.",
    )


def resolve_user_no(args: argparse.Namespace) -> str:
    raw = getattr(args, "user_no", None)
    if raw is not None and str(raw).strip():
        s = str(raw).strip()
        if not re.fullmatch(r"\d{4}", s):
            raise SystemExit(f"Invalid --user-no {s!r} (expected 4 digits)")
        return s

    from backend.core.tenant_context import is_single_user_mode

    env_u = (os.environ.get("REC_USER_NO") or "").strip()
    if env_u and re.fullmatch(r"\d{4}", env_u):
        return env_u

    if is_single_user_mode():
        login = (os.environ.get("REC_DEFAULT_LOGIN_USER_NO") or "0001").strip()
        if re.fullmatch(r"\d{4}", login):
            return login
        return "0001"

    raise SystemExit(
        "Multi-user: pass --user-no NNNN or set REC_USER_NO (or run with REC_SINGLE_USER_MODE=1)."
    )


def tenant_schema_for_user_no(user_no: str) -> str:
    if not re.fullmatch(r"\d{4}", user_no):
        raise ValueError(user_no)
    return f"users_{user_no}"
