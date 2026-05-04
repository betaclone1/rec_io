#!/usr/bin/env python3
"""
One-time QuickBooks Online OAuth 2.0 authorization: opens a local redirect handler,
exchanges the auth code for refresh/access tokens, and prints .env lines to save.

Prerequisites (Intuit Developer):
  - Create an app at https://developer.intuit.com/
  - Add a Redirect URI that matches --redirect-uri (default http://127.0.0.1:8080/callback)
  - Put INTUIT_CLIENT_ID and INTUIT_CLIENT_SECRET in your quickbooks .env (see below)

Credentials file (per REC_USER_NO, default user_0001):
  backend/data/users/user_NNNN/credentials/quickbooks/.env

Required before running:
  INTUIT_CLIENT_ID=...
  INTUIT_CLIENT_SECRET=...

After success, append the printed lines (INTUIT_REFRESH_TOKEN, QBO_REALM_ID, QBO_ENVIRONMENT).

Run from repo root:
  REC_USER_NO=0001 ./venv/bin/python scripts/diagnostics/quickbooks_oauth_authorize.py
"""
from __future__ import annotations

import argparse
import secrets
import sys
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from dotenv import dotenv_values

from backend.bookkeeper.quickbooks import (
    SCOPE_ACCOUNTING,
    build_authorization_url,
    exchange_authorization_code,
)
from backend.util.paths import get_quickbooks_credentials_dir


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="QuickBooks OAuth browser flow (one-time).")
    p.add_argument(
        "--host",
        default="127.0.0.1",
        help="Callback bind address (default 127.0.0.1)",
    )
    p.add_argument(
        "--port",
        type=int,
        default=8080,
        help="Callback port (default 8080)",
    )
    p.add_argument(
        "--redirect-uri",
        default=None,
        help="Must match Intuit app redirect URI exactly (default http://HOST:PORT/callback)",
    )
    p.add_argument(
        "--credentials-dir",
        default=None,
        help="Override quickbooks credentials directory",
    )
    p.add_argument(
        "--environment",
        choices=("sandbox", "production"),
        default="sandbox",
        help="QBO company environment you are connecting (default sandbox)",
    )
    return p.parse_args()


def main() -> int:
    args = _parse_args()
    cred_root = Path(args.credentials_dir or get_quickbooks_credentials_dir())
    cred_root.mkdir(parents=True, exist_ok=True)
    env_path = cred_root / ".env"
    env = dotenv_values(env_path) if env_path.is_file() else {}
    client_id = (env.get("INTUIT_CLIENT_ID") or "").strip()
    client_secret = (env.get("INTUIT_CLIENT_SECRET") or "").strip()
    if not client_id or not client_secret:
        print(
            f"Add INTUIT_CLIENT_ID and INTUIT_CLIENT_SECRET to:\n  {env_path}\n"
            "Then re-run this script.",
            file=sys.stderr,
        )
        return 1

    redirect_uri = args.redirect_uri or f"http://{args.host}:{args.port}/callback"
    state = secrets.token_urlsafe(24)
    auth_url = build_authorization_url(client_id, redirect_uri, state)

    received: dict[str, str | None] = {
        "code": None,
        "realm_id": None,
        "error": None,
    }

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            parsed = urllib.parse.urlparse(self.path)
            if parsed.path != "/callback":
                self.send_error(404, "Not Found")
                return
            qs = urllib.parse.parse_qs(parsed.query)
            if qs.get("error"):
                err = qs.get("error_description", qs["error"])
                received["error"] = err[0] if err else "unknown_error"
                self._ok_html("Authorization declined or failed. Check the terminal.")
                return
            if (qs.get("state") or [None])[0] != state:
                received["error"] = "state_mismatch"
                self._ok_html("State mismatch. Close this tab and run the script again.")
                return
            received["code"] = (qs.get("code") or [None])[0]
            received["realm_id"] = (qs.get("realmId") or [None])[0]
            self._ok_html(
                "QuickBooks authorization received. You can close this tab."
            )

        def _ok_html(self, message: str) -> None:
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(
                f"<html><body><p>{message}</p></body></html>".encode("utf-8")
            )

        def log_message(self, format: str, *args: object) -> None:
            return

    print("Scope:", SCOPE_ACCOUNTING)
    print("Open this URL in a browser (logged into the right Intuit / QBO company):\n")
    print(auth_url)
    print(f"\nWaiting for redirect to {redirect_uri} ...\n")

    server = HTTPServer((args.host, args.port), Handler)
    server.timeout = 30
    # Browsers may hit /favicon.ico first; keep accepting until /callback arrives.
    for _ in range(128):
        server.handle_request()
        if received["code"] or received["error"]:
            break
    else:
        print("Timed out waiting for OAuth redirect.", file=sys.stderr)
        return 1

    if received["error"]:
        print("OAuth error:", received["error"], file=sys.stderr)
        return 1
    code = received["code"]
    realm = received["realm_id"]
    if not code or not realm:
        print("Missing code or realmId in callback.", file=sys.stderr)
        return 1

    try:
        tokens = exchange_authorization_code(
            client_id, client_secret, code, redirect_uri
        )
    except RuntimeError as e:
        print(e, file=sys.stderr)
        return 1

    refresh = tokens.get("refresh_token") or ""
    if not refresh:
        print("No refresh_token in token response:", tokens, file=sys.stderr)
        return 1

    print("--- Add or merge these into your QuickBooks .env ---\n")
    print(f"QBO_ENVIRONMENT={args.environment}")
    print(f"QBO_REALM_ID={realm}")
    print(f"INTUIT_REFRESH_TOKEN={refresh}")
    print("\n(Intuit may also return a new refresh_token on later refreshes; keep .env updated.)")
    print(f"\nFile: {env_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
