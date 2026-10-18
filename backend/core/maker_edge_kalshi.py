"""
Kalshi place/cancel for Maker Edge dual rests (outside trade_executor).

BID @ L = buy yes at L; ASK @ L = buy no at L.
V2 YES-book price encoding matches trade_executor._v2_price_from_internal_side_and_limit.
"""

from __future__ import annotations

import base64
import logging
import time
import uuid
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import requests
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from dotenv import dotenv_values

log = logging.getLogger("maker_edge_kalshi")

KALSHI_BASE_URL = "https://external-api.kalshi.com/trade-api/v2"
MIN_SUBMIT = Decimal("0.0001")
MAX_SUBMIT = Decimal("0.9999")


def _load_credentials() -> Tuple[Optional[str], Optional[Path]]:
    from backend.util.paths import get_kalshi_credentials_dir

    cred_dir = Path(get_kalshi_credentials_dir()) / "prod"
    env_vars = dotenv_values(cred_dir / ".env")
    return env_vars.get("KALSHI_API_KEY_ID"), cred_dir / "kalshi.pem"


def _sign(method: str, full_path: str, timestamp: str, key_path: Path) -> str:
    with open(key_path, "rb") as key_file:
        private_key = serialization.load_pem_private_key(
            key_file.read(),
            password=None,
            backend=default_backend(),
        )
    message = f"{timestamp}{method.upper()}{full_path}".encode("utf-8")
    signature = private_key.sign(
        message,
        padding.PSS(
            mgf=padding.MGF1(hashes.SHA256()),
            salt_length=padding.PSS.DIGEST_LENGTH,
        ),
        hashes.SHA256(),
    )
    return base64.b64encode(signature).decode("utf-8")


def _auth_headers(method: str, path: str) -> Dict[str, str]:
    key_id, key_path = _load_credentials()
    if not key_id or not key_path or not Path(key_path).exists():
        raise RuntimeError("maker_edge_kalshi: missing Kalshi credentials")
    ts = str(int(time.time() * 1000))
    full_path = f"/trade-api/v2{path}"
    return {
        "KALSHI-ACCESS-KEY": key_id,
        "KALSHI-ACCESS-SIGNATURE": _sign(method, full_path, ts, Path(key_path)),
        "KALSHI-ACCESS-TIMESTAMP": ts,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def clamp_submit_price(px: Decimal) -> Decimal:
    if px < MIN_SUBMIT:
        return MIN_SUBMIT
    if px > MAX_SUBMIT:
        return MAX_SUBMIT
    return px


def v2_price_for_limit_side(*, side: str, limit_dollars: float) -> str:
    """
    side: 'bid' (yes @ L) or 'ask' (no @ L).
    Returns Kalshi V2 YES-book price string.
    """
    s = str(side).strip().lower()
    try:
        L = Decimal(str(limit_dollars))
    except (InvalidOperation, TypeError, ValueError) as e:
        raise ValueError(f"invalid limit_dollars: {limit_dollars}") from e
    if L <= 0 or L >= 1:
        raise ValueError(f"limit_dollars out of range: {L}")
    if s == "bid":
        out = L
    elif s == "ask":
        out = Decimal("1") - L
    else:
        raise ValueError(f"side must be bid or ask, got {side!r}")
    return f"{clamp_submit_price(out):.4f}"


def place_post_only_gtc(
    *,
    ticker: str,
    side: str,
    limit_dollars: float,
    count: int,
    subaccount: int,
    exchange_index: int = -1,
) -> Optional[Dict[str, Any]]:
    """Place one post-only GTC. side is 'bid' or 'ask'. Returns API JSON or None."""
    try:
        price = v2_price_for_limit_side(side=side, limit_dollars=limit_dollars)
    except ValueError as e:
        log.error("place price map failed: %s", e)
        return None
    path = "/portfolio/events/orders"
    body: Dict[str, Any] = {
        "ticker": str(ticker).strip(),
        "client_order_id": str(uuid.uuid4()),
        "side": str(side).strip().lower(),
        "count": int(count),
        "price": price,
        "time_in_force": "good_till_canceled",
        "self_trade_prevention_type": "maker",
        "cancel_order_on_pause": True,
        "post_only": True,
        "subaccount": int(subaccount),
        "exchange_index": int(exchange_index),
    }
    try:
        resp = requests.post(
            f"{KALSHI_BASE_URL}{path}",
            headers=_auth_headers("POST", path),
            json=body,
            timeout=8,
        )
        log.info(
            "PLACE %s %s ct=%s @ %s (limit=%s) sa=%s status=%s body=%s",
            side,
            ticker,
            count,
            price,
            limit_dollars,
            subaccount,
            resp.status_code,
            resp.text[:800],
        )
        if resp.status_code in (200, 201):
            return resp.json()
        return None
    except Exception as exc:
        log.error("PLACE failed: %s", exc)
        return None


def cancel_order(order_id: str, *, subaccount: int) -> bool:
    oid = str(order_id or "").strip()
    if not oid:
        return False
    path = f"/portfolio/events/orders/{oid}"
    url = f"{KALSHI_BASE_URL}{path}?subaccount={int(subaccount)}"
    try:
        resp = requests.delete(url, headers=_auth_headers("DELETE", path), timeout=8)
        log.info("CANCEL %s sa=%s status=%s", oid, subaccount, resp.status_code)
        return resp.status_code in (200, 204)
    except Exception as exc:
        log.error("CANCEL %s failed: %s", oid, exc)
        return False


def extract_order_id(api_json: Optional[Dict[str, Any]]) -> Optional[str]:
    if not api_json or not isinstance(api_json, dict):
        return None
    order = api_json.get("order") if isinstance(api_json.get("order"), dict) else api_json
    for key in ("order_id", "id"):
        val = order.get(key) if isinstance(order, dict) else None
        if val:
            return str(val).strip()
    return None
