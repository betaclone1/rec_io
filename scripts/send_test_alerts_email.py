#!/usr/bin/env python3
"""
Send a test email using REC_ALERTS SMTP (same config as registration verification).

From repo root:
  PYTHONPATH=. python3 scripts/send_test_alerts_email.py you@example.com

Optional recipient default: REC_ALERTS_TEST_TO environment variable.

Credentials (same as backend/util/registration_email.py):
  REC_ALERTS_SMTP_PASSWORD, REC_ALERTS_SMTP_PASSWORD_FILE, or
  backend/data/secrets/rec_alerts_smtp_password.txt
"""

from __future__ import annotations

import argparse
import os
import smtplib
import sys

# Repo root on path
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_SCRIPT_DIR)
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from backend.util.registration_email import (  # noqa: E402
    _default_smtp_password_file_path,
    _smtp_config,
    send_alerts_smtp_test_email,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Send REC_ALERTS SMTP test email.")
    parser.add_argument(
        "to_email",
        nargs="?",
        default=(os.getenv("REC_ALERTS_TEST_TO") or "").strip(),
        help="Recipient address (or set REC_ALERTS_TEST_TO)",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Print where credentials are loaded from (password length only, never the secret)",
    )
    args = parser.parse_args()
    if not args.to_email:
        print(
            "Usage: PYTHONPATH=. python3 scripts/send_test_alerts_email.py <to_email>\n"
            "   or: export REC_ALERTS_TEST_TO=you@example.com && PYTHONPATH=. python3 scripts/send_test_alerts_email.py",
            file=sys.stderr,
        )
        return 2
    if args.verbose:
        path = _default_smtp_password_file_path()
        host, port, user, password, from_addr = _smtp_config()
        print(f"SMTP host={host!r} port={port} user={user!r} from={from_addr!r}", file=sys.stderr)
        print(f"Default secrets file: {path!r} exists={os.path.isfile(path)}", file=sys.stderr)
        print(f"Resolved app-password length: {len(password)} (expect 16 for Gmail)", file=sys.stderr)
    try:
        send_alerts_smtp_test_email(args.to_email)
    except smtplib.SMTPAuthenticationError as e:
        print("Gmail rejected SMTP login.", file=sys.stderr)
        print(e, file=sys.stderr)
        print(
            "Use an App password (not your Google account password): "
            "https://myaccount.google.com/apppasswords — then put the 16 characters in "
            "backend/data/secrets/rec_alerts_smtp_password.txt (one line; spaces OK). "
            "REC_ALERTS_SMTP_USER must be the same mailbox that created the app password.",
            file=sys.stderr,
        )
        return 1
    except Exception as e:
        print(f"Failed: {e}", file=sys.stderr)
        return 1
    print(f"Sent test email to {args.to_email!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
