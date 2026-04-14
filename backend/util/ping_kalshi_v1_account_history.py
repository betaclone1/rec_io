#!/usr/bin/env python3
"""
One-off test: ping Kalshi v1 account/history endpoint (deprecated; often 404).
Production sync uses /deposits and /withdrawals only (kalshi_account_sync_ws.py).
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

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))

from dotenv import dotenv_values

USER_NO = "0001"
BASE_URL = "https://api.elections.kalshi.com"


def load_credentials():
    cred_dir = REPO_ROOT / "backend" / "data" / "users" / "user_0001" / "credentials" / "kalshi-credentials"
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


def get_kalshi_user_id_from_db():
    try:
        from backend.core.config.database import get_system_postgresql_connection

        conn = get_system_postgresql_connection()
        if not conn:
            return None, "No DB connection"
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT kalshi_user_id FROM system.master_users
                WHERE LPAD(TRIM(user_no::text), 4, '0') = %s
                LIMIT 1
                """,
                (USER_NO,),
            )
            row = cur.fetchone()
        conn.close()
        if not row or not (row[0] or "").strip():
            return None, "kalshi_user_id not set"
        return (row[0] or "").strip(), None
    except Exception as e:
        return None, str(e)


def main():
    kalshi_user_id, err = get_kalshi_user_id_from_db()
    if err or not kalshi_user_id:
        print(f"Error: {err}")
        sys.exit(1)
    api_key, private_key, mode = load_credentials()
    if not api_key or not private_key:
        print("No credentials")
        sys.exit(1)
    path = f"/v1/users/{kalshi_user_id}/account/history"
    url = BASE_URL + path
    params = {"deposits": "true", "withdrawals": "true", "page_size": "200", "page_number": "1"}
    timestamp = str(int(time.time() * 1000))
    message = f"{timestamp}GET{path}".encode("utf-8")
    sig = private_key.sign(message, padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.MAX_LENGTH), hashes.SHA256())
    signature = base64.b64encode(sig).decode("utf-8")
    headers = {"Accept": "application/json", "KALSHI-ACCESS-KEY": api_key, "KALSHI-ACCESS-TIMESTAMP": timestamp, "KALSHI-ACCESS-SIGNATURE": signature}
    r = requests.get(url, params=params, headers=headers, timeout=15)
    print(f"Status: {r.status_code}")
    if r.ok and "application/json" in r.headers.get("content-type", ""):
        data = r.json()
        entries = data.get("entries") or []
        print(f"Entries: {len(entries)}")
        print(json.dumps(data, indent=2))
    else:
        print(r.text)
        if r.status_code == 404:
            print("(v1 account/history returns 404 on api.elections.kalshi.com; endpoint may be deprecated or path changed)")


if __name__ == "__main__":
    main()
