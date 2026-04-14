"""
On-disk Kalshi prod auth metadata per tenant slot (``user_NNNN/credentials/...``).

Workers and HTTP handlers should use explicit ``user_no``; do not assume ``REC_USER_NO`` here.
"""

from __future__ import annotations

import logging
import os
from typing import Optional

from backend.util.paths import get_data_dir

_LOG = logging.getLogger(__name__)


def read_kalshi_prod_email_for_user_no(user_no: str) -> Optional[str]:
    """Return email from ``user_<slot>/credentials/kalshi-credentials/prod/kalshi-auth.txt``."""
    u = (user_no or "").strip().zfill(4)
    if len(u) != 4 or not u.isdigit():
        return None
    auth_file = os.path.join(
        get_data_dir(),
        "users",
        f"user_{u}",
        "credentials",
        "kalshi-credentials",
        "prod",
        "kalshi-auth.txt",
    )
    try:
        if not os.path.exists(auth_file):
            return None
        with open(auth_file, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                if line.startswith("email:"):
                    val = line.split("email:", 1)[1].strip()
                    return val or None
    except OSError as e:
        _LOG.warning("Kalshi auth email read failed for user_%s: %s", u, e)
    return None


def read_kalshi_prod_email_for_process_default_slot() -> Optional[str]:
    """``REC_USER_NO`` worker default (supervisor); prefer :func:`read_kalshi_prod_email_for_user_no` in APIs."""
    from backend.util.paths import _tenant_user_no_for_paths

    return read_kalshi_prod_email_for_user_no(_tenant_user_no_for_paths())
