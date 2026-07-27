"""Upload cycle packages to Google Drive (post-package hook).

Invokes ``scripts/gdrive/upload-backtesting-data.js`` with the same OAuth files
used by daily briefing / prod secrets.

Enable with ``CYCLE_GDRIVE_UPLOAD=1`` (default when creds resolve).
Disable with ``CYCLE_GDRIVE_UPLOAD=0``.
Legacy alias: ``BTC15M_CYCLE_GDRIVE_UPLOAD``.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
from pathlib import Path
from typing import List, Optional, Sequence

logger = logging.getLogger("cycle_gdrive")

_DEFAULT_FOLDER_ID = "1Jlhz57hSXMYe8Yr_GtIJsaXY0GAW6L1v"


def _env_first(*names: str, default: str = "") -> str:
    for name in names:
        raw = os.getenv(name)
        if raw is not None and str(raw).strip() != "":
            return str(raw).strip()
    return default


_UPLOAD_TIMEOUT_SEC = int(
    _env_first(
        "CYCLE_GDRIVE_UPLOAD_TIMEOUT_SEC",
        "BTC15M_CYCLE_GDRIVE_UPLOAD_TIMEOUT_SEC",
        default="600",
    )
)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def resolve_gdrive_oauth_paths() -> tuple[Optional[Path], Optional[Path]]:
    """Return (client_json, token_json) or (None, None) if missing."""
    root = _repo_root()
    client_env = (os.getenv("GDRIVE_OAUTH_PATH") or "").strip()
    token_env = (os.getenv("GDRIVE_CREDENTIALS_PATH") or "").strip()
    candidates_client = [
        Path(client_env) if client_env else None,
        root / "backend" / "data" / "secrets" / "gdrive_oauth_client.json",
        root / ".cursor" / "gcp-oauth.keys.json",
    ]
    candidates_token = [
        Path(token_env) if token_env else None,
        root / "backend" / "data" / "secrets" / "gdrive_oauth_token.json",
        root / ".cursor" / "gdrive-server-credentials.json",
    ]
    client = next((p for p in candidates_client if p is not None and p.is_file()), None)
    token = next((p for p in candidates_token if p is not None and p.is_file()), None)
    if client is None or token is None:
        return None, None
    return client, token


def gdrive_upload_enabled() -> bool:
    raw = _env_first(
        "CYCLE_GDRIVE_UPLOAD", "BTC15M_CYCLE_GDRIVE_UPLOAD", default=""
    ).lower()
    if raw in ("0", "false", "no", "off"):
        return False
    if raw in ("1", "true", "yes", "on"):
        return True
    # Auto: on when credentials are present.
    client, token = resolve_gdrive_oauth_paths()
    return client is not None and token is not None


def _node_bin() -> Optional[str]:
    found = shutil.which("node")
    if found:
        return found
    for candidate in (
        "/usr/bin/node",
        "/usr/local/bin/node",
        "/opt/homebrew/bin/node",
    ):
        if Path(candidate).is_file():
            return candidate
    return None


def upload_cycle_packages(paths: Sequence[Path]) -> bool:
    """
    Upload one or more local ``.tar.xz`` packages to Drive.

    Returns True on success (or nothing to do). False on hard failure.
    Local packaging remains authoritative — callers should log failures, not roll back.
    """
    files: List[Path] = []
    for p in paths:
        if p is None:
            continue
        pp = Path(p)
        if pp.is_file() and pp.name.endswith(".tar.xz"):
            files.append(pp.resolve())
    if not files:
        return True
    if not gdrive_upload_enabled():
        logger.info("gdrive upload skipped (disabled or no credentials)")
        return True

    client, token = resolve_gdrive_oauth_paths()
    if client is None or token is None:
        logger.error("gdrive upload enabled but credentials missing")
        return False

    node = _node_bin()
    if not node:
        logger.error("gdrive upload requires node on PATH")
        return False

    script = _repo_root() / "scripts" / "gdrive" / "upload-backtesting-data.js"
    if not script.is_file():
        logger.error("gdrive upload script missing: %s", script)
        return False

    folder_id = (
        os.getenv("GDRIVE_BACKTESTING_DATA_FOLDER_ID") or _DEFAULT_FOLDER_ID
    ).strip()
    cmd: List[str] = [node, str(script), "--folder-id", folder_id]
    for f in files:
        cmd.extend(["--file", str(f)])

    env = os.environ.copy()
    env["GDRIVE_OAUTH_PATH"] = str(client)
    env["GDRIVE_CREDENTIALS_PATH"] = str(token)
    env["GDRIVE_BACKTESTING_DATA_FOLDER_ID"] = folder_id

    logger.info(
        "gdrive upload starting n=%s folder=%s as creds=%s",
        len(files),
        folder_id,
        token,
    )
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(_repo_root()),
            env=env,
            capture_output=True,
            text=True,
            timeout=_UPLOAD_TIMEOUT_SEC,
            check=False,
        )
    except subprocess.TimeoutExpired:
        logger.error("gdrive upload timed out after %ss", _UPLOAD_TIMEOUT_SEC)
        return False
    except Exception as e:
        logger.exception("gdrive upload failed: %s", e)
        return False

    for line in (proc.stdout or "").splitlines():
        logger.info("gdrive: %s", line)
    for line in (proc.stderr or "").splitlines():
        logger.warning("gdrive stderr: %s", line)

    if proc.returncode != 0:
        logger.error("gdrive upload exited %s", proc.returncode)
        return False
    logger.info("gdrive upload ok (%s file(s))", len(files))
    return True


def upload_cycle_packages_best_effort(paths: Sequence[Path]) -> None:
    """Post-package hook — never raises."""
    try:
        upload_cycle_packages(paths)
    except Exception as e:
        logger.exception("gdrive post-package hook failed: %s", e)
