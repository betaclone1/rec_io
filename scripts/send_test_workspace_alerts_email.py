#!/usr/bin/env python3
"""
Send a one-off test email from the Workspace alerts mailbox (alerts@rec-io.com)
to a master_users email (default: user_no 0001).

Uses the same SMTP stack as registration alerts (backend/util/registration_email.py).

Examples (repo root):

  # Resolve user_0001 email from the DB this process is configured for, then send
  PYTHONPATH=. python3 scripts/send_test_workspace_alerts_email.py --user-no 0001

  # Prod DB from a laptop (see docs/PRODUCTION_HOST.md), then send with local/prod secret file
  export REC_PROD_DB_HOST=165.22.13.146
  export DB_HOST="$REC_PROD_DB_HOST"
  PYTHONPATH=. python3 scripts/send_test_workspace_alerts_email.py --user-no 0001 -v

  # On the production host
  cd /opt/rec_io_server
  PYTHONPATH=. ./venv/bin/python scripts/send_test_workspace_alerts_email.py --user-no 0001

  # Preview only (no SMTP)
  PYTHONPATH=. python3 scripts/send_test_workspace_alerts_email.py --user-no 0001 --dry-run

Credentials: Google app password for alerts@rec-io.com via REC_ALERTS_SMTP_PASSWORD,
REC_ALERTS_SMTP_PASSWORD_FILE, or backend/data/secrets/rec_alerts_smtp_password.txt.
REC_ALERTS_SMTP_USER / FROM default to alerts@rec-io.com for this script (override with env
or --from-addr). The consumer mailbox rec.io.alerts@gmail.com will not authenticate as
alerts@rec-io.com — use an app password created on the Workspace account.
"""

from __future__ import annotations

import argparse
import os
import smtplib
import sys
from datetime import datetime, timezone

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_SCRIPT_DIR)
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

_DEFAULT_FROM = "alerts@rec-io.com"


def _lookup_master_user_email(user_no: str) -> tuple[str, str, str]:
    """Return (user_no, user_id, email) from system.master_users."""
    from backend.core.config.database import get_system_postgresql_connection

    conn = get_system_postgresql_connection()
    if not conn:
        raise RuntimeError("Database unavailable (check DB_* / REC_DB_* / DB_HOST)")
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT user_no, user_id, email
            FROM system.master_users
            WHERE user_no = %s
            LIMIT 1
            """,
            (user_no,),
        )
        row = cur.fetchone()
        if not row:
            raise RuntimeError(f"No system.master_users row for user_no={user_no!r}")
        email = (row[2] or "").strip()
        if not email:
            raise RuntimeError(f"master_users.email is empty for user_no={user_no!r}")
        return str(row[0]), str(row[1] or ""), email
    finally:
        conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Send a Workspace alerts@rec-io.com SMTP test to a master_users email."
    )
    parser.add_argument(
        "--user-no",
        metavar="NNNN",
        default="0001",
        help="Tenant slot to look up in system.master_users (default: 0001)",
    )
    parser.add_argument(
        "--to",
        dest="to_email",
        default="",
        help="Override recipient (skip DB lookup)",
    )
    parser.add_argument(
        "--from-addr",
        default=(os.getenv("REC_ALERTS_SMTP_FROM") or _DEFAULT_FROM).strip(),
        help=f"From / SMTP login mailbox (default: {_DEFAULT_FROM})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print resolved From/To and exit without sending",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Print SMTP config (password length only, never the secret)",
    )
    args = parser.parse_args()

    user_no = str(args.user_no or "").strip()
    if len(user_no) != 4 or not user_no.isdigit():
        print(f"Invalid --user-no {user_no!r} (expected 4 digits)", file=sys.stderr)
        return 2

    from_addr = (args.from_addr or _DEFAULT_FROM).strip()
    if not from_addr:
        print("--from-addr is empty", file=sys.stderr)
        return 2

    # This smoke test authenticates and sends as the Workspace mailbox.
    os.environ["REC_ALERTS_SMTP_USER"] = from_addr
    os.environ["REC_ALERTS_SMTP_FROM"] = from_addr

    to_email = (args.to_email or "").strip()
    user_id = ""
    if to_email:
        resolved_user_no = user_no
    else:
        resolved_user_no, user_id, to_email = _lookup_master_user_email(user_no)

    from backend.util.registration_email import (  # noqa: E402
        _default_smtp_password_file_path,
        _smtp_config,
        send_plaintext_alerts_email,
    )

    host, port, user, password, cfg_from = _smtp_config()
    if args.verbose or args.dry_run:
        path = _default_smtp_password_file_path()
        print(
            f"user_no={resolved_user_no!r} user_id={user_id!r} to={to_email!r}",
            file=sys.stderr,
        )
        print(
            f"SMTP host={host!r} port={port} user={user!r} from={cfg_from!r}",
            file=sys.stderr,
        )
        print(
            f"Default secrets file: {path!r} exists={os.path.isfile(path)}",
            file=sys.stderr,
        )
        print(
            f"Resolved app-password length: {len(password)} (expect 16 for Google)",
            file=sys.stderr,
        )

    if args.dry_run:
        print("Dry run — not sending.")
        return 0

    if not password:
        print(
            "SMTP password missing: set REC_ALERTS_SMTP_PASSWORD, "
            "REC_ALERTS_SMTP_PASSWORD_FILE, or "
            "backend/data/secrets/rec_alerts_smtp_password.txt "
            f"(app password for {from_addr}).",
            file=sys.stderr,
        )
        return 1

    subject = "rec.io alerts — Workspace SMTP test"
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    body = (
        "This is a test message from scripts/send_test_workspace_alerts_email.py.\n\n"
        f"From: {cfg_from}\n"
        f"To:   {to_email}\n"
        f"User: {resolved_user_no}"
        + (f" ({user_id})" if user_id else "")
        + f"\nSent: {now}\n\n"
        "If you received this, alerts@rec-io.com SMTP credentials are working.\n"
    )

    try:
        send_plaintext_alerts_email(to_email, subject, body)
    except smtplib.SMTPAuthenticationError as e:
        print("Google rejected SMTP login.", file=sys.stderr)
        print(e, file=sys.stderr)
        print(
            f"Create an App password for {from_addr} (Google Workspace account), "
            "put the 16 characters in backend/data/secrets/rec_alerts_smtp_password.txt "
            "(or REC_ALERTS_SMTP_PASSWORD_FILE). "
            "REC_ALERTS_SMTP_USER must be that same mailbox.",
            file=sys.stderr,
        )
        return 1
    except Exception as e:
        print(f"Failed: {e}", file=sys.stderr)
        return 1

    print(f"Sent test email from {cfg_from!r} to {to_email!r} (user_no={resolved_user_no})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
