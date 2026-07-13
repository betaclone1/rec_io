#!/usr/bin/env python3
"""
One-time OAuth setup for Gmail API alerts (HTTPS — works on DigitalOcean).

Requires a Google Cloud OAuth Desktop client for alerts@rec-io.com.

  PYTHONPATH=. python3 scripts/setup_gmail_api_alerts_oauth.py \\
    --client-secrets /path/to/client_secret.json

Writes: backend/data/secrets/rec_alerts_gmail_oauth.json (mode 600)

See docs/REC_ALERTS_SMTP_SECRETS.md for the Google Cloud console steps.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer

import requests

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_SCRIPT_DIR)
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

_SCOPE = "https://www.googleapis.com/auth/gmail.send"
_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
_TOKEN_URL = "https://oauth2.googleapis.com/token"
_REDIRECT = "http://127.0.0.1:8765/oauth2callback"


def _load_client_secrets(path: str) -> tuple[str, str]:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    block = data.get("installed") or data.get("web") or data
    client_id = str(block.get("client_id") or "").strip()
    client_secret = str(block.get("client_secret") or "").strip()
    if not client_id or not client_secret:
        raise SystemExit(f"Could not find client_id/client_secret in {path}")
    return client_id, client_secret


def main() -> int:
    parser = argparse.ArgumentParser(description="Authorize Gmail API for rec.io alerts.")
    parser.add_argument(
        "--client-secrets",
        required=True,
        help="Path to Google Cloud OAuth client JSON (Desktop app)",
    )
    parser.add_argument(
        "--out",
        default="",
        help="Output path (default: backend/data/secrets/rec_alerts_gmail_oauth.json)",
    )
    args = parser.parse_args()

    from backend.util.registration_email import _default_gmail_oauth_file_path

    out_path = (args.out or "").strip() or _default_gmail_oauth_file_path()
    client_id, client_secret = _load_client_secrets(args.client_secrets)

    auth_qs = urllib.parse.urlencode(
        {
            "client_id": client_id,
            "redirect_uri": _REDIRECT,
            "response_type": "code",
            "scope": _SCOPE,
            "access_type": "offline",
            "prompt": "consent",
            "include_granted_scopes": "true",
        }
    )
    auth_url = f"{_AUTH_URL}?{auth_qs}"

    result: dict[str, str] = {}
    error_holder: dict[str, str] = {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            parsed = urllib.parse.urlparse(self.path)
            if parsed.path != "/oauth2callback":
                self.send_response(404)
                self.end_headers()
                return
            qs = urllib.parse.parse_qs(parsed.query)
            if qs.get("error"):
                error_holder["error"] = qs["error"][0]
                body = b"Authorization failed. You can close this tab."
            else:
                result["code"] = (qs.get("code") or [""])[0]
                body = b"Authorization OK. You can close this tab and return to the terminal."
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:  # noqa: A003
            return

    server = HTTPServer(("127.0.0.1", 8765), Handler)
    thread = threading.Thread(target=server.handle_request, daemon=True)
    thread.start()

    print("Opening browser for Google OAuth.")
    print("Sign in as alerts@rec-io.com and approve gmail.send.")
    print(auth_url)
    try:
        webbrowser.open(auth_url)
    except Exception:
        pass

    thread.join(timeout=300)
    server.server_close()

    if error_holder.get("error"):
        print(f"OAuth error: {error_holder['error']}", file=sys.stderr)
        return 1
    code = (result.get("code") or "").strip()
    if not code:
        print("No authorization code received (timeout or browser closed).", file=sys.stderr)
        return 1

    token_resp = requests.post(
        _TOKEN_URL,
        data={
            "code": code,
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": _REDIRECT,
            "grant_type": "authorization_code",
        },
        timeout=30,
    )
    if token_resp.status_code >= 400:
        print(f"Token exchange failed: {token_resp.status_code} {token_resp.text}", file=sys.stderr)
        return 1
    tokens = token_resp.json()
    refresh = str(tokens.get("refresh_token") or "").strip()
    if not refresh:
        print(
            "No refresh_token returned. Revoke prior grants for this client at "
            "https://myaccount.google.com/permissions then re-run with prompt=consent.",
            file=sys.stderr,
        )
        return 1

    payload = {
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": refresh,
        "token_uri": _TOKEN_URL,
        "scopes": [_SCOPE],
        "mailbox": "alerts@rec-io.com",
    }
    os.makedirs(os.path.dirname(out_path), mode=0o700, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
        f.write("\n")
    os.chmod(out_path, 0o600)
    print(f"Wrote {out_path}")
    print("Copy this file to prod (same path under /opt/rec_io_server) and restart monitor_manager / main_app.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
