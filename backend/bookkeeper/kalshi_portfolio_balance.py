"""Fetch Kalshi v2 portfolio balance (cash + positions) using per-user prod credentials."""
from __future__ import annotations

import base64
import logging
import time
from pathlib import Path

logger = logging.getLogger(__name__)

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

    # balance_breakdown (per exchange_index) and subaccount balances (per subaccount)
    # are two different partitions of the same money, each a 4-decimal dollar string
    # rounded to cents per row. Their aggregate cent-rounding drift is bounded by
    # ceil((n_break + n_sub)/2); differences beyond that are a real discrepancy.
    n_break = len([r for r in (data.get("balance_breakdown") or []) if isinstance(r, dict)])
    n_sub = len(sub_map)
    tolerance_cents = (n_break + n_sub + 1) // 2
    drift = sub_sum - cash_cents
    if abs(drift) > tolerance_cents:
        raise RuntimeError(
            f"Kalshi full-account cash mismatch for user {user_no}: "
            f"balance_breakdown_sum_cents={cash_cents} "
            f"subaccount_sum_cents={sub_sum} "
            f"(drift={drift}c > tolerance={tolerance_cents}c; "
            f"subaccounts={dict(sorted(sub_map.items()))})"
        )
    if drift != 0:
        logger.warning(
            "Kalshi cash cross-check off by %+dc within rounding tolerance %dc for "
            "user %s (balance_breakdown_sum=%d, subaccount_sum=%d); using "
            "balance_breakdown as total",
            drift,
            tolerance_cents,
            user_no,
            cash_cents,
            sub_sum,
        )

    total = cash_cents + pos_cents
    detail = {
        "balance_cents": cash_cents,
        "portfolio_value_cents": pos_cents,
        "total_portfolio_cents": total,
        "subaccount_sum_cents": sub_sum,
        "subaccount_cross_check_drift_cents": drift,
        "subaccount_cross_check_tolerance_cents": tolerance_cents,
        "subaccount_balances_cents": dict(sorted(sub_map.items())),
        "legacy_top_level_balance_cents": int(data.get("balance") or 0),
    }
    return total, detail


def fetch_subaccount_balances_matrix(user_no: str) -> dict[int, dict] | None:
    """
    GET /portfolio/subaccounts/balances as a per-subaccount matrix.

    Returns ``{subaccount_number: {"balance_cents": int, "exchange_balances_cents": {exchange_index: cents}}}``
    or ``None`` if credentials missing / request fails.

    Multiple rows for the same subaccount on different ``exchange_index`` values are **summed**
    into ``balance_cents`` (do not overwrite).
    """
    from backend.core.kalshi_money import normalize_kalshi_subaccount_balances_response

    try:
        resp = kalshi_prod_request(user_no, "GET", "/portfolio/subaccounts/balances")
        resp.raise_for_status()
        raw = resp.json()
    except Exception:
        return None

    normalized = normalize_kalshi_subaccount_balances_response(raw)
    out: dict[int, dict] = {}
    for row in normalized.get("subaccount_balances") or []:
        num = row.get("subaccount_number")
        bal = row.get("balance")
        if num is None or bal is None:
            continue
        try:
            n = int(num)
            cents = int(bal)
            ex = int(row.get("exchange_index") if row.get("exchange_index") is not None else 0)
        except (TypeError, ValueError):
            continue
        slot = out.setdefault(n, {"balance_cents": 0, "exchange_balances_cents": {}})
        slot["balance_cents"] = int(slot["balance_cents"]) + cents
        ex_map = slot["exchange_balances_cents"]
        ex_map[ex] = int(ex_map.get(ex, 0)) + cents
        if ex < 0 or ex > 3:
            logger.warning(
                "Kalshi subaccount %s has exchange_index=%s outside exchange_0..3 columns (user %s)",
                n,
                ex,
                user_no,
            )
    return out if out else None


def fetch_subaccount_balances_cents_map(user_no: str) -> dict[int, int] | None:
    """
    GET /portfolio/subaccounts/balances; normalize dollar ``balance`` strings to integer cents.

    Returns ``{kalshi_subaccount_number: balance_cents}`` summed across exchange shards,
    or ``None`` if credentials missing or the request fails.
    """
    matrix = fetch_subaccount_balances_matrix(user_no)
    if matrix is None:
        return None
    return {int(n): int(v["balance_cents"]) for n, v in matrix.items()}


def fetch_subaccount_transferable_cents(
    user_no: str,
    subaccount_number: int,
    *,
    exchange_index: int = 0,
) -> int | None:
    """
    Largest whole-cent amount Kalshi will move out of ``(exchange_index, subaccount_number)``.

    Kalshi reports balances with sub-cent precision (``"3487.4972"``). Rounding that to
    348750c and transferring it is rejected with ``insufficient_balance``, so truncate:
    348749c is the real maximum. ``None`` if credentials/API fail; ``0`` if the address
    is absent from the matrix (unfunded pair) — callers distinguish fail vs empty.
    Absent credentials / request errors return ``None`` (must not guess).
    """
    from decimal import Decimal, InvalidOperation

    try:
        resp = kalshi_prod_request(user_no, "GET", "/portfolio/subaccounts/balances")
        resp.raise_for_status()
        raw = resp.json()
    except Exception:
        return None

    want_sub = int(subaccount_number)
    want_ex = int(exchange_index)
    found = False
    for row in (raw or {}).get("subaccount_balances") or []:
        if not isinstance(row, dict):
            continue
        try:
            if int(row.get("subaccount_number")) != want_sub:
                continue
            row_ex = int(row.get("exchange_index") if row.get("exchange_index") is not None else 0)
            if row_ex != want_ex:
                continue
            found = True
            # Truncate toward zero: floor of dollars*100 for positive balances.
            dollars = Decimal(str(row.get("balance")).strip())
            return int(dollars * 100)
        except (TypeError, ValueError, InvalidOperation):
            return None
    if not found:
        return 0
    return None
