#!/usr/bin/env python3
"""
Test poll: Kalshi v1 /deposits and /withdrawals (same endpoints as kalshi_account_sync_ws.sync_account_history).

Does not write to the database. For deprecated /account/history see ping_kalshi_v1_account_history.py.
"""
from __future__ import annotations

import base64
import json
import os
import sys
import time
from pathlib import Path

import requests
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from dotenv import dotenv_values

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))

BASE_URL = "https://api.elections.kalshi.com"
USER_NO = (os.environ.get("REC_USER_NO") or "0001").strip().zfill(4)


def load_credentials():
    cred_root = REPO_ROOT / "backend" / "data" / "users" / f"user_{USER_NO}" / "credentials" / "kalshi-credentials"
    for mode in ("prod", "demo"):
        env_path = cred_root / mode / ".env"
        pem_path = cred_root / mode / "kalshi.pem"
        if env_path.exists() and pem_path.exists():
            env = dotenv_values(env_path)
            key_id = env.get("KALSHI_API_KEY_ID")
            if key_id:
                with open(pem_path, "rb") as f:
                    private_key = serialization.load_pem_private_key(
                        f.read(), password=None, backend=default_backend()
                    )
                return key_id, private_key, str(pem_path), mode
    return None, None, None, None


def sign_get(path: str, key_id: str, private_key) -> dict:
    timestamp = str(int(time.time() * 1000))
    message = f"{timestamp}GET{path}".encode("utf-8")
    sig = private_key.sign(
        message,
        padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.MAX_LENGTH),
        hashes.SHA256(),
    )
    signature = base64.b64encode(sig).decode("utf-8")
    return {
        "Accept": "application/json",
        "KALSHI-ACCESS-KEY": key_id,
        "KALSHI-ACCESS-TIMESTAMP": timestamp,
        "KALSHI-ACCESS-SIGNATURE": signature,
    }


def get_kalshi_user_id_from_db():
    kalshi_uid = (os.environ.get("KALSHI_USER_ID") or "").strip()
    if kalshi_uid:
        return kalshi_uid, None
    try:
        from backend.core.config.database import get_system_postgresql_connection

        conn = get_system_postgresql_connection()
        if not conn:
            return None, "No DB connection (set KALSHI_USER_ID or configure DB)"
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
            return None, "kalshi_user_id not set for user_no " + USER_NO
        return (row[0] or "").strip(), None
    except Exception as e:
        return None, str(e)


def fetch_page(label: str, path: str, key_id: str, private_key, page_size: int = 200) -> None:
    url = BASE_URL + path
    params = {"page_size": page_size, "page_number": 1}
    headers = sign_get(path, key_id, private_key)
    r = requests.get(url, params=params, headers=headers, timeout=20)
    print(f"\n=== {label} ===")
    print(f"GET {path}  ->  HTTP {r.status_code}")
    if not r.ok:
        print(r.text[:2000])
        return
    ctype = r.headers.get("content-type", "")
    if "application/json" not in ctype:
        print(r.text[:500])
        return
    data = r.json()
    if label == "deposits":
        items = data.get("deposits") or []
    else:
        items = data.get("withdrawals") or []
    print(f"Count (page 1): {len(items)}")
    if items:
        print("Sample keys:", sorted(items[0].keys()))
        print("First item:", json.dumps(items[0], indent=2, default=str)[:2500])


def main():
    kalshi_user_id, err = get_kalshi_user_id_from_db()
    if err or not kalshi_user_id:
        print(f"Error: {err}")
        sys.exit(1)
    key_id, private_key, _pem, mode = load_credentials()
    if not key_id or not private_key:
        print(f"No credentials under user_{USER_NO} (prod/demo .env + kalshi.pem)")
        sys.exit(1)
    print(f"Kalshi user id: {kalshi_user_id}  (master user_no={USER_NO}, creds={mode})")
    dep_path = f"/v1/users/{kalshi_user_id}/deposits"
    wdr_path = f"/v1/users/{kalshi_user_id}/withdrawals"
    fetch_page("deposits", dep_path, key_id, private_key)
    fetch_page("withdrawals", wdr_path, key_id, private_key)


if __name__ == "__main__":
    main()
