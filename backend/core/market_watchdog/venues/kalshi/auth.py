"""Kalshi REST/WS credentials for production ingest."""

from __future__ import annotations

import os
from pathlib import Path


def load_kalshi_credentials_from_disk() -> None:
    if os.getenv("KALSHI_API_KEY_ID", "").strip() and os.getenv("KALSHI_PRIVATE_KEY_PATH", "").strip():
        return
    # parents[4] == backend/ (…/backend/core/market_watchdog/venues/kalshi/auth.py)
    backend_root = Path(__file__).resolve().parents[4]
    cred_dir = (
        backend_root
        / "data"
        / "users"
        / "user_0001"
        / "credentials"
        / "kalshi-credentials"
        / "prod"
    )
    env_path = cred_dir / ".env"
    pem_path = cred_dir / "kalshi.pem"
    if not env_path.is_file() or not pem_path.is_file():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        key, val = s.split("=", 1)
        key, val = key.strip(), val.strip()
        if key == "KALSHI_API_KEY_ID" and val:
            os.environ.setdefault("KALSHI_API_KEY_ID", val)
        elif key == "KALSHI_PRIVATE_KEY_PATH" and val:
            p = Path(val)
            os.environ.setdefault(
                "KALSHI_PRIVATE_KEY_PATH",
                str(p if p.is_absolute() else cred_dir / p),
            )
    if not os.getenv("KALSHI_PRIVATE_KEY_PATH", "").strip():
        os.environ["KALSHI_PRIVATE_KEY_PATH"] = str(pem_path)
