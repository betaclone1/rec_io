"""
Kalshi place/cancel for Maker Edge dual rests (outside trade_executor).

BID @ L = buy yes at L; ASK @ L = buy no at L.
V2 YES-book price encoding matches trade_executor._v2_price_from_internal_side_and_limit.
"""

from __future__ import annotations

import base64
import json
import logging
import threading
import time
import uuid
from dataclasses import dataclass
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

_cred_lock = threading.Lock()
_cached_key_id: Optional[str] = None
_cached_private_key: Any = None
_session: Optional[requests.Session] = None
_session_lock = threading.Lock()


@dataclass
class PlaceResult:
    """Outcome of one place attempt with wire timestamps (unix seconds)."""

    api_json: Optional[Dict[str, Any]]
    t_send: float
    t_ack: float

    @property
    def rtt_ms(self) -> float:
        return max(0.0, (self.t_ack - self.t_send) * 1000.0)


def _load_credentials() -> Tuple[Optional[str], Optional[Path]]:
    from backend.util.paths import get_kalshi_credentials_dir

    cred_dir = Path(get_kalshi_credentials_dir()) / "prod"
    env_vars = dotenv_values(cred_dir / ".env")
    return env_vars.get("KALSHI_API_KEY_ID"), cred_dir / "kalshi.pem"


def _get_signing_material() -> Tuple[str, Any]:
    """Return (key_id, private_key), caching PEM parse in memory."""
    global _cached_key_id, _cached_private_key
    with _cred_lock:
        if _cached_key_id and _cached_private_key is not None:
            return _cached_key_id, _cached_private_key
        key_id, key_path = _load_credentials()
        if not key_id or not key_path or not Path(key_path).exists():
            raise RuntimeError("maker_edge_kalshi: missing Kalshi credentials")
        with open(key_path, "rb") as key_file:
            private_key = serialization.load_pem_private_key(
                key_file.read(),
                password=None,
                backend=default_backend(),
            )
        _cached_key_id = key_id
        _cached_private_key = private_key
        return _cached_key_id, _cached_private_key


def _sign(method: str, full_path: str, timestamp: str, private_key: Any) -> str:
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
    key_id, private_key = _get_signing_material()
    ts = str(int(time.time() * 1000))
    full_path = f"/trade-api/v2{path}"
    return {
        "KALSHI-ACCESS-KEY": key_id,
        "KALSHI-ACCESS-SIGNATURE": _sign(method, full_path, ts, private_key),
        "KALSHI-ACCESS-TIMESTAMP": ts,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def _http_session() -> requests.Session:
    global _session
    with _session_lock:
        if _session is None:
            _session = requests.Session()
        return _session


def warm_kalshi_http() -> None:
    """Prefetch signing material and warm TLS to Kalshi (call before open_time)."""
    try:
        _get_signing_material()
    except Exception as exc:
        log.warning("warm credentials failed: %s", exc)
        return
    try:
        # Cheap authenticated ping — establishes TCP/TLS on the pooled session.
        path = "/exchange/status"
        _http_session().get(
            f"{KALSHI_BASE_URL}{path}",
            headers=_auth_headers("GET", path),
            timeout=5,
        )
    except Exception as exc:
        log.warning("warm HTTP session failed: %s", exc)


def clamp_submit_price(px: Decimal) -> Decimal:
    if px < MIN_SUBMIT:
        return MIN_SUBMIT
    if px > MAX_SUBMIT:
        return MAX_SUBMIT
    return px


def build_place_body(
    *,
    ticker: str,
    side: str,
    price: str,
    count: int,
    subaccount: int,
    exchange_index: int = -1,
    client_order_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Build a Kalshi V2 post-only GTC body (safe to construct before open_time)."""
    count_fp = f"{float(int(count)):.2f}"
    return {
        "ticker": str(ticker).strip(),
        "client_order_id": client_order_id or str(uuid.uuid4()),
        "side": str(side).strip().lower(),
        "count": count_fp,
        "price": str(price),
        "time_in_force": "good_till_canceled",
        "self_trade_prevention_type": "maker",
        "cancel_order_on_pause": True,
        "post_only": True,
        "subaccount": int(subaccount),
        "exchange_index": int(exchange_index),
    }


def encode_place_body(body: Dict[str, Any]) -> bytes:
    """Compact JSON bytes for hot-path POST (no dumps after open_time)."""
    return json.dumps(body, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


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
    prebuilt_price: Optional[str] = None,
    prebuilt_body_bytes: Optional[bytes] = None,
) -> PlaceResult:
    """Place one post-only GTC. side is 'bid' or 'ask'.

    Prefetch path: pass ``prebuilt_body_bytes`` (and optionally ``prebuilt_price``)
    so the hot path only signs + POSTs. ``t_send`` is stamped immediately before
    the HTTP call (after auth headers are built — signing cannot be prefetched).
    """
    t0 = time.time()
    path = "/portfolio/events/orders"
    price = prebuilt_price or ""
    body_bytes = prebuilt_body_bytes
    if body_bytes is None:
        try:
            price = (
                prebuilt_price
                if prebuilt_price is not None
                else v2_price_for_limit_side(side=side, limit_dollars=limit_dollars)
            )
        except ValueError as e:
            log.error("place price map failed: %s", e)
            return PlaceResult(api_json=None, t_send=t0, t_ack=time.time())
        body = build_place_body(
            ticker=ticker,
            side=side,
            price=price,
            count=count,
            subaccount=subaccount,
            exchange_index=exchange_index,
        )
        body_bytes = encode_place_body(body)
    try:
        headers = _auth_headers("POST", path)
        t_send = time.time()
        resp = _http_session().post(
            f"{KALSHI_BASE_URL}{path}",
            headers=headers,
            data=body_bytes,
            timeout=8,
        )
        t_ack = time.time()
        log.info(
            "PLACE %s %s ct=%s @ %s (limit=%s) sa=%s status=%s send_lag_prep_ms=%.1f rtt_ms=%.1f body=%s",
            side,
            ticker,
            count,
            price or "?",
            limit_dollars,
            subaccount,
            resp.status_code,
            (t_send - t0) * 1000.0,
            (t_ack - t_send) * 1000.0,
            resp.text[:800],
        )
        if resp.status_code in (200, 201):
            return PlaceResult(api_json=resp.json(), t_send=t_send, t_ack=t_ack)
        return PlaceResult(api_json=None, t_send=t_send, t_ack=t_ack)
    except Exception as exc:
        t_ack = time.time()
        log.error("PLACE failed: %s", exc)
        return PlaceResult(api_json=None, t_send=t0, t_ack=t_ack)


def cancel_order(
    order_id: str,
    *,
    subaccount: int,
    market_ticker: Optional[str] = None,
    exchange_index: int = -1,
) -> bool:
    """Cancel a V2 event-market order.

    Kalshi shard routing requires ``market_ticker`` when ``exchange_index`` is
    omitted or -1. Without it, DELETE returns 404 and the resting sibling stays live.
    """
    oid = str(order_id or "").strip()
    if not oid:
        return False
    path = f"/portfolio/events/orders/{oid}"
    ticker = str(market_ticker or "").strip()
    params = [f"subaccount={int(subaccount)}"]
    if ticker:
        params.append(f"market_ticker={ticker}")
        params.append(f"exchange_index={int(exchange_index)}")
    elif exchange_index >= 0:
        params.append(f"exchange_index={int(exchange_index)}")
    else:
        log.error(
            "CANCEL %s refused: market_ticker required for V2 auto-route (sa=%s)",
            oid,
            subaccount,
        )
        return False
    url = f"{KALSHI_BASE_URL}{path}?{'&'.join(params)}"
    try:
        resp = _http_session().delete(
            url, headers=_auth_headers("DELETE", path), timeout=8
        )
        log.info(
            "CANCEL %s sa=%s ticker=%s status=%s body=%s",
            oid,
            subaccount,
            ticker or "-",
            resp.status_code,
            (resp.text or "")[:300],
        )
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
