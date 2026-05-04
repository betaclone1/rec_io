#!/usr/bin/env python3
"""
Per-tenant QuickBooks Online bookkeeper: OAuth, chart of accounts, transfers,
Kalshi vs QBO reconciliation journal entries.

Credentials:
  QuickBooks: backend/data/users/user_NNNN/credentials/quickbooks/.env
  Kalshi:     backend/data/users/user_NNNN/credentials/kalshi-credentials/prod

Run from repo root:
  ./venv/bin/python -m backend.bookkeeper.bookkeeper
  ./venv/bin/python -m backend.bookkeeper.bookkeeper --user-no 0001 --json
  ./venv/bin/python -m backend.bookkeeper.bookkeeper --user-no 0001 --transfer-from Checking \\
    --transfer-to "Kalshi Trading Account" --amount 1000
  ./venv/bin/python -m backend.bookkeeper.bookkeeper --user-no 0001 --reconcile-kalshi --reconcile-dry-run
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import date
from typing import Any

from backend.bookkeeper.kalshi_portfolio_balance import fetch_total_portfolio_cents
from backend.bookkeeper.quickbooks import (
    QboConfig,
    create_journal_entry_two_line,
    create_transfer,
    get_chart_of_accounts,
    load_qbo_config,
    refresh_access_token,
)
from backend.core.tenant_script_args import add_user_no_argument, resolve_user_no
from backend.util.paths import get_quickbooks_credentials_dir

logger = logging.getLogger(__name__)


def qbo_connect(user_no: str) -> tuple[QboConfig, str, dict[str, Any]]:
    """
    Load .env, refresh access token. Returns (QboConfig, access_token, meta).

    meta: user_no, credentials_dir, realm_id, environment.
    """
    cred_dir = get_quickbooks_credentials_dir(user_no)
    cfg = load_qbo_config(cred_dir)
    meta: dict[str, Any] = {
        "user_no": user_no,
        "credentials_dir": cred_dir,
        "realm_id": cfg.realm_id,
        "environment": cfg.environment,
    }
    logger.info(
        "QuickBooks: refreshing token (user=%s env=%s realm=%s)",
        user_no,
        cfg.environment,
        cfg.realm_id,
    )
    tok = refresh_access_token(
        cfg.client_id, cfg.client_secret, cfg.refresh_token
    )
    access = tok.get("access_token")
    if not access:
        raise RuntimeError(f"No access_token in refresh response: {tok}")
    new_refresh = tok.get("refresh_token")
    if new_refresh and new_refresh != cfg.refresh_token:
        logger.warning(
            "Intuit returned a new refresh_token; update INTUIT_REFRESH_TOKEN in %s/.env",
            cred_dir,
        )
    return cfg, access, meta


def fetch_chart_of_accounts(user_no: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Refresh OAuth and return chart of accounts + meta with account_count."""
    cfg, access, meta = qbo_connect(user_no)
    accounts = get_chart_of_accounts(cfg, access)
    meta["account_count"] = len(accounts)
    return accounts, meta


def account_id_by_exact_name(accounts: list[dict[str, Any]], label: str) -> str | None:
    """Match Account ``Name`` then ``FullyQualifiedName`` (case-insensitive)."""
    lf = label.strip().casefold()
    for a in accounts:
        if (a.get("Name") or "").strip().casefold() == lf:
            i = a.get("Id")
            return str(i) if i is not None else None
    for a in accounts:
        fq = (a.get("FullyQualifiedName") or "").strip()
        if fq.casefold() == lf:
            i = a.get("Id")
            return str(i) if i is not None else None
    return None


def _current_balance_float(account_row: dict[str, Any] | None) -> float:
    if not account_row:
        return 0.0
    v = account_row.get("CurrentBalance")
    if v is None:
        return 0.0
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _account_row_by_id(
    accounts: list[dict[str, Any]], account_id: str
) -> dict[str, Any] | None:
    for a in accounts:
        if str(a.get("Id")) == str(account_id):
            return a
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Rec IO bookkeeper: QuickBooks Online (chart, transfers, Kalshi reconcile).",
    )
    add_user_no_argument(parser)
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Log to stderr at INFO.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print JSON {meta, accounts} to stdout (chart mode only).",
    )
    parser.add_argument(
        "--pretty-json",
        action="store_true",
        help="With --json, indent output (default: compact).",
    )
    parser.add_argument(
        "--reconcile-kalshi",
        action="store_true",
        help=(
            "Compare Kalshi API total portfolio (cash + positions) to QBO Kalshi Trading Account; "
            "post a balancing journal entry when they differ."
        ),
    )
    parser.add_argument(
        "--reconcile-dry-run",
        action="store_true",
        help="With --reconcile-kalshi, print analysis only (no journal entry).",
    )
    parser.add_argument(
        "--kalshi-account",
        default="Kalshi Trading Account",
        metavar="NAME",
        help="QBO asset account name to compare (default: Kalshi Trading Account).",
    )
    parser.add_argument(
        "--trading-income-account",
        default="Trading Income",
        metavar="NAME",
        help="QBO income account for P/L side (default: Trading Income).",
    )
    parser.add_argument(
        "--min-diff",
        type=float,
        default=0.01,
        metavar="DOLLARS",
        help="Skip posting if absolute gap is below this (default: 0.01).",
    )
    parser.add_argument(
        "--transfer-from",
        metavar="NAME",
        default=None,
        help="Account Name (or FullyQualifiedName) to transfer money from.",
    )
    parser.add_argument(
        "--transfer-to",
        metavar="NAME",
        default=None,
        help="Account Name (or FullyQualifiedName) to transfer money to.",
    )
    parser.add_argument(
        "--amount",
        type=float,
        default=None,
        help="Transfer amount (positive number). Requires --transfer-from and --transfer-to.",
    )
    parser.add_argument(
        "--txn-date",
        dest="txn_date",
        metavar="YYYY-MM-DD",
        default=None,
        help="Transaction date for transfer or journal (default: today local date).",
    )
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )

    user_no = resolve_user_no(args)

    transfer_requested = (
        args.transfer_from is not None
        or args.transfer_to is not None
        or args.amount is not None
    )
    if args.reconcile_kalshi and transfer_requested:
        parser.error("Use either --reconcile-kalshi or transfer options, not both.")

    if args.reconcile_kalshi:
        try:
            kalshi_cents, ks_detail = fetch_total_portfolio_cents(user_no)
            kalshi_dollars = kalshi_cents / 100.0
            cfg, access, meta = qbo_connect(user_no)
            accounts = get_chart_of_accounts(cfg, access)
            kalshi_aid = account_id_by_exact_name(accounts, args.kalshi_account)
            income_aid = account_id_by_exact_name(accounts, args.trading_income_account)
            if not kalshi_aid:
                logger.error("Unknown QBO account: %r", args.kalshi_account)
                return 1
            if not income_aid:
                logger.error("Unknown QBO account: %r", args.trading_income_account)
                return 1
            kalshi_row = _account_row_by_id(accounts, kalshi_aid)
            qb_kalshi_bal = _current_balance_float(kalshi_row)
            diff = round(qb_kalshi_bal - kalshi_dollars, 2)
        except (FileNotFoundError, ValueError, RuntimeError, OSError) as e:
            logger.error("%s", e)
            return 1

        print(
            f"Kalshi vs QuickBooks — user {user_no} | {meta['environment']} | realm {meta['realm_id']}"
        )
        print(
            f"  Kalshi total portfolio: ${kalshi_dollars:.2f} "
            f"(cash ${ks_detail['balance_cents']/100:.2f} + "
            f"positions ${ks_detail['portfolio_value_cents']/100:.2f})"
        )
        print(
            f"  QBO [{args.kalshi_account}] CurrentBalance: ${qb_kalshi_bal:.2f}"
        )
        print(f"  Gap (QB − Kalshi): ${diff:.2f}")

        ad = abs(diff)
        if ad < args.min_diff:
            print(
                f"Within min-diff ({args.min_diff}); no journal entry needed."
            )
            return 0

        amt = round(ad, 2)
        txn_date = args.txn_date or date.today().isoformat()

        if diff > 0:
            # QB higher than Kalshi → realized losses: Debit Trading Income, Credit Kalshi asset
            debit_id, credit_id = income_aid, kalshi_aid
            scenario = "QB > Kalshi (loss): Debit Trading Income, Credit Kalshi Trading Account"
            note = (
                "Rec IO bookkeeper: reconcile Kalshi — QB Kalshi balance exceeds Kalshi portfolio "
                f"(gap ${amt:.2f})"
            )
        else:
            # QB lower than Kalshi → realized profits: Debit Kalshi, Credit Trading Income
            debit_id, credit_id = kalshi_aid, income_aid
            scenario = "QB < Kalshi (gain): Debit Kalshi Trading Account, Credit Trading Income"
            note = (
                "Rec IO bookkeeper: reconcile Kalshi — Kalshi portfolio exceeds QB Kalshi balance "
                f"(gap ${amt:.2f})"
            )

        print(f"  Entry: {scenario}")
        print(f"  Amount: ${amt:.2f}  TxnDate {txn_date}")

        if args.reconcile_dry_run:
            print("(dry-run: no JournalEntry POST)")
            return 0

        try:
            result = create_journal_entry_two_line(
                cfg,
                access,
                txn_date=txn_date,
                private_note=note,
                amount=amt,
                debit_account_id=debit_id,
                credit_account_id=credit_id,
            )
        except (RuntimeError, ValueError) as e:
            logger.error("%s", e)
            return 1

        je = result.get("JournalEntry") or result
        je_id = je.get("Id")
        sync = je.get("SyncToken")
        print(
            f"JournalEntry created — Id={je_id} SyncToken={sync}"
        )
        if args.json:
            print(json.dumps(result, indent=2 if args.pretty_json else None))
        return 0

    if transfer_requested:
        if args.transfer_from is None or args.transfer_to is None or args.amount is None:
            parser.error(
                "Transfer requires all of: --transfer-from, --transfer-to, --amount"
            )
        if args.amount <= 0:
            parser.error("--amount must be positive")

        try:
            cfg, access, meta = qbo_connect(user_no)
            accounts = get_chart_of_accounts(cfg, access)
            fid = account_id_by_exact_name(accounts, args.transfer_from)
            tid = account_id_by_exact_name(accounts, args.transfer_to)
            if not fid:
                logger.error("Unknown from-account: %r", args.transfer_from)
                return 1
            if not tid:
                logger.error("Unknown to-account: %r", args.transfer_to)
                return 1
            txn_date = args.txn_date or date.today().isoformat()
            result = create_transfer(
                cfg,
                access,
                from_account_id=fid,
                to_account_id=tid,
                amount=float(args.amount),
                txn_date=txn_date,
                private_note="Rec IO bookkeeper",
            )
        except (FileNotFoundError, ValueError, RuntimeError) as e:
            logger.error("%s", e)
            return 1

        xfer = result.get("Transfer") or result
        tid_out = xfer.get("Id")
        sync = xfer.get("SyncToken")
        print(
            f"Transfer created — user {user_no} | {meta['environment']} | "
            f"realm {meta['realm_id']} | Id={tid_out} SyncToken={sync}"
        )
        print(f"  From [{fid}] {args.transfer_from}  →  To [{tid}] {args.transfer_to}")
        print(f"  Amount {args.amount}  TxnDate {txn_date}")
        if args.json:
            print(json.dumps(result, indent=2 if args.pretty_json else None))
        return 0

    try:
        accounts, meta = fetch_chart_of_accounts(user_no)
    except (FileNotFoundError, ValueError, RuntimeError) as e:
        logger.error("%s", e)
        return 1

    if args.json:
        print(
            json.dumps(
                {"meta": meta, "accounts": accounts},
                indent=2 if args.pretty_json else None,
            )
        )
        return 0

    print(
        f"QuickBooks chart of accounts — user {user_no} | "
        f"{meta['environment']} | realm {meta['realm_id']} | {len(accounts)} accounts"
    )
    for row in accounts:
        fq = row.get("FullyQualifiedName") or row.get("Name")
        at = row.get("AccountType")
        bal = row.get("CurrentBalance")
        aid = row.get("Id")
        print(f"  [{aid}] {fq}  ({at})  balance={bal}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
