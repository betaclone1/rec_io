"""
Intuit QuickBooks Online: OAuth 2.0 token exchange/refresh and QBO v3 REST calls.

Docs: https://developer.intuit.com/app/developer/qbo/docs/get-started

OAuth endpoints are loaded from the OpenID discovery document when possible
(https://developer.intuit.com/app/developer/qbo/docs/develop/authentication-and-authorization/oauth-openid-discovery-doc).
Fallback constants match last-known-good Intuit URLs if discovery is unreachable.
"""
from __future__ import annotations

import base64
import json
import logging
import urllib.parse
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import requests
from dotenv import dotenv_values

logger = logging.getLogger(__name__)

DISCOVERY_URL = "https://developer.intuit.com/.well-known/openid-configuration"

# Fallbacks when discovery fails (must stay aligned with Intuit production endpoints).
TOKEN_URL = "https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer"
AUTHORIZE_URL = "https://appcenter.intuit.com/connect/oauth2"

_oauth_endpoints_cache: tuple[str, str] | None = None


def reset_intuit_oauth_endpoints_cache() -> None:
    """Clear cached discovery result (for tests or forced re-fetch)."""
    global _oauth_endpoints_cache
    _oauth_endpoints_cache = None


def get_intuit_oauth_endpoints(
    *,
    timeout_sec: float = 30.0,
    session: requests.Session | None = None,
) -> tuple[str, str]:
    """
    Return ``(authorization_endpoint, token_endpoint)`` from OpenID discovery.

    Successful discovery is cached for the process lifetime. On failure or an
    invalid payload, returns ``(AUTHORIZE_URL, TOKEN_URL)`` without caching so a
    later call can retry discovery.
    """
    global _oauth_endpoints_cache
    if _oauth_endpoints_cache is not None:
        return _oauth_endpoints_cache
    sess = session or requests.Session()
    try:
        resp = sess.get(
            DISCOVERY_URL,
            timeout=timeout_sec,
            headers={"Accept": "application/json"},
        )
        resp.raise_for_status()
        doc = resp.json()
        auth_ep = doc.get("authorization_endpoint")
        tok_ep = doc.get("token_endpoint")
        if not isinstance(auth_ep, str) or not isinstance(tok_ep, str):
            raise ValueError("discovery: authorization_endpoint or token_endpoint missing")
        auth_ep, tok_ep = auth_ep.strip(), tok_ep.strip()
        if not auth_ep or not tok_ep:
            raise ValueError("discovery: empty authorization_endpoint or token_endpoint")
        _oauth_endpoints_cache = (auth_ep, tok_ep)
        logger.info(
            "Intuit OAuth: using discovery endpoints (auth=%s token=%s)",
            auth_ep,
            tok_ep,
        )
        return _oauth_endpoints_cache
    except Exception as e:
        logger.warning(
            "Intuit OAuth: discovery failed (%s); using fallback URLs",
            e,
        )
        return (AUTHORIZE_URL, TOKEN_URL)
# Accounting scope: read/write QBO data (read-only operations use the same scope).
SCOPE_ACCOUNTING = "com.intuit.quickbooks.accounting"
DEFAULT_MINOR_VERSION = "73"


@dataclass(frozen=True)
class QboConfig:
    client_id: str
    client_secret: str
    refresh_token: str
    realm_id: str
    environment: Literal["sandbox", "production"]


def api_base_url(environment: Literal["sandbox", "production"]) -> str:
    if environment == "sandbox":
        return "https://sandbox-quickbooks.api.intuit.com"
    return "https://quickbooks.api.intuit.com"


def load_qbo_config(credentials_dir: str | Path) -> QboConfig:
    """Load QBO config from credentials_dir/.env (see quickbooks/dotenv.example)."""
    path = Path(credentials_dir) / ".env"
    if not path.is_file():
        raise FileNotFoundError(f"Missing QuickBooks env file: {path}")
    env = dotenv_values(path)
    client_id = (env.get("INTUIT_CLIENT_ID") or "").strip()
    client_secret = (env.get("INTUIT_CLIENT_SECRET") or "").strip()
    refresh = (env.get("INTUIT_REFRESH_TOKEN") or "").strip()
    realm = (env.get("QBO_REALM_ID") or "").strip()
    raw_env = (env.get("QBO_ENVIRONMENT") or "sandbox").strip().lower()
    environment: Literal["sandbox", "production"] = (
        "production" if raw_env in ("production", "prod") else "sandbox"
    )
    missing = [
        name
        for name, val in (
            ("INTUIT_CLIENT_ID", client_id),
            ("INTUIT_CLIENT_SECRET", client_secret),
            ("INTUIT_REFRESH_TOKEN", refresh),
            ("QBO_REALM_ID", realm),
        )
        if not val
    ]
    if missing:
        raise ValueError(f"QuickBooks .env is missing: {', '.join(missing)}")
    return QboConfig(
        client_id=client_id,
        client_secret=client_secret,
        refresh_token=refresh,
        realm_id=realm,
        environment=environment,
    )


def _basic_auth_header(client_id: str, client_secret: str) -> str:
    raw = f"{client_id}:{client_secret}".encode("utf-8")
    return "Basic " + base64.b64encode(raw).decode("ascii")


def _intuit_tid(resp: requests.Response) -> str | None:
    """Return Intuit correlation id from response headers (case-insensitive)."""
    raw = resp.headers.get("intuit_tid")
    if raw is None or not str(raw).strip():
        return None
    return str(raw).strip()


def _log_intuit_response(resp: requests.Response, context: str) -> str | None:
    """
    Log intuit_tid for Intuit support correlation (see QBO API docs).

    Warnings on HTTP errors; DEBUG on success when intuit_tid is present.
    Returns the tid when present.
    """
    tid = _intuit_tid(resp)
    if resp.status_code >= 400:
        if tid:
            logger.warning(
                "Intuit HTTP error context=%s status=%s intuit_tid=%s",
                context,
                resp.status_code,
                tid,
            )
        else:
            logger.warning(
                "Intuit HTTP error context=%s status=%s (no intuit_tid header)",
                context,
                resp.status_code,
            )
    elif tid:
        logger.debug(
            "Intuit HTTP ok context=%s status=%s intuit_tid=%s",
            context,
            resp.status_code,
            tid,
        )
    return tid


def _fail_json_http(
    context: str,
    resp: requests.Response,
    body: Any,
) -> None:
    tid = _log_intuit_response(resp, context)
    suffix = f" intuit_tid={tid}" if tid else ""
    raise RuntimeError(f"{context} failed HTTP {resp.status_code}{suffix}: {body}")


def exchange_authorization_code(
    client_id: str,
    client_secret: str,
    code: str,
    redirect_uri: str,
    *,
    timeout_sec: float = 60.0,
) -> dict[str, Any]:
    """Trade an authorization code for tokens (one-time browser OAuth)."""
    token_ep = get_intuit_oauth_endpoints()[1]
    resp = requests.post(
        token_ep,
        headers={
            "Authorization": _basic_auth_header(client_id, client_secret),
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
        },
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
        },
        timeout=timeout_sec,
    )
    try:
        body = resp.json()
    except json.JSONDecodeError:
        body = {"raw": resp.text}
    if resp.status_code >= 400:
        _fail_json_http("Token exchange", resp, body)
    _log_intuit_response(resp, "oauth_token_exchange")
    return body


def refresh_access_token(
    client_id: str,
    client_secret: str,
    refresh_token: str,
    *,
    timeout_sec: float = 60.0,
) -> dict[str, Any]:
    """Obtain a new access_token (and usually a rotated refresh_token)."""
    token_ep = get_intuit_oauth_endpoints()[1]
    resp = requests.post(
        token_ep,
        headers={
            "Authorization": _basic_auth_header(client_id, client_secret),
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
        },
        data={"grant_type": "refresh_token", "refresh_token": refresh_token},
        timeout=timeout_sec,
    )
    try:
        body = resp.json()
    except json.JSONDecodeError:
        body = {"raw": resp.text}
    if resp.status_code >= 400:
        _fail_json_http("Refresh token", resp, body)
    _log_intuit_response(resp, "oauth_refresh_token")
    return body


def build_authorization_url(
    client_id: str,
    redirect_uri: str,
    state: str,
) -> str:
    authorize_ep = get_intuit_oauth_endpoints()[0]
    q = urllib.parse.urlencode(
        {
            "client_id": client_id,
            "response_type": "code",
            "scope": SCOPE_ACCOUNTING,
            "redirect_uri": redirect_uri,
            "state": state,
        }
    )
    return f"{authorize_ep}?{q}"


def get_company_info(
    cfg: QboConfig,
    access_token: str,
    *,
    timeout_sec: float = 60.0,
) -> dict[str, Any]:
    """GET CompanyInfo for the connected realm (read smoke test)."""
    base = api_base_url(cfg.environment)
    url = f"{base}/v3/company/{cfg.realm_id}/companyinfo/{cfg.realm_id}"
    resp = requests.get(
        url,
        headers={
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
        },
        params={"minorversion": DEFAULT_MINOR_VERSION},
        timeout=timeout_sec,
    )
    try:
        body = resp.json()
    except json.JSONDecodeError:
        body = {"raw": resp.text}
    if resp.status_code >= 400:
        _fail_json_http("CompanyInfo", resp, body)
    _log_intuit_response(resp, "qbo_companyinfo")
    return body


def run_report_query(
    cfg: QboConfig,
    access_token: str,
    query: str,
    *,
    timeout_sec: float = 60.0,
) -> dict[str, Any]:
    """
    Run a read-only QBO SQL query (v3 query endpoint).

    Example: ``select * from Account maxresults 100``
    See Intuit docs for supported entities and grammar.
    """
    base = api_base_url(cfg.environment)
    url = f"{base}/v3/company/{cfg.realm_id}/query"
    resp = requests.get(
        url,
        headers={
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
        },
        params={
            "query": query,
            "minorversion": DEFAULT_MINOR_VERSION,
        },
        timeout=timeout_sec,
    )
    try:
        body = resp.json()
    except json.JSONDecodeError:
        body = {"raw": resp.text}
    if resp.status_code >= 400:
        _fail_json_http("Query", resp, body)
    _log_intuit_response(resp, "qbo_query")
    return body


def run_transaction_list_report(
    cfg: QboConfig,
    access_token: str,
    *,
    account_id: str,
    start_date: str,
    end_date: str,
    cleared: Literal["Uncleared", "Cleared", "Reconciled"] | None = None,
    timeout_sec: float = 120.0,
) -> dict[str, Any]:
    """
    Run the **TransactionList** report for a single chart account.

    ``start_date`` / ``end_date`` must be ``YYYY-MM-DD``.

    ``cleared`` maps to QBO's ``cleared`` query parameter (e.g. ``Uncleared`` for
    items not yet cleared/reconciled on the bank register). Omit for all lines
    QBO includes in the default report window.

    Note: This is **not** the Banking tab "downloaded / for review" pipeline;
    that feed is largely outside the v3 Accounting REST surface we use here.
    """
    base = api_base_url(cfg.environment)
    url = f"{base}/v3/company/{cfg.realm_id}/reports/TransactionList"
    params: dict[str, str] = {
        "account": str(account_id),
        "start_date": start_date,
        "end_date": end_date,
        "minorversion": str(DEFAULT_MINOR_VERSION),
    }
    if cleared is not None:
        params["cleared"] = cleared
    resp = requests.get(
        url,
        headers={
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
        },
        params=params,
        timeout=timeout_sec,
    )
    try:
        body = resp.json()
    except json.JSONDecodeError:
        body = {"raw": resp.text}
    if resp.status_code >= 400:
        _fail_json_http("TransactionList report", resp, body)
    _log_intuit_response(resp, "qbo_report_transactionlist")
    return body


def transaction_list_report_column_meta(
    report: dict[str, Any],
) -> tuple[list[str], list[str | None]]:
    """
    Column titles and ``ColType`` from a TransactionList (or other report) ``Columns`` block.

    ``ColType`` is e.g. ``is_no_post`` for the **Posting** column; see QBO report JSON.
    """
    cols = report.get("Columns") or {}
    raw = cols.get("Column") or []
    if isinstance(raw, dict):
        raw = [raw]
    titles: list[str] = []
    types: list[str | None] = []
    for c in raw:
        if not isinstance(c, dict):
            titles.append("")
            types.append(None)
            continue
        titles.append(str(c.get("ColTitle") or ""))
        ct = c.get("ColType")
        types.append(str(ct) if ct is not None else None)
    return titles, types


def transaction_list_report_headers(report: dict[str, Any]) -> list[str]:
    """Column titles from a TransactionList report JSON."""
    titles, _ = transaction_list_report_column_meta(report)
    return titles


def iter_transaction_list_data_rows(rows: Any) -> list[dict[str, Any]]:
    """Flatten nested ``Rows`` / ``Row`` / ``Section`` structure into ``type=Data`` rows."""
    out: list[dict[str, Any]] = []

    def walk(node: Any) -> None:
        if node is None:
            return
        if isinstance(node, dict):
            if node.get("type") == "Data" and "ColData" in node:
                out.append(node)
                return
            inner = node.get("Rows")
            if inner is not None:
                walk(inner)
            row = node.get("Row")
            if row is not None:
                walk(row)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    if isinstance(rows, dict):
        walk(rows.get("Row"))
    return out


def _transaction_list_parse_cell(cell: Any) -> dict[str, Any]:
    """One ``ColData`` cell: string ``value`` and optional ``is_no_post`` (QBO report flag)."""
    if not isinstance(cell, dict):
        return {"value": "", "is_no_post": None}
    out: dict[str, Any] = {"value": str(cell.get("value") or "")}
    if "is_no_post" in cell:
        out["is_no_post"] = bool(cell["is_no_post"])
    else:
        out["is_no_post"] = None
    return out


def transaction_list_report_enriched(
    report: dict[str, Any],
) -> tuple[list[str], list[str | None], list[list[dict[str, Any]]]]:
    """
    Parse TransactionList report rows with per-cell metadata.

    Returns ``(headers, col_types, rows)`` where each row is a list of cell dicts
    ``{"value": str, "is_no_post": bool | None}`` aligned with ``headers``.
    """
    headers, col_types = transaction_list_report_column_meta(report)
    data_rows = iter_transaction_list_data_rows(report.get("Rows"))
    lines: list[list[dict[str, Any]]] = []
    for dr in data_rows:
        cd = dr.get("ColData") or []
        row = [_transaction_list_parse_cell(cell) for cell in cd]
        lines.append(row)
    return headers, col_types, lines


def _transaction_list_posting_column_index(
    headers: list[str], col_types: list[str | None]
) -> int | None:
    for i, ct in enumerate(col_types):
        if ct == "is_no_post":
            return i
    for i, h in enumerate(headers):
        if h.strip().casefold() == "posting":
            return i
    return None


def transaction_list_report_to_row_dicts(
    report: dict[str, Any],
) -> tuple[list[str], list[str | None], list[dict[str, Any]]]:
    """
    Flatten a TransactionList report to one dict per line.

    Each dict maps ``ColTitle`` to the cell string. If the report has a Posting column
    (``ColType`` ``is_no_post`` or title **Posting**), adds ``posting_is_no_post``:
    the API boolean when present, else ``None``.
    """
    headers, col_types, enriched = transaction_list_report_enriched(report)
    posting_idx = _transaction_list_posting_column_index(headers, col_types)
    rows_out: list[dict[str, Any]] = []
    for row_cells in enriched:
        pad_n = max(0, len(headers) - len(row_cells))
        padded = row_cells + [{"value": "", "is_no_post": None}] * pad_n
        row_dict: dict[str, Any] = {}
        for hi, h in enumerate(headers):
            row_dict[h] = str(padded[hi].get("value") or "")
        if posting_idx is not None and posting_idx < len(padded):
            row_dict["posting_is_no_post"] = padded[posting_idx].get("is_no_post")
        rows_out.append(row_dict)
    return headers, col_types, rows_out


def transaction_list_report_to_cell_rows(report: dict[str, Any]) -> tuple[list[str], list[list[str]]]:
    """Return ``(headers, rows)`` where each row is a list of string cell values."""
    headers, _, enriched = transaction_list_report_enriched(report)
    lines = [[c["value"] for c in row] for row in enriched]
    return headers, lines


def get_chart_of_accounts(
    cfg: QboConfig,
    access_token: str,
    *,
    max_results: int = 1000,
    timeout_sec: float = 60.0,
) -> list[dict[str, Any]]:
    """Return Account rows (chart of accounts) via a read-only query."""
    cap = max(1, min(int(max_results), 1000))
    q = (
        "select Id, Name, AccountType, AccountSubType, FullyQualifiedName, "
        "Active, Classification, CurrentBalance "
        f"from Account order by FullyQualifiedName maxresults {cap}"
    )
    body = run_report_query(cfg, access_token, q, timeout_sec=timeout_sec)
    qr = body.get("QueryResponse") or {}
    raw = qr.get("Account")
    if raw is None:
        return []
    if isinstance(raw, dict):
        return [raw]
    if isinstance(raw, list):
        return raw
    return []


def create_transfer(
    cfg: QboConfig,
    access_token: str,
    *,
    from_account_id: str,
    to_account_id: str,
    amount: float,
    txn_date: str,
    private_note: str | None = None,
    timeout_sec: float = 60.0,
) -> dict[str, Any]:
    """
    Create a balance-sheet Transfer between two accounts (POST Transfer).

    ``txn_date`` must be ``YYYY-MM-DD``. Both accounts must be balance-sheet types QBO accepts for transfers.
    """
    base = api_base_url(cfg.environment)
    url = f"{base}/v3/company/{cfg.realm_id}/transfer"
    payload: dict[str, Any] = {
        "TxnDate": txn_date,
        "FromAccountRef": {"value": str(from_account_id)},
        "ToAccountRef": {"value": str(to_account_id)},
        "Amount": float(amount),
    }
    if private_note:
        payload["PrivateNote"] = private_note
    resp = requests.post(
        url,
        headers={
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
        params={"minorversion": DEFAULT_MINOR_VERSION},
        json=payload,
        timeout=timeout_sec,
    )
    try:
        body = resp.json()
    except json.JSONDecodeError:
        body = {"raw": resp.text}
    if resp.status_code >= 400:
        _fail_json_http("Transfer", resp, body)
    _log_intuit_response(resp, "qbo_transfer")
    return body


def create_journal_entry_lines(
    cfg: QboConfig,
    access_token: str,
    *,
    txn_date: str,
    private_note: str,
    lines: list[dict[str, Any]],
    timeout_sec: float = 60.0,
) -> dict[str, Any]:
    """
    Post a balanced multi-line JournalEntry.

    Each ``lines`` item: ``{"posting_type": "Debit"|"Credit", "account_id": str, "amount": float}``.
    Debit totals must equal credit totals (to the cent).
    """
    if not lines:
        raise ValueError("Journal entry requires at least one line")
    qbo_lines: list[dict[str, Any]] = []
    debit_total = 0.0
    credit_total = 0.0
    for i, raw in enumerate(lines):
        posting = str(raw.get("posting_type") or "").strip()
        if posting not in ("Debit", "Credit"):
            raise ValueError(f"Journal line[{i}] posting_type must be Debit or Credit")
        aid = str(raw.get("account_id") or "").strip()
        if not aid:
            raise ValueError(f"Journal line[{i}] missing account_id")
        amt = round(float(raw["amount"]), 2)
        if amt <= 0:
            raise ValueError(f"Journal line[{i}] amount must be positive")
        if posting == "Debit":
            debit_total = round(debit_total + amt, 2)
        else:
            credit_total = round(credit_total + amt, 2)
        qbo_lines.append(
            {
                "DetailType": "JournalEntryLineDetail",
                "Amount": amt,
                "JournalEntryLineDetail": {
                    "PostingType": posting,
                    "AccountRef": {"value": aid},
                },
            }
        )
    if debit_total != credit_total:
        raise ValueError(
            f"Journal entry unbalanced: debits={debit_total:.2f} credits={credit_total:.2f}"
        )
    base = api_base_url(cfg.environment)
    url = f"{base}/v3/company/{cfg.realm_id}/journalentry"
    payload: dict[str, Any] = {
        "TxnDate": txn_date,
        "PrivateNote": private_note,
        "Line": qbo_lines,
    }
    resp = requests.post(
        url,
        headers={
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
        params={"minorversion": DEFAULT_MINOR_VERSION},
        json=payload,
        timeout=timeout_sec,
    )
    try:
        body = resp.json()
    except json.JSONDecodeError:
        body = {"raw": resp.text}
    if resp.status_code >= 400:
        _fail_json_http("JournalEntry", resp, body)
    _log_intuit_response(resp, "qbo_journalentry")
    return body


def create_journal_entry_two_line(
    cfg: QboConfig,
    access_token: str,
    *,
    txn_date: str,
    private_note: str,
    amount: float,
    debit_account_id: str,
    credit_account_id: str,
    timeout_sec: float = 60.0,
) -> dict[str, Any]:
    """
    Balanced two-line journal entry: Debit first account, Credit second, same ``amount``.
    """
    return create_journal_entry_lines(
        cfg,
        access_token,
        txn_date=txn_date,
        private_note=private_note,
        lines=[
            {
                "posting_type": "Debit",
                "account_id": debit_account_id,
                "amount": amount,
            },
            {
                "posting_type": "Credit",
                "account_id": credit_account_id,
                "amount": amount,
            },
        ],
        timeout_sec=timeout_sec,
    )
