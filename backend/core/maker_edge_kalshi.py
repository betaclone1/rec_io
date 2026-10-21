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
from typing import Any, Dict, List, Optional, Sequence, Tuple

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
# Dedicated keep-alive lanes so dual BID/ASK posts do not share one TLS socket.
# "misc" = cancel / list / non-hot-path; "bid" / "ask" = dual place only.
_sessions: Dict[str, requests.Session] = {}
_session_lock = threading.Lock()
_PLACE_LANES = ("bid", "ask")


@dataclass
class PlaceResult:
    """Outcome of one place attempt with wire timestamps (unix seconds)."""

    api_json: Optional[Dict[str, Any]]
    t_send: float
    t_ack: float

    @property
    def rtt_ms(self) -> float:
        return max(0.0, (self.t_ack - self.t_send) * 1000.0)


def _new_session() -> requests.Session:
    """One connection per lane — dual place must not contend on a shared pool."""
    from requests.adapters import HTTPAdapter

    sess = requests.Session()
    adapter = HTTPAdapter(pool_connections=1, pool_maxsize=1, max_retries=0)
    sess.mount("https://", adapter)
    sess.mount("http://", adapter)
    return sess


def _http_session_for_lane(lane: str) -> requests.Session:
    key = str(lane or "misc").strip().lower() or "misc"
    if key not in ("bid", "ask", "misc"):
        key = "misc"
    with _session_lock:
        sess = _sessions.get(key)
        if sess is None:
            sess = _new_session()
            _sessions[key] = sess
        return sess


def _place_lane(side: str) -> str:
    return "ask" if str(side).strip().lower() == "ask" else "bid"


def _http_session() -> requests.Session:
    """Non-place lane (cancel / list). Hot-path place uses ``_http_session_for_lane``."""
    return _http_session_for_lane("misc")


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


def warm_kalshi_http() -> None:
    """Prefetch signing material and warm TLS on bid + ask (+ misc) lanes."""
    try:
        _get_signing_material()
    except Exception as exc:
        log.warning("warm credentials failed: %s", exc)
        return

    path = "/exchange/status"
    url = f"{KALSHI_BASE_URL}{path}"

    def _warm_lane(lane: str) -> None:
        try:
            # Fresh auth per lane; establishes keep-alive on that session only.
            _http_session_for_lane(lane).get(
                url,
                headers=_auth_headers("GET", path),
                timeout=5,
            )
        except Exception as exc:
            log.warning("warm HTTP session lane=%s failed: %s", lane, exc)

    # Parallel warm so both place sockets are ready before open_time.
    from concurrent.futures import ThreadPoolExecutor, as_completed

    lanes = (*_PLACE_LANES, "misc")
    with ThreadPoolExecutor(max_workers=len(lanes), thread_name_prefix="me_warm") as pool:
        futs = [pool.submit(_warm_lane, lane) for lane in lanes]
        for fut in as_completed(futs):
            fut.result()


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
    post_only: bool = True,
    self_trade_prevention_type: str = "maker",
) -> Dict[str, Any]:
    """Build a Kalshi V2 GTC body. Maker Edge stays post-only; Taker Edge crosses."""
    count_fp = f"{float(int(count)):.2f}"
    return {
        "ticker": str(ticker).strip(),
        "client_order_id": client_order_id or str(uuid.uuid4()),
        "side": str(side).strip().lower(),
        "count": count_fp,
        "price": str(price),
        "time_in_force": "good_till_canceled",
        "self_trade_prevention_type": str(self_trade_prevention_type),
        "cancel_order_on_pause": True,
        "post_only": bool(post_only),
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


def place_limit_gtc(
    *,
    ticker: str,
    side: str,
    limit_dollars: float,
    count: int,
    subaccount: int,
    exchange_index: int = -1,
    prebuilt_price: Optional[str] = None,
    prebuilt_body_bytes: Optional[bytes] = None,
    post_only: bool = True,
    self_trade_prevention_type: str = "maker",
) -> PlaceResult:
    """Place one GTC. side is 'bid' (yes @ L) or 'ask' (no @ L).

    ``post_only=False`` lets the order cross (Taker Edge). Maker Edge passes True.

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
            post_only=post_only,
            self_trade_prevention_type=self_trade_prevention_type,
        )
        body_bytes = encode_place_body(body)
    try:
        lane = _place_lane(side)
        headers = _auth_headers("POST", path)
        t_send = time.time()
        resp = _http_session_for_lane(lane).post(
            f"{KALSHI_BASE_URL}{path}",
            headers=headers,
            data=body_bytes,
            timeout=8,
        )
        t_ack = time.time()
        log.info(
            "PLACE %s %s ct=%s @ %s (limit=%s) sa=%s lane=%s status=%s "
            "send_lag_prep_ms=%.1f rtt_ms=%.1f body=%s",
            side,
            ticker,
            count,
            price or "?",
            limit_dollars,
            subaccount,
            lane,
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
    """Maker Edge dual rest: post-only GTC."""
    return place_limit_gtc(
        ticker=ticker,
        side=side,
        limit_dollars=limit_dollars,
        count=count,
        subaccount=subaccount,
        exchange_index=exchange_index,
        prebuilt_price=prebuilt_price,
        prebuilt_body_bytes=prebuilt_body_bytes,
        post_only=True,
        self_trade_prevention_type="maker",
    )


def list_resting_orders(*, subaccount: int, limit: int = 100) -> List[Dict[str, Any]]:
    """GET resting portfolio orders for a subaccount (empty list on failure)."""
    path = "/portfolio/orders"
    url = (
        f"{KALSHI_BASE_URL}{path}"
        f"?status=resting&limit={int(limit)}&subaccount={int(subaccount)}"
    )
    try:
        resp = _http_session().get(
            url, headers=_auth_headers("GET", path), timeout=8
        )
        if resp.status_code != 200:
            log.warning(
                "list resting orders sa=%s status=%s body=%s",
                subaccount,
                resp.status_code,
                (resp.text or "")[:300],
            )
            return []
        data = resp.json() if resp.text else {}
        orders = data.get("orders") if isinstance(data, dict) else None
        if not isinstance(orders, list):
            return []
        return [o for o in orders if isinstance(o, dict)]
    except Exception as exc:
        log.warning("list resting orders sa=%s failed: %s", subaccount, exc)
        return []


def _order_created_key(order: Dict[str, Any]) -> str:
    return str(order.get("created_time") or order.get("created_ts") or "")


def _order_limit_dollars(order: Dict[str, Any]) -> Optional[float]:
    """Internal limit L for a Maker Edge style rest (yes@L bid or no@L ask)."""
    book = str(order.get("book_side") or "").strip().lower()
    try:
        if book == "bid":
            return float(order.get("yes_price_dollars"))
        if book == "ask":
            # ASK @ L is buy-no @ L → no_price_dollars == L
            np = order.get("no_price_dollars")
            if np is not None:
                return float(np)
            yp = order.get("yes_price_dollars")
            if yp is not None:
                return float(Decimal("1") - Decimal(str(yp)))
    except (TypeError, ValueError, InvalidOperation):
        return None
    return None


def select_oldest_me_dual_rests(
    orders: Sequence[Dict[str, Any]],
    *,
    market_ticker: str,
    limit_dollars: float,
    price_tol: float = 1e-6,
) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]], List[str]]:
    """Pick oldest BID and ASK rests at ``limit_dollars``; cancel ids are the rest.

    Queue priority: older orders win. When deduping, always cancel newer ids.
    Returns ``(keep_bid, keep_ask, cancel_order_ids)``.
    """
    ticker = str(market_ticker or "").strip()
    bids: List[Dict[str, Any]] = []
    asks: List[Dict[str, Any]] = []
    for o in orders:
        if str(o.get("ticker") or "").strip() != ticker:
            continue
        L = _order_limit_dollars(o)
        if L is None or abs(L - float(limit_dollars)) > price_tol:
            continue
        book = str(o.get("book_side") or "").strip().lower()
        if book == "bid":
            bids.append(o)
        elif book == "ask":
            asks.append(o)
    bids.sort(key=_order_created_key)
    asks.sort(key=_order_created_key)
    keep_bid = bids[0] if bids else None
    keep_ask = asks[0] if asks else None
    cancel_ids: List[str] = []
    for o in bids[1:] + asks[1:]:
        oid = str(o.get("order_id") or "").strip()
        if oid:
            cancel_ids.append(oid)
    return keep_bid, keep_ask, cancel_ids


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
