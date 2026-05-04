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
    base = api_base_url(cfg.environment)
    url = f"{base}/v3/company/{cfg.realm_id}/journalentry"
    amt = round(float(amount), 2)
    if amt <= 0:
        raise ValueError("Journal amount must be positive")
    payload: dict[str, Any] = {
        "TxnDate": txn_date,
        "PrivateNote": private_note,
        "Line": [
            {
                "DetailType": "JournalEntryLineDetail",
                "Amount": amt,
                "JournalEntryLineDetail": {
                    "PostingType": "Debit",
                    "AccountRef": {"value": str(debit_account_id)},
                },
            },
            {
                "DetailType": "JournalEntryLineDetail",
                "Amount": amt,
                "JournalEntryLineDetail": {
                    "PostingType": "Credit",
                    "AccountRef": {"value": str(credit_account_id)},
                },
            },
        ],
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
