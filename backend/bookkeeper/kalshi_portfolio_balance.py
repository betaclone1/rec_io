"""Fetch Kalshi v2 portfolio balance (cash + positions) using per-user prod credentials."""
from __future__ import annotations

import base64
import time
from pathlib import Path

import requests
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from dotenv import dotenv_values

KALSHI_TRADE_API_V2 = "https://external-api.kalshi.com/trade-api/v2"


def _kalshi_prod_credentials(user_no: str) -> tuple[str, Path] | None:
    from backend.util.paths import get_kalshi_credentials_dir

    cred_root = Path(get_kalshi_credentials_dir(user_no)) / "prod"
    env_path = cred_root / ".env"
    pem_path = cred_root / "kalshi.pem"
    env = dotenv_values(env_path) if env_path.is_file() else {}
    key_id = (env.get("KALSHI_API_KEY_ID") or "").strip()
    if not key_id or not pem_path.is_file():
        return None
    return key_id, pem_path


def _sign_request(method: str, path_for_sig: str, timestamp_ms: str, key_path: Path) -> str:
    """RSA-PSS SHA256 signature (same contract as kalshi_account_sync_ws)."""
    with open(key_path, "rb") as key_file:
        private_key = serialization.load_pem_private_key(
            key_file.read(), password=None, backend=default_backend()
        )
    message = f"{timestamp_ms}{method.upper()}{path_for_sig}".encode("utf-8")
    signature = private_key.sign(
        message,
        padding.PSS(
            mgf=padding.MGF1(hashes.SHA256()),
            salt_length=padding.PSS.MAX_LENGTH,
        ),
        hashes.SHA256(),
    )
    return base64.b64encode(signature).decode("utf-8")


def kalshi_prod_request(
    user_no: str,
    method: str,
    path: str,
    *,
    params: dict | None = None,
    json_body: dict | None = None,
    timeout: int = 30,
) -> requests.Response:
    """
    Signed Kalshi Trade API v2 request for ``user_no`` prod credentials.

    ``path`` must start with ``/portfolio/...`` (no host, no query string).
    Query params are signed separately from the path (Kalshi excludes ``?`` from the signature).
    """
    creds = _kalshi_prod_credentials(user_no)
    if creds is None:
        raise FileNotFoundError(f"Kalshi prod credentials missing for user {user_no}")
    key_id, pem_path = creds
    path_only = path.split("?", 1)[0]
    path_sig = f"/trade-api/v2{path_only}"
    url = f"{KALSHI_TRADE_API_V2}{path_only}"
    ts = str(int(time.time() * 1000))
    sig = _sign_request(method, path_sig, ts, pem_path)
    headers = {
        "Accept": "application/json",
        "User-Agent": "rec-io-kalshi-bookkeeper/1.0",
        "KALSHI-ACCESS-KEY": key_id,
        "KALSHI-ACCESS-TIMESTAMP": ts,
        "KALSHI-ACCESS-SIGNATURE": sig,
    }
    if json_body is not None:
        headers["Content-Type"] = "application/json"
        return requests.request(
            method.upper(),
            url,
            headers=headers,
            params=params,
            json=json_body,
            timeout=timeout,
        )
    return requests.request(
        method.upper(), url, headers=headers, params=params, timeout=timeout
    )


def fetch_portfolio_balance_detail(
    user_no: str,
    *,
    subaccount: int | None = None,
) -> dict[str, int] | None:
    """
    GET /portfolio/balance for a tenant (optional ``subaccount`` query param).

    Returns ``balance_cents``, ``portfolio_value_cents``, ``total_portfolio_cents``.

    When ``subaccount`` is set, this is that wallet's top-level ``balance`` field.
    When omitted, callers that need **full-account** cash across subaccounts should
    use ``fetch_total_portfolio_cents`` (``balance_breakdown``, confirmed vs subaccounts),
    not this helper — top-level ``balance`` / ``balance_dollars`` can be primary-wallet only.
    """
    try:
        req_params = {"subaccount": int(subaccount)} if subaccount is not None else None
        resp = kalshi_prod_request(user_no, "GET", "/portfolio/balance", params=req_params)
        resp.raise_for_status()
        data = resp.json()
    except Exception:
        return None
    cash = int(data.get("balance") or 0)
    pos = int(data.get("portfolio_value") or 0)
    return {
        "balance_cents": cash,
        "portfolio_value_cents": pos,
        "total_portfolio_cents": cash + pos,
    }


def sum_balance_breakdown_cents(data: dict) -> int:
    """
    Sum ``balance_breakdown[].balance`` dollar strings from GET /portfolio/balance into cents.

    Raises ``ValueError`` if breakdown is missing, empty, or not parseable.
    Does **not** fall back to top-level ``balance`` / ``balance_dollars``.
    """
    from backend.core.kalshi_money import dollars_to_cents

    rows = data.get("balance_breakdown")
    if not isinstance(rows, list) or not rows:
        raise ValueError(
            "Kalshi GET /portfolio/balance missing non-empty balance_breakdown "
            "(cannot use top-level balance / balance_dollars as full-account total)"
        )
    total = 0
    for i, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ValueError(f"Kalshi balance_breakdown[{i}] is not an object")
        cents = dollars_to_cents(row.get("balance"))
        if cents is None:
            raise ValueError(
                f"Kalshi balance_breakdown[{i}] has unparseable balance: {row.get('balance')!r}"
            )
        total += cents
    return total


def fetch_total_portfolio_cents(user_no: str) -> tuple[int, dict]:
    """
    Full-account Kalshi total for bookkeeper reconcile, in cents.

    Cash = sum of ``balance_breakdown`` on GET /portfolio/balance (not top-level
    ``balance`` / ``balance_dollars``, which may be primary-wallet only). Confirmed
    against the sum of GET /portfolio/subaccounts/balances. Positions =
    ``portfolio_value``. Total = cash + positions.

    Raises if credentials/API fail, breakdown is missing, subaccounts cannot be
    fetched, or cash vs subaccount sums disagree (no substitute / fallback).
    """
    try:
        resp = kalshi_prod_request(user_no, "GET", "/portfolio/balance")
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        raise FileNotFoundError(
            f"Kalshi prod credentials or balance fetch failed for user {user_no}: {e}"
        ) from e

    cash_cents = sum_balance_breakdown_cents(data)
    pos_cents = int(data.get("portfolio_value") or 0)

    sub_map = fetch_subaccount_balances_cents_map(user_no)
    if sub_map is None:
        raise RuntimeError(
            f"Kalshi subaccount balances unavailable for user {user_no}; "
            "cannot confirm balance_breakdown against subaccounts"
        )
    sub_sum = sum(int(v) for v in sub_map.values())
    if sub_sum != cash_cents:
        raise RuntimeError(
            f"Kalshi full-account cash mismatch for user {user_no}: "
            f"balance_breakdown_sum_cents={cash_cents} "
            f"subaccount_sum_cents={sub_sum} "
            f"(subaccounts={dict(sorted(sub_map.items()))})"
        )

    total = cash_cents + pos_cents
    detail = {
        "balance_cents": cash_cents,
        "portfolio_value_cents": pos_cents,
        "total_portfolio_cents": total,
        "subaccount_sum_cents": sub_sum,
        "subaccount_balances_cents": dict(sorted(sub_map.items())),
        "legacy_top_level_balance_cents": int(data.get("balance") or 0),
    }
    return total, detail


def fetch_subaccount_balances_cents_map(user_no: str) -> dict[int, int] | None:
    """
    GET /portfolio/subaccounts/balances; normalize dollar ``balance`` strings to integer cents.

    Returns ``{kalshi_subaccount_number: balance_cents}`` or ``None`` if credentials missing
    or the request fails.
    """
    from backend.core.kalshi_money import normalize_kalshi_subaccount_balances_response

    try:
        resp = kalshi_prod_request(user_no, "GET", "/portfolio/subaccounts/balances")
        resp.raise_for_status()
        raw = resp.json()
    except Exception:
        return None

    normalized = normalize_kalshi_subaccount_balances_response(raw)
    out: dict[int, int] = {}
    for row in normalized.get("subaccount_balances") or []:
        num = row.get("subaccount_number")
        bal = row.get("balance")
        if num is None or bal is None:
            continue
        try:
            out[int(num)] = int(bal)
        except (TypeError, ValueError):
            continue
    return out if out else None
