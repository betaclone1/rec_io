#!/usr/bin/env python3
"""
Verify QuickBooks Online connectivity: refresh OAuth access token and GET CompanyInfo.

Expects the same per-user quickbooks .env as quickbooks_oauth_authorize.py (after OAuth).

Run from repo root:
  REC_USER_NO=0001 ./venv/bin/python scripts/diagnostics/quickbooks_read_smoke.py
  REC_USER_NO=0001 ./venv/bin/python scripts/diagnostics/quickbooks_read_smoke.py --chart-of-accounts
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from backend.bookkeeper.quickbooks import (
    get_chart_of_accounts,
    get_company_info,
    load_qbo_config,
    refresh_access_token,
)
from backend.util.paths import get_quickbooks_credentials_dir


def _company_name(payload: dict) -> str | None:
    info = payload.get("CompanyInfo")
    if isinstance(info, list) and info:
        info = info[0]
    if isinstance(info, dict):
        return info.get("CompanyName") or info.get("LegalName")
    try:
        qr = payload.get("QueryResponse") or {}
        infos = qr.get("CompanyInfo")
        if isinstance(infos, list) and infos:
            row = infos[0]
            return row.get("CompanyName") or row.get("LegalName")
    except (AttributeError, KeyError, TypeError):
        pass
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description="QBO read smoke test (CompanyInfo).")
    parser.add_argument(
        "--credentials-dir",
        default=None,
        help="Override quickbooks credentials directory",
    )
    parser.add_argument(
        "--dump-json",
        action="store_true",
        help="Print full CompanyInfo JSON response",
    )
    parser.add_argument(
        "--chart-of-accounts",
        action="store_true",
        help="List chart of accounts (Account query) after CompanyInfo check",
    )
    args = parser.parse_args()
    cred_dir = Path(args.credentials_dir or get_quickbooks_credentials_dir())
    try:
        cfg = load_qbo_config(cred_dir)
    except (FileNotFoundError, ValueError) as e:
        print(e, file=sys.stderr)
        return 1

    try:
        tok = refresh_access_token(
            cfg.client_id, cfg.client_secret, cfg.refresh_token
        )
    except RuntimeError as e:
        print(e, file=sys.stderr)
        return 1

    access = tok.get("access_token")
    if not access:
        print("No access_token in refresh response:", tok, file=sys.stderr)
        return 1
    new_refresh = tok.get("refresh_token")
    if new_refresh and new_refresh != cfg.refresh_token:
        print(
            "Note: Intuit returned a new refresh_token. Update INTUIT_REFRESH_TOKEN in:\n"
            f"  {cred_dir / '.env'}\n",
            file=sys.stderr,
        )

    try:
        company = get_company_info(cfg, access)
    except RuntimeError as e:
        print(e, file=sys.stderr)
        return 1

    name = _company_name(company)
    print("QBO read OK.")
    print(f"  Environment: {cfg.environment}")
    print(f"  Realm ID:    {cfg.realm_id}")
    if name:
        print(f"  Company:     {name}")
    if args.dump_json:
        print(json.dumps(company, indent=2))

    if args.chart_of_accounts:
        rows = get_chart_of_accounts(cfg, access)
        print(f"\nChart of accounts ({len(rows)} accounts):")
        for row in rows:
            fq = row.get("FullyQualifiedName") or row.get("Name")
            at = row.get("AccountType")
            bal = row.get("CurrentBalance")
            aid = row.get("Id")
            print(f"  [{aid}] {fq}  ({at})  balance={bal}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
