#!/usr/bin/env python3
"""
Check status of Kalshi v1 account/history, deposits, and withdrawals endpoints.
Reports HTTP status and response shape for each. No DB writes.
Run from project root; uses same credentials as scripts/ping_kalshi_v1_account_history.py.
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

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import dotenv_values

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


def get_kalshi_user_id_from_db():
    """Try to read kalshi_user_id from user_info_0001 if DB is available."""
    try:
        from backend.core.config.database import get_postgresql_connection
        conn = get_postgresql_connection()
        if not conn:
            return None
        with conn.cursor() as cur:
            cur.execute("SELECT kalshi_user_id FROM users.user_info_0001 WHERE user_no = '0001' LIMIT 1")
            row = cur.fetchone()
        conn.close()
        return (row[0] or "").strip() if row and row[0] else None
    except Exception:
        return None


def ping(path, params=None, api_key=None, private_key=None):
    """GET path; return (status_code, body_or_error_str). Path must include leading slash."""
    params = params or {}
    timestamp = str(int(time.time() * 1000))
    signature = make_signature(private_key, "GET", path, timestamp)
    headers = {
        "Accept": "application/json",
        "KALSHI-ACCESS-KEY": api_key,
        "KALSHI-ACCESS-TIMESTAMP": timestamp,
        "KALSHI-ACCESS-SIGNATURE": signature,
    }
    url = BASE_URL + path
    try:
        r = requests.get(url, params=params, headers=headers, timeout=15)
        ct = r.headers.get("content-type", "")
        if "application/json" in ct:
            return r.status_code, r.json()
        return r.status_code, r.text
    except Exception as e:
        return None, str(e)


def summarize(body, top_key=None):
    """Return a short summary of response shape for reporting."""
    if body is None or not isinstance(body, dict):
        return str(body)[:200] if body else "(empty)"
    if top_key and top_key in body and isinstance(body[top_key], list):
        arr = body[top_key]
        if not arr:
            return f"{top_key}: [] (0 items)"
        first = arr[0]
        keys = list(first.keys()) if isinstance(first, dict) else type(first).__name__
        return f"{top_key}: {len(arr)} items, first keys: {keys}"
    keys = list(body.keys())
    return f"keys: {keys}"


def main():
    api_key, private_key, mode = load_credentials()
    user_id = get_kalshi_user_id_from_db() or "6d68c23a-0e94-43f5-b290-8faf79481441"
    if not api_key or not private_key:
        print("No Kalshi credentials found. Put prod or demo credentials in backend/data/users/user_0001/credentials/kalshi-credentials/{prod|demo}/")
        sys.exit(1)

    print(f"Base URL: {BASE_URL}")
    print(f"User ID:  {user_id}")
    print(f"Creds:    {mode}")
    print()

    results = []

    # 1. account/history
    path1 = f"/v1/users/{user_id}/account/history"
    params1 = {"deposits": "true", "withdrawals": "true", "page_size": "10", "page_number": "1"}
    status1, body1 = ping(path1, params1, api_key, private_key)
    results.append(("account/history", path1, params1, status1, body1, "entries"))

    # 2. deposits
    path2 = f"/v1/users/{user_id}/deposits"
    params2 = {"page_size": "10", "page_number": "1"}
    status2, body2 = ping(path2, params2, api_key, private_key)
    results.append(("deposits", path2, params2, status2, body2, "deposits"))

    # 3. withdrawals
    path3 = f"/v1/users/{user_id}/withdrawals"
    params3 = {"page_size": "10", "page_number": "1"}
    status3, body3 = ping(path3, params3, api_key, private_key)
    results.append(("withdrawals", path3, params3, status3, body3, "withdrawals"))

    for name, path, params, status, body, top_key in results:
        print(f"--- {name} ---")
        print(f"  Path:   {path}")
        if params:
            print(f"  Params: {params}")
        print(f"  Status: {status}")
        if status == 200 and isinstance(body, dict):
            print(f"  Shape:  {summarize(body, top_key)}")
            if name == "account/history" and "entries" in body and body["entries"]:
                print(f"  First entry keys: {list(body['entries'][0].keys()) if body['entries'] else 'n/a'}")
            if name == "deposits" and "deposits" in body and body["deposits"]:
                print(f"  First deposit keys: {list(body['deposits'][0].keys()) if body['deposits'] else 'n/a'}")
            if name == "withdrawals" and "withdrawals" in body and body["withdrawals"]:
                print(f"  First withdrawal keys: {list(body['withdrawals'][0].keys()) if body['withdrawals'] else 'n/a'}")
        elif isinstance(body, str) and len(body) < 500:
            print(f"  Body:   {body}")
        elif isinstance(body, dict):
            print(f"  Shape:  {summarize(body)}")
        print()

    # Summary line
    statuses = [(r[0], r[3]) for r in results]
    print("Summary:", ", ".join(f"{n}={s}" for n, s in statuses))


if __name__ == "__main__":
    main()
