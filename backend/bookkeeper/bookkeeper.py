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
  ./venv/bin/python -m backend.bookkeeper.bookkeeper --user-no 0001 --list-bank-uncleared --bank-days 90
  ./venv/bin/python -m backend.bookkeeper.bookkeeper --user-no 0001 --transaction-list "Revenue Checking" \\
    --bank-days 90 --json --pretty-json
  ./venv/bin/python -m backend.bookkeeper.bookkeeper --user-no 0001 --journal-entries "Kalshi Trading Account" \\
    --bank-days 365 --json --pretty-json
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from backend.bookkeeper.kalshi_portfolio_balance import fetch_total_portfolio_cents
from backend.bookkeeper.quickbooks import (
    QboConfig,
    create_journal_entry_two_line,
    create_transfer,
    get_chart_of_accounts,
    load_qbo_config,
    refresh_access_token,
    run_transaction_list_report,
    transaction_list_report_to_row_dicts,
)
from backend.core.tenant_script_args import add_user_no_argument, resolve_user_no
from backend.util.paths import get_quickbooks_credentials_dir

logger = logging.getLogger(__name__)


def _persist_refresh_token(cred_dir: str, new_refresh_token: str) -> None:
    """
    Atomically update INTUIT_REFRESH_TOKEN in the tenant quickbooks ``.env``.

    Preserves file mode and updates in place (append key if missing).
    """
    env_path = Path(cred_dir) / ".env"
    if not env_path.is_file():
        raise FileNotFoundError(f"Missing QuickBooks env file: {env_path}")
    raw = env_path.read_text(encoding="utf-8")
    lines = raw.splitlines(keepends=True)
    had_final_newline = raw.endswith("\n")
    out_lines: list[str] = []
    replaced = False
    for line in lines:
        stripped = line.lstrip()
        if stripped.startswith("INTUIT_REFRESH_TOKEN="):
            prefix = line[: len(line) - len(stripped)]
            ending = "\n" if line.endswith("\n") else ""
            out_lines.append(f"{prefix}INTUIT_REFRESH_TOKEN={new_refresh_token}{ending}")
            replaced = True
            continue
        out_lines.append(line)
    if not replaced:
        if out_lines and not out_lines[-1].endswith("\n"):
            out_lines[-1] = out_lines[-1] + "\n"
        out_lines.append(f"INTUIT_REFRESH_TOKEN={new_refresh_token}\n")
    new_content = "".join(out_lines)
    if not had_final_newline:
        new_content = new_content.rstrip("\n")

    st = env_path.stat()
    tmp_path = env_path.with_suffix(".env.tmp")
    tmp_path.write_text(new_content, encoding="utf-8")
    os.chmod(tmp_path, st.st_mode)
    os.replace(tmp_path, env_path)


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
        try:
            _persist_refresh_token(cred_dir, str(new_refresh))
            logger.info("QuickBooks: rotated refresh token persisted in %s/.env", cred_dir)
        except OSError as e:
            raise RuntimeError(
                f"Intuit returned a rotated refresh_token but persistence failed in {cred_dir}/.env: {e}"
            ) from e
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


def resolve_account_id(accounts: list[dict[str, Any]], label: str) -> str | None:
    """Chart account by numeric ``Id`` or by Name / FullyQualifiedName (see ``account_id_by_exact_name``)."""
    s = label.strip()
    if s.isdigit():
        for a in accounts:
            if str(a.get("Id") or "") == s:
                return s
        return None
    return account_id_by_exact_name(accounts, label)


def _transaction_list_cleared_param(args: argparse.Namespace) -> str | None:
    if args.cleared_filter == "all":
        return None
    if args.cleared_filter == "uncleared":
        return "Uncleared"
    if args.cleared_filter == "cleared":
        return "Cleared"
    return "Reconciled"


def _transaction_list_date_span(
    args: argparse.Namespace, parser: argparse.ArgumentParser
) -> tuple[str, str]:
    if args.report_start_date and args.report_end_date:
        return args.report_start_date, args.report_end_date
    if args.report_start_date or args.report_end_date:
        parser.error(
            "Use both --report-start-date and --report-end-date, or neither "
            "(then --bank-days applies)."
        )
    days = max(1, min(int(args.bank_days), 3650))
    end_d = date.today()
    start_d = end_d - timedelta(days=days)
    return start_d.isoformat(), end_d.isoformat()


def _format_transaction_list_line(rd: dict[str, Any]) -> str:
    txn_type = rd.get("Transaction Type", "")
    dt = rd.get("Date", "")
    amt = rd.get("Amount", "")
    memo = rd.get("Memo/Description", "")
    split = rd.get("Split", "")
    base = f"  {dt}  {txn_type}  amt={amt}  split={split}  memo={memo}"
    if "posting_is_no_post" in rd:
        posting = rd.get("Posting", "")
        pinp = rd.get("posting_is_no_post")
        base += f"  Posting={posting!r}"
        if pinp is not None:
            base += f"  is_no_post={pinp!r}"
    return base


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
        description=(
            "Rec IO bookkeeper: QuickBooks Online (chart, transfers, Kalshi reconcile, "
            "bank uncleared lines)."
        ),
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
        help="Print JSON to stdout (chart mode, --transaction-list, or --list-bank-uncleared).",
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
    parser.add_argument(
        "--list-bank-uncleared",
        action="store_true",
        help=(
            "List uncleared register lines on Bank and Credit Card accounts (QBO "
            "TransactionList report, cleared=Uncleared). Not the Banking tab "
            "'for review' downloaded feed (not on this v3 Accounting API)."
        ),
    )
    parser.add_argument(
        "--bank-days",
        type=int,
        default=90,
        metavar="N",
        help="With --list-bank-uncleared, --transaction-list, or --journal-entries (no explicit dates), "
        "start date is today minus N days (default 90).",
    )
    parser.add_argument(
        "--transaction-list",
        metavar="ACCOUNT",
        default=None,
        help=(
            "Run QBO TransactionList for one chart account (Name, FullyQualifiedName, or numeric Id). "
            "Date range: use --report-start-date and --report-end-date together, or else --bank-days "
            "ending today. Default cleared filter is all lines; set --cleared-filter to narrow."
        ),
    )
    parser.add_argument(
        "--journal-entries",
        metavar="ACCOUNT",
        default=None,
        help=(
            "QBO TransactionList for one account, output only rows with Transaction Type Journal Entry "
            "(same account resolution and date/cleared options as --transaction-list)."
        ),
    )
    parser.add_argument(
        "--cleared-filter",
        choices=("all", "uncleared", "cleared", "reconciled"),
        default="all",
        help="With --transaction-list or --journal-entries, QBO cleared= filter (default: all).",
    )
    parser.add_argument(
        "--report-start-date",
        dest="report_start_date",
        metavar="YYYY-MM-DD",
        default=None,
        help="With --transaction-list or --journal-entries, range start (requires --report-end-date).",
    )
    parser.add_argument(
        "--report-end-date",
        dest="report_end_date",
        metavar="YYYY-MM-DD",
        default=None,
        help="With --transaction-list or --journal-entries, range end (requires --report-start-date).",
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

    if args.transaction_list:
        if (
            args.reconcile_kalshi
            or transfer_requested
            or args.list_bank_uncleared
            or args.journal_entries
        ):
            parser.error(
                "--transaction-list cannot be used with --reconcile-kalshi, "
                "--list-bank-uncleared, --journal-entries, or transfer options."
            )
        cleared_param = _transaction_list_cleared_param(args)
        start_s, end_s = _transaction_list_date_span(args, parser)
        try:
            cfg, access, meta = qbo_connect(user_no)
            accounts = get_chart_of_accounts(cfg, access)
            aid = resolve_account_id(accounts, args.transaction_list)
            if not aid:
                logger.error("Unknown QBO account: %r", args.transaction_list)
                return 1
            acct_row = _account_row_by_id(accounts, aid)
            label = (
                (acct_row or {}).get("FullyQualifiedName")
                or (acct_row or {}).get("Name")
                or aid
            )
            rep = run_transaction_list_report(
                cfg,
                access,
                account_id=aid,
                start_date=start_s,
                end_date=end_s,
                cleared=cleared_param,
            )
            hdrs, col_types, row_dicts = transaction_list_report_to_row_dicts(rep)
            payload_tl: dict[str, Any] = {
                "meta": {
                    **meta,
                    "bank_report": "TransactionList",
                    "cleared_filter": args.cleared_filter,
                    "start_date": start_s,
                    "end_date": end_s,
                },
                "account": {
                    "account_id": aid,
                    "account_name": str(label).strip(),
                    "account_type": (acct_row or {}).get("AccountType"),
                    "headers": hdrs,
                    "column_types": col_types,
                    "rows": row_dicts,
                },
            }
        except (FileNotFoundError, ValueError, RuntimeError, OSError) as e:
            logger.error("%s", e)
            return 1

        if args.json:
            print(
                json.dumps(
                    payload_tl,
                    indent=2 if args.pretty_json else None,
                )
            )
            return 0

        print(
            f"QuickBooks TransactionList — user {user_no} | {meta['environment']} | "
            f"realm {meta['realm_id']} | {start_s} .. {end_s} | cleared={args.cleared_filter}"
        )
        print(
            "\n(TransactionList is register/report data; Banking 'for review' is a separate pipeline.)"
        )
        fq_label = str(label).strip()
        print(
            f"\n## [{aid}] {fq_label}  ({(acct_row or {}).get('AccountType')})  lines={len(row_dicts)}"
        )
        for rd in row_dicts:
            print(_format_transaction_list_line(rd))
        return 0

    if args.journal_entries:
        if (
            args.reconcile_kalshi
            or transfer_requested
            or args.list_bank_uncleared
            or args.transaction_list
        ):
            parser.error(
                "--journal-entries cannot be used with --reconcile-kalshi, "
                "--list-bank-uncleared, --transaction-list, or transfer options."
            )
        cleared_param = _transaction_list_cleared_param(args)
        start_s, end_s = _transaction_list_date_span(args, parser)
        try:
            cfg, access, meta = qbo_connect(user_no)
            accounts = get_chart_of_accounts(cfg, access)
            aid = resolve_account_id(accounts, args.journal_entries)
            if not aid:
                logger.error("Unknown QBO account: %r", args.journal_entries)
                return 1
            acct_row = _account_row_by_id(accounts, aid)
            label = (
                (acct_row or {}).get("FullyQualifiedName")
                or (acct_row or {}).get("Name")
                or aid
            )
            rep = run_transaction_list_report(
                cfg,
                access,
                account_id=aid,
                start_date=start_s,
                end_date=end_s,
                cleared=cleared_param,
            )
            hdrs, col_types, row_dicts = transaction_list_report_to_row_dicts(rep)
            je_rows = [
                r
                for r in row_dicts
                if (r.get("Transaction Type") or "").strip().casefold()
                == "journal entry"
            ]
            payload_je: dict[str, Any] = {
                "meta": {
                    **meta,
                    "bank_report": "TransactionList",
                    "row_filter": "Journal Entry",
                    "cleared_filter": args.cleared_filter,
                    "start_date": start_s,
                    "end_date": end_s,
                    "report_line_count": len(row_dicts),
                    "journal_entry_count": len(je_rows),
                },
                "account": {
                    "account_id": aid,
                    "account_name": str(label).strip(),
                    "account_type": (acct_row or {}).get("AccountType"),
                    "headers": hdrs,
                    "column_types": col_types,
                    "rows": je_rows,
                },
            }
        except (FileNotFoundError, ValueError, RuntimeError, OSError) as e:
            logger.error("%s", e)
            return 1

        if args.json:
            print(
                json.dumps(
                    payload_je,
                    indent=2 if args.pretty_json else None,
                )
            )
            return 0

        print(
            f"QuickBooks JournalEntry lines (TransactionList) — user {user_no} | "
            f"{meta['environment']} | realm {meta['realm_id']} | {start_s} .. {end_s} | "
            f"cleared={args.cleared_filter}"
        )
        print(
            f"Account [{aid}] {str(label).strip()}  ({(acct_row or {}).get('AccountType')})  "
            f"journal_lines={len(je_rows)}  (of {len(row_dicts)} report lines)"
        )
        for rd in je_rows:
            print(_format_transaction_list_line(rd))
        return 0

    if args.list_bank_uncleared:
        if (
            args.reconcile_kalshi
            or transfer_requested
            or args.transaction_list
            or args.journal_entries
        ):
            parser.error(
                "--list-bank-uncleared cannot be used with --reconcile-kalshi, "
                "--transaction-list, --journal-entries, or transfer options."
            )
        days = max(1, min(int(args.bank_days), 3650))
        end_d = date.today()
        start_d = end_d - timedelta(days=days)
        start_s, end_s = start_d.isoformat(), end_d.isoformat()
        bank_types = frozenset({"Bank", "Credit Card"})
        try:
            cfg, access, meta = qbo_connect(user_no)
            accounts = get_chart_of_accounts(cfg, access)
            bank_accounts = [
                a
                for a in accounts
                if (a.get("AccountType") or "").strip() in bank_types
            ]
            sections: list[dict[str, Any]] = []
            for acct in bank_accounts:
                aid = str(acct.get("Id") or "")
                if not aid:
                    continue
                label = (acct.get("FullyQualifiedName") or acct.get("Name") or aid).strip()
                try:
                    rep = run_transaction_list_report(
                        cfg,
                        access,
                        account_id=aid,
                        start_date=start_s,
                        end_date=end_s,
                        cleared="Uncleared",
                    )
                except (RuntimeError, OSError) as e:
                    logger.error("TransactionList failed for %s (%s): %s", label, aid, e)
                    sections.append(
                        {
                            "account_id": aid,
                            "account_name": label,
                            "account_type": acct.get("AccountType"),
                            "error": str(e),
                            "rows": [],
                        }
                    )
                    continue
                hdrs, col_types, row_dicts = transaction_list_report_to_row_dicts(rep)
                sections.append(
                    {
                        "account_id": aid,
                        "account_name": label,
                        "account_type": acct.get("AccountType"),
                        "headers": hdrs,
                        "column_types": col_types,
                        "rows": row_dicts,
                    }
                )
            payload: dict[str, Any] = {
                "meta": {
                    **meta,
                    "bank_report": "TransactionList",
                    "cleared_filter": "Uncleared",
                    "start_date": start_s,
                    "end_date": end_s,
                },
                "accounts": sections,
            }
        except (FileNotFoundError, ValueError, RuntimeError, OSError) as e:
            logger.error("%s", e)
            return 1

        if args.json:
            print(
                json.dumps(
                    payload,
                    indent=2 if args.pretty_json else None,
                )
            )
            return 0

        print(
            f"QuickBooks uncleared bank/CC register lines — user {user_no} | "
            f"{meta['environment']} | realm {meta['realm_id']} | {start_s} .. {end_s}"
        )
        print(
            "(QBO TransactionList, cleared=Uncleared — not Banking 'for review' downloads.)"
        )
        for sec in sections:
            label = sec.get("account_name")
            aid = sec.get("account_id")
            if sec.get("error"):
                print(f"\n## [{aid}] {label}  ERROR: {sec['error']}")
                continue
            rows = sec.get("rows") or []
            print(f"\n## [{aid}] {label}  ({sec.get('account_type')})  lines={len(rows)}")
            for rd in rows:
                print(_format_transaction_list_line(rd))
        return 0

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
            f"(full-account cash ${ks_detail['balance_cents']/100:.2f} "
            f"from balance_breakdown, confirmed vs subaccounts "
            f"${ks_detail.get('subaccount_sum_cents', ks_detail['balance_cents'])/100:.2f} + "
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
