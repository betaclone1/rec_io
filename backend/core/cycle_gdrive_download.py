"""Download cycle packages from Google Drive into the local backtesting_data tree.

Invokes ``scripts/gdrive/download-backtesting-data.js`` with the same OAuth
files as upload. Used when trade-detail candles need a package that is not
cached locally yet.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
from pathlib import Path
from typing import List, Optional, Sequence

from backend.core.cycle_gdrive_upload import resolve_gdrive_oauth_paths
from backend.core.cycle_packager import package_path_for_ticker, package_root

logger = logging.getLogger("cycle_gdrive")

_DEFAULT_FOLDER_ID = "1Jlhz57hSXMYe8Yr_GtIJsaXY0GAW6L1v"


def _env_first(*names: str, default: str = "") -> str:
    for name in names:
        raw = os.getenv(name)
        if raw is not None and str(raw).strip() != "":
            return str(raw).strip()
    return default


_DOWNLOAD_TIMEOUT_SEC = int(
    _env_first(
        "CYCLE_GDRIVE_DOWNLOAD_TIMEOUT_SEC",
        "BTC15M_CYCLE_GDRIVE_DOWNLOAD_TIMEOUT_SEC",
        default="300",
    )
)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


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


def download_cycle_packages(paths: Sequence[Path]) -> bool:
    """
    Ensure each local ``.tar.xz`` package path exists by downloading from Drive.

    Returns True when every path exists after the call (already present or downloaded).
    """
    targets: List[Path] = []
    for p in paths:
        if p is None:
            continue
        pp = Path(p)
        if pp.name.endswith(".tar.xz"):
            targets.append(pp.resolve())
    if not targets:
        return True
    missing = [p for p in targets if not p.is_file()]
    if not missing:
        return True

    client, token = resolve_gdrive_oauth_paths()
    if client is None or token is None:
        logger.error("gdrive download skipped: credentials missing")
        return False

    node = _node_bin()
    if not node:
        logger.error("gdrive download requires node on PATH")
        return False

    script = _repo_root() / "scripts" / "gdrive" / "download-backtesting-data.js"
    if not script.is_file():
        logger.error("gdrive download script missing: %s", script)
        return False

    folder_id = (
        os.getenv("GDRIVE_BACKTESTING_DATA_FOLDER_ID") or _DEFAULT_FOLDER_ID
    ).strip()
    root = package_root()
    cmd: List[str] = [
        node,
        str(script),
        "--folder-id",
        folder_id,
        "--local",
        str(root),
    ]
    for f in missing:
        cmd.extend(["--file", str(f)])

    env = os.environ.copy()
    env["GDRIVE_OAUTH_PATH"] = str(client)
    env["GDRIVE_CREDENTIALS_PATH"] = str(token)
    env["GDRIVE_BACKTESTING_DATA_FOLDER_ID"] = folder_id
    env["CYCLE_PACKAGE_ROOT"] = str(root)

    logger.info(
        "gdrive download starting n=%s folder=%s",
        len(missing),
        folder_id,
    )
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(_repo_root()),
            env=env,
            capture_output=True,
            text=True,
            timeout=_DOWNLOAD_TIMEOUT_SEC,
            check=False,
        )
    except subprocess.TimeoutExpired:
        logger.error("gdrive download timed out after %ss", _DOWNLOAD_TIMEOUT_SEC)
        return False
    except Exception as e:
        logger.exception("gdrive download failed: %s", e)
        return False

    for line in (proc.stdout or "").splitlines():
        logger.info("gdrive: %s", line)
    for line in (proc.stderr or "").splitlines():
        logger.warning("gdrive stderr: %s", line)

    if proc.returncode != 0:
        logger.error("gdrive download exited %s", proc.returncode)
        return all(p.is_file() for p in targets)

    return all(p.is_file() for p in targets)


def ensure_cycle_package_local(market_ticker: str) -> Optional[Path]:
    """
    Return local package path if present or after a successful Drive download.
    """
    found = ensure_cycle_packages_local([market_ticker])
    return found.get(str(market_ticker or "").strip())


def ensure_cycle_packages_local(tickers: Sequence[str]) -> dict[str, Optional[Path]]:
    """
    Resolve each market ticker to a local package path, downloading missing ones in one Drive call.
    """
    wanted: list[tuple[str, Path]] = []
    out: dict[str, Optional[Path]] = {}
    for raw in tickers:
        ticker = str(raw or "").strip()
        if not ticker:
            continue
        path = package_path_for_ticker(ticker)
        if path is None:
            out[ticker] = None
            continue
        wanted.append((ticker, path))
    missing = [path for _ticker, path in wanted if not path.is_file()]
    if missing:
        for path in missing:
            path.parent.mkdir(parents=True, exist_ok=True)
        download_cycle_packages(missing)
    for ticker, path in wanted:
        out[ticker] = path if path.is_file() else None
    return out
