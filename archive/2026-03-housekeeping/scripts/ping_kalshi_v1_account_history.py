#!/usr/bin/env python3
"""
One-off: ping Kalshi v1 account/history endpoint to see what data comes back.
Endpoint from community: v1/users/{userId}/account/history with deposits, withdrawals, page_size, page_number.
"""
import base64
import json
import sys
import time
from pathlib import Path

import requests
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

# Project root and credentials
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import dotenv_values

USER_ID = "6d68c23a-0e94-43f5-b290-8faf79481441"

# v1 lives on elections API (trading-api.kalshi.com redirects to it)
BASE_URL = "https://api.elections.kalshi.com"


def load_credentials():
    cred_dir = ROOT / "backend" / "data" / "users" / "user_0001" / "credentials" / "kalshi-credentials"
    for mode in ("prod", "demo"):
        env_path = cred_dir / mode / ".env"
        pem_path = cred_dir / mode / "kalshi.pem"
        if env_path.exists() and pem_path.exists():
            env = dotenv_values(env_path)
            key_id = env.get("KALSHI_API_KEY_ID")
            if key_id:
                with open(pem_path, "rb") as f:
                    private_key = serialization.load_pem_private_key(
                        f.read(), password=None, backend=default_backend()
                    )
                return key_id, private_key, mode
    return None, None, None


def make_signature(private_key, method, path, timestamp):
    message = f"{timestamp}{method.upper()}{path}".encode("utf-8")
    sig = private_key.sign(
        message,
        padding.PSS(
            mgf=padding.MGF1(hashes.SHA256()),
            salt_length=padding.PSS.MAX_LENGTH,
        ),
        hashes.SHA256(),
    )
    return base64.b64encode(sig).decode("utf-8")


def main():
    api_key, private_key, mode = load_credentials()
    path = f"/v1/users/{USER_ID}/account/history"
    params = {
        "deposits": "true",
        "withdrawals": "true",
        "page_size": "200",
        "page_number": "1",
    }

    print(f"User ID: {USER_ID}")
    print(f"Path: {path}")
    print(f"Params: {params}")
    print(f"Credentials: {'loaded' if api_key else 'missing'} ({mode or 'none'})")
    print()

    url = BASE_URL + path
    print(f"GET {url}")
    print()

    # Try with v2-style signed headers (path without query for signing)
    if api_key and private_key:
        timestamp = str(int(time.time() * 1000))
        signature = make_signature(private_key, "GET", path, timestamp)
        headers = {
            "Accept": "application/json",
            "KALSHI-ACCESS-KEY": api_key,
            "KALSHI-ACCESS-TIMESTAMP": timestamp,
            "KALSHI-ACCESS-SIGNATURE": signature,
        }
        try:
            r = requests.get(url, params=params, headers=headers, timeout=15)
            print(f"Status: {r.status_code}")
            ct = r.headers.get("content-type", "")
            if "application/json" in ct:
                body = r.json()
                print(json.dumps(body, indent=2))
            else:
                print(r.text)
        except Exception as e:
            print(f"Error: {e}")
    else:
        print("No API key or private key; run with prod/demo credentials in place.")


if __name__ == "__main__":
    main()
