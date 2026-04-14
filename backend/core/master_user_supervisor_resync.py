"""Regenerate supervisord and apply changes after ``system.master_users`` status updates."""

from __future__ import annotations

import logging
import os
import subprocess
import sys
from typing import Any, Optional, Tuple

_LOG = logging.getLogger(__name__)


def master_user_trading_active(status: Optional[Any]) -> bool:
    """
    True when this row is treated as an active trading user in supervisor discovery.

    Matches ``generate_unified_supervisor_config``:
    ``COALESCE(NULLIF(TRIM(LOWER(status)), ''), 'active') = 'active'``.
    """
    if status is None:
        return True
    s = str(status).strip().lower()
    if not s:
        return True
    return s == "active"


def resync_supervisor_after_master_users_db_change(
    *,
    logger: Optional[logging.Logger] = None,
) -> Tuple[bool, str]:
    """
    Run ``generate_unified_supervisor_config.py`` then ``supervisorctl reread`` / ``update``.

    Mirrors the pattern in ``main.py`` (monitor activate/deactivate). Safe to call when
    supervisord is not running (logs failure, returns False).
    """
    log = logger or _LOG
    if os.environ.get("REC_SKIP_MASTER_USER_SUPERVISOR_RESYNC", "").strip() in (
        "1",
        "true",
        "yes",
    ):
        return True, "skipped (REC_SKIP_MASTER_USER_SUPERVISOR_RESYNC)"

    try:
        from backend.util.paths import (
            get_project_root,
            get_supervisor_config_path,
            get_supervisorctl_path,
        )
    except Exception as exc:
        return False, f"path helpers import failed: {exc}"

    proot = get_project_root()
    gen_script = os.path.join(proot, "scripts", "config", "generate_unified_supervisor_config.py")
    if not os.path.isfile(gen_script):
        return False, f"generate script missing: {gen_script}"

    env = os.environ.copy()
    env.setdefault("PYTHONPATH", proot)
    env.setdefault("REC_PROJECT_ROOT", proot)

    r0 = subprocess.run(
        [sys.executable, gen_script],
        cwd=proot,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    if r0.returncode != 0:
        detail = (r0.stderr or r0.stdout or "").strip() or f"exit {r0.returncode}"
        log.warning("[MASTER_USER] generate_unified_supervisor_config failed: %s", detail[:2000])
        return False, detail[:500]

    ctl = get_supervisorctl_path()
    cfg = get_supervisor_config_path()
    for cmd in ("reread", "update"):
        r = subprocess.run(
            [ctl, "-c", cfg, cmd],
            cwd=proot,
            capture_output=True,
            text=True,
            timeout=120,
        )
        if r.returncode != 0:
            detail = (r.stderr or r.stdout or "").strip() or f"supervisorctl {cmd} exit {r.returncode}"
            log.warning("[MASTER_USER] supervisorctl %s failed: %s", cmd, detail[:2000])
            return False, detail[:500]

    log.info("[MASTER_USER] supervisord config regenerated and supervisorctl update applied")
    return True, "ok"
