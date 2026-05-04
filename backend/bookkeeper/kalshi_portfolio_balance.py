"""Fetch Kalshi v2 portfolio balance (cash + positions) using per-user prod credentials."""
from __future__ import annotations

import base64
import time
from pathlib import Path

import requests
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from dotenv import dotenv_values

KALSHI_TRADE_API_V2 = "https://api.elections.kalshi.com/trade-api/v2"


def _sign_request(method: str, path_for_sig: str, timestamp_ms: str, key_path: Path) -> str:
    """RSA-PSS SHA256 signature (same contract as kalshi_account_sync_ws)."""
    with open(key_path, "rb") as key_file:
        private_key = serialization.load_pem_private_key(
            key_file.read(), password=None, backend=default_backend()
        )
    message = f"{timestamp_ms}{method.upper()}{path_for_sig}".encode("utf-8")
    signature = private_key.sign(
        message,
        padding.PSS(
            mgf=padding.MGF1(hashes.SHA256()),
            salt_length=padding.PSS.MAX_LENGTH,
        ),
        hashes.SHA256(),
    )
    return base64.b64encode(signature).decode("utf-8")


def fetch_total_portfolio_cents(user_no: str) -> tuple[int, dict]:
    """
    GET /portfolio/balance; return (cash + portfolio_value) in cents and raw JSON subset.

    Uses ``backend/data/users/user_NNNN/credentials/kalshi-credentials/prod``.
    """
    from backend.util.paths import get_kalshi_credentials_dir

    cred_root = Path(get_kalshi_credentials_dir(user_no)) / "prod"
    env_path = cred_root / ".env"
    pem_path = cred_root / "kalshi.pem"
    env = dotenv_values(env_path) if env_path.is_file() else {}
    key_id = (env.get("KALSHI_API_KEY_ID") or "").strip()
    if not key_id or not pem_path.is_file():
        raise FileNotFoundError(
            f"Kalshi prod credentials missing for user {user_no}: "
            f"need {env_path} with KALSHI_API_KEY_ID and {pem_path}"
        )

    path = "/portfolio/balance"
    path_sig = f"/trade-api/v2{path}"
    url = f"{KALSHI_TRADE_API_V2}{path}"
    ts = str(int(time.time() * 1000))
    sig = _sign_request("GET", path_sig, ts, pem_path)
    headers = {
        "Accept": "application/json",
        "User-Agent": "rec-io-bookkeeper/1.0",
        "KALSHI-ACCESS-KEY": key_id,
        "KALSHI-ACCESS-TIMESTAMP": ts,
        "KALSHI-ACCESS-SIGNATURE": sig,
    }
    resp = requests.get(url, headers=headers, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    cash = int(data.get("balance") or 0)
    pos = int(data.get("portfolio_value") or 0)
    total = cash + pos
    detail = {
        "balance_cents": cash,
        "portfolio_value_cents": pos,
        "total_portfolio_cents": total,
    }
    return total, detail
