"""Kalshi Trade API WebSocket authentication headers (same signing as REST WS docs)."""

from __future__ import annotations

import base64
import time
from pathlib import Path

from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding


WS_URL_PATH = "/trade-api/ws/v2"


def load_kalshi_ws_credentials():
    """Return (api_key_id: str, private_key_path: Path) using account_mode + kalshi credentials dir."""
    from backend.account_mode import get_account_mode
    from backend.util.paths import get_kalshi_credentials_dir
    from dotenv import dotenv_values

    mode = get_account_mode()
    cred_dir = Path(get_kalshi_credentials_dir()) / mode
    env = dotenv_values(cred_dir / ".env")
    key_id = env.get("KALSHI_API_KEY_ID")
    pem = cred_dir / "kalshi.pem"
    if not key_id or not pem.is_file():
        raise FileNotFoundError(f"Kalshi WS credentials missing under {cred_dir}")
    return key_id, pem


def generate_kalshi_ws_signature(private_key_path: Path, timestamp_ms: str) -> str:
    signature_text = timestamp_ms + "GET" + WS_URL_PATH
    with open(private_key_path, "rb") as f:
        private_key = serialization.load_pem_private_key(
            f.read(), password=None, backend=default_backend()
        )
    signature = private_key.sign(
        signature_text.encode("utf-8"),
        padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.MAX_LENGTH),
        hashes.SHA256(),
    )
    return base64.b64encode(signature).decode("utf-8")


def kalshi_ws_connect_headers() -> dict:
    """Headers for websockets.connect(..., additional_headers=...)."""
    key_id, pem = load_kalshi_ws_credentials()
    ts = str(int(time.time() * 1000))
    sig = generate_kalshi_ws_signature(pem, ts)
    return {
        "KALSHI-ACCESS-KEY": key_id,
        "KALSHI-ACCESS-TIMESTAMP": ts,
        "KALSHI-ACCESS-SIGNATURE": sig,
    }
