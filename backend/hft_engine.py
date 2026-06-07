"""
HFT Engine v2 — paired post-only entry; surviving leg is the close.

Flat: ACQUISITION places bid+ask at touch (ENTRY). One fill keeps the other leg
as the resting close, pinned to best bid/ask. Exchange cancel on a leg re-joins
that side at touch. Ripcord (>=3c loss): cancel all resting, market flatten, flat.

Gates: TTC > 120s, buffer % > 0.025%. No momentum.

Run:  python -m backend.hft_engine
"""

from __future__ import annotations

import base64
import json
import logging
import os
import sys
import time
import uuid
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

import requests
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from dotenv import dotenv_values

from backend.core.port_config import get_port
from backend.core.live_state_cache import (
    UPDATED_CHANNEL,
    get_strike_ladder,
    redis_client_optional,
)
from backend.core.trade_monitor_orderbook_keys import trade_monitor_orderbook_redis_key
from backend.core.kalshi_event_market_readiness import market_row_has_usable_strike_inputs
from backend.core.live_state_kalshi_portfolio import tenant_kalshi_positions_key
from backend.util.paths import get_kalshi_credentials_dir

EST = ZoneInfo("America/New_York")
try:
    HFT_PORT = get_port("hft_engine")
except Exception:
    HFT_PORT = 8060

KALSHI_BASE_URL = "https://external-api.kalshi.com/trade-api/v2"
HFT_CONTROL_KEY = "rec_io:hft:control"
HFT_STATE_KEY = "rec_io:hft:state"

MIN_TTC_SEC = 120.0
MIN_BUFFER_PCT = float(os.getenv("HFT_MIN_BUFFER_PCT", "0.025"))
MAX_LOSS_CENTS = Decimal(os.getenv("HFT_MAX_LOSS_CENTS", "0.03"))
MIN_SUBMIT_PRICE = Decimal("0.10")
MAX_SUBMIT_PRICE = Decimal("0.999")
AMEND_INTERVAL_SEC = float(os.getenv("HFT_ENTRY_AMEND_INTERVAL_SEC", "0.2"))


def _clamp_kalshi_submit_price(price: Decimal) -> Decimal:
    p = price.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
    if p < MIN_SUBMIT_PRICE:
        return MIN_SUBMIT_PRICE
    if p > MAX_SUBMIT_PRICE:
        return MAX_SUBMIT_PRICE
    return p


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------


def _configure_logging() -> logging.Logger:
    lgr = logging.getLogger("hft_engine")
    if lgr.handlers:
        return lgr

    class _ESTFormatter(logging.Formatter):
        def formatTime(self, record, datefmt=None):
            dt = datetime.fromtimestamp(record.created, tz=EST)
            return dt.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3]

    fmt = _ESTFormatter(fmt="%(asctime)s %(levelname)s [hft] %(message)s")
    stdout_h = logging.StreamHandler(sys.stdout)
    stdout_h.setFormatter(fmt)
    lgr.addHandler(stdout_h)

    log_dir = Path(__file__).resolve().parent.parent / "logs"
    log_dir.mkdir(exist_ok=True)
    from logging.handlers import RotatingFileHandler

    file_h = RotatingFileHandler(
        log_dir / "hft_engine.log", maxBytes=10 * 1024 * 1024, backupCount=5,
    )
    file_h.setFormatter(fmt)
    lgr.addHandler(file_h)
    lgr.setLevel(logging.INFO)
    return lgr


log = _configure_logging()

# ---------------------------------------------------------------------------
# Kalshi API
# ---------------------------------------------------------------------------

_cached_credentials: Optional[Dict[str, Any]] = None
_cached_private_key = None


def _load_credentials() -> Dict[str, Any]:
    global _cached_credentials
    if _cached_credentials:
        return _cached_credentials
    cred_dir = Path(get_kalshi_credentials_dir()) / "prod"
    env_vars = dotenv_values(cred_dir / ".env")
    _cached_credentials = {
        "KEY_ID": env_vars.get("KALSHI_API_KEY_ID"),
        "KEY_PATH": str(cred_dir / "kalshi.pem"),
    }
    return _cached_credentials


def _get_private_key():
    global _cached_private_key
    if _cached_private_key:
        return _cached_private_key
    creds = _load_credentials()
    with open(creds["KEY_PATH"], "rb") as f:
        _cached_private_key = serialization.load_pem_private_key(
            f.read(), password=None, backend=default_backend(),
        )
    return _cached_private_key


def _sign(method: str, full_path: str, timestamp_ms: str) -> str:
    pk = _get_private_key()
    message = f"{timestamp_ms}{method.upper()}{full_path}".encode("utf-8")
    sig = pk.sign(
        message,
        padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.DIGEST_LENGTH),
        hashes.SHA256(),
    )
    return base64.b64encode(sig).decode("utf-8")


def _auth_headers(method: str, path: str) -> Dict[str, str]:
    creds = _load_credentials()
    ts = str(int(time.time() * 1000))
    full_path = f"/trade-api/v2{path}"
    return {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "KALSHI-ACCESS-KEY": creds["KEY_ID"],
        "KALSHI-ACCESS-TIMESTAMP": ts,
        "KALSHI-ACCESS-SIGNATURE": _sign(method, full_path, ts),
    }


def kalshi_batch_create_orders(orders: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    path = "/portfolio/events/orders/batched"
    url = f"{KALSHI_BASE_URL}{path}"
    headers = _auth_headers("POST", path)
    t0 = time.monotonic()
    try:
        resp = requests.post(url, headers=headers, json={"orders": orders}, timeout=5)
        log.info(
            "BATCH_ORDER n=%d status=%d elapsed=%.1fms",
            len(orders), resp.status_code, (time.monotonic() - t0) * 1000,
        )
        if resp.status_code in (200, 201):
            return resp.json()
        log.info("BATCH_ORDER body=%s", resp.text[:1500])
        return None
    except Exception as exc:
        log.error("BATCH_ORDER failed: %s", exc)
        return None


def kalshi_place_limit_order(
    *,
    ticker: str,
    side: str,
    price: str,
    count: str,
    subaccount: int,
    post_only: bool = True,
) -> Optional[Dict[str, Any]]:
    try:
        price = f"{_clamp_kalshi_submit_price(Decimal(str(price))):.4f}"
    except Exception:
        return None
    path = "/portfolio/events/orders"
    url = f"{KALSHI_BASE_URL}{path}"
    body: Dict[str, Any] = {
        "ticker": ticker,
        "client_order_id": str(uuid.uuid4()),
        "side": side,
        "count": count,
        "price": price,
        "time_in_force": "good_till_canceled",
        "self_trade_prevention_type": "taker_at_cross",
        "cancel_order_on_pause": True,
        "subaccount": subaccount,
    }
    if post_only:
        body["post_only"] = True
    try:
        resp = requests.post(url, headers=_auth_headers("POST", path), json=body, timeout=5)
        log.info(
            "PLACE %s %s @ %s status=%d body=%s",
            side, count, price, resp.status_code, resp.text[:800],
        )
        if resp.status_code in (200, 201):
            return resp.json()
        return None
    except Exception as exc:
        log.error("PLACE failed: %s", exc)
        return None


def kalshi_amend_order(
    order_id: str,
    *,
    ticker: str,
    side: str,
    price: str,
    count: str,
    subaccount: int,
) -> Optional[Dict[str, Any]]:
    path = f"/portfolio/events/orders/{order_id}/amend"
    url = f"{KALSHI_BASE_URL}{path}?subaccount={subaccount}"
    try:
        price = f"{_clamp_kalshi_submit_price(Decimal(str(price))):.4f}"
    except Exception:
        return None
    body = {"ticker": ticker, "side": side, "price": price, "count": count}
    try:
        resp = requests.post(
            url, headers=_auth_headers("POST", path), json=body, timeout=5,
        )
        log.info("AMEND %s %s @ %s status=%d", order_id, side, price, resp.status_code)
        if resp.status_code == 200:
            return resp.json()
        log.info("AMEND body=%s", resp.text[:800])
        return None
    except Exception as exc:
        log.error("AMEND failed: %s", exc)
        return None


def kalshi_market_order(
    *, ticker: str, side: str, count: str, subaccount: int,
) -> Optional[Dict[str, Any]]:
    path = "/portfolio/events/orders"
    url = f"{KALSHI_BASE_URL}{path}"
    body = {
        "ticker": ticker,
        "client_order_id": str(uuid.uuid4()),
        "side": side,
        "count": count,
        "price": (
            f"{MAX_SUBMIT_PRICE:.4f}" if side == "bid" else f"{MIN_SUBMIT_PRICE:.4f}"
        ),
        "time_in_force": "fill_or_kill",
        "self_trade_prevention_type": "maker",
        "cancel_order_on_pause": True,
        "subaccount": subaccount,
    }
    try:
        resp = requests.post(
            url, headers=_auth_headers("POST", path), json=body, timeout=5,
        )
        log.info("RIPCORD %s %s status=%d body=%s", side, count, resp.status_code, resp.text[:800])
        if resp.status_code in (200, 201):
            return resp.json()
        return None
    except Exception as exc:
        log.error("RIPCORD failed: %s", exc)
        return None


def kalshi_cancel_order(order_id: str, *, subaccount: int = 2) -> bool:
    path = f"/portfolio/events/orders/{order_id}"
    url = f"{KALSHI_BASE_URL}{path}?subaccount={subaccount}"
    try:
        resp = requests.delete(url, headers=_auth_headers("DELETE", path), timeout=5)
        log.info("CANCEL %s status=%d", order_id, resp.status_code)
        return resp.status_code in (200, 204)
    except Exception as exc:
        log.error("CANCEL %s failed: %s", order_id, exc)
        return False


# ---------------------------------------------------------------------------
# State machine (v2)
# ---------------------------------------------------------------------------


class HFTState(str, Enum):
    ACQUISITION = "ACQUISITION"  # flat, no entry legs resting
    ENTRY = "ENTRY"              # flat, bid+ask resting for fill
    CLOSING = "CLOSING"          # position open


class HFTEngine:
    """Minimal HFT: dual post-only entry at touch, close at touch, 3c ripcord."""

    def __init__(self, *, user_no: str = "0001", symbol: str = "BTC", market: str = "15m"):
        self.user_no = user_no
        self.symbol = symbol.upper()
        self.market = market
        self.state = HFTState.ACQUISITION
        self.last_eval_mono = 0.0
        self._last_amend_bid_mono = 0.0
        self._last_amend_ask_mono = 0.0

        self.active_ticker: Optional[str] = None
        self.gate_ttc: Optional[float] = None
        self.gate_buffer_pct: Optional[float] = None
        self.gate_best_bid: Optional[str] = None
        self.gate_best_ask: Optional[str] = None
        self.gates_pass = False
        self.gate_block_reason: Optional[str] = None

        self.my_bid_oid: Optional[str] = None
        self.my_ask_oid: Optional[str] = None
        self.submitted_bid_price: Optional[Decimal] = None
        self.submitted_ask_price: Optional[Decimal] = None

        self.entry_price: Optional[Decimal] = None
        self.entry_side: Optional[str] = None  # "long" | "short"

        self.control_neutral_mode = False

    # -- Control / state ----------------------------------------------------

    def _read_control(self, r) -> Dict[str, Any]:
        defaults = {
            "enabled": False,
            "subaccount": 2,
            "count": "1.00",
            "neutral_mode": False,
        }
        raw = r.get(HFT_CONTROL_KEY)
        if not raw:
            return dict(defaults)
        try:
            return {**defaults, **json.loads(raw)}
        except (json.JSONDecodeError, TypeError):
            return dict(defaults)

    def _write_state(self, r) -> None:
        close_side = None
        if self.entry_side == "long":
            close_side = "ask"
        elif self.entry_side == "short":
            close_side = "bid"
        payload = {
            "state": self.state.value,
            "symbol": self.symbol,
            "market": self.market,
            "active_ticker": self.active_ticker,
            "gate_ttc": self.gate_ttc,
            "gate_buffer_pct": self.gate_buffer_pct,
            "gate_min_buffer_pct": MIN_BUFFER_PCT,
            "gate_buffer_ok": (
                self.gate_buffer_pct is not None
                and float(self.gate_buffer_pct) > MIN_BUFFER_PCT
            ),
            "gate_mom_1m": None,
            "gate_best_bid": self.gate_best_bid,
            "gate_best_ask": self.gate_best_ask,
            "my_bid_oid": self.my_bid_oid,
            "my_ask_oid": self.my_ask_oid,
            "counter_oid": self._close_oid(),
            "trade_mode": "v2_simple",
            "entry_price": str(self.entry_price) if self.entry_price else None,
            "entry_side": self.entry_side,
            "gates_pass": self.gates_pass,
            "gate_block_reason": self.gate_block_reason,
            "neutral_mode": self.control_neutral_mode,
            "in_cooldown": False,
            "seeking_resting_close": (
                self.state == HFTState.CLOSING and not self._close_oid()
            ),
            "seeking_close_side": close_side,
            "updated_at": datetime.now(EST).isoformat(),
        }
        try:
            r.setex(HFT_STATE_KEY, 120, json.dumps(payload))
        except Exception:
            pass

    def _clear_orders(self) -> None:
        self.my_bid_oid = None
        self.my_ask_oid = None
        self.submitted_bid_price = None
        self.submitted_ask_price = None

    def _close_oid(self) -> Optional[str]:
        if self.entry_side == "long":
            return self.my_ask_oid
        if self.entry_side == "short":
            return self.my_bid_oid
        return None

    def _close_side(self) -> Optional[str]:
        if self.entry_side == "long":
            return "ask"
        if self.entry_side == "short":
            return "bid"
        return None

    def _cancel_all_resting(self, subaccount: int) -> None:
        seen: set[str] = set()
        for oid in (self.my_bid_oid, self.my_ask_oid):
            if oid and oid not in seen:
                kalshi_cancel_order(oid, subaccount=subaccount)
                seen.add(oid)
        self._clear_orders()

    def _cancel_oid_if_resting(
        self, r, oid: Optional[str], subaccount: int,
    ) -> None:
        if not oid:
            return
        st = self._order_status(r, oid)
        if st in (None, "resting"):
            kalshi_cancel_order(oid, subaccount=subaccount)

    @staticmethod
    def _contract_limit(count: str) -> float:
        try:
            return max(0.0, float(count))
        except (TypeError, ValueError):
            return 1.0

    def _position_over_limit(self, position: float, count: str) -> bool:
        limit = self._contract_limit(count)
        return abs(position) > limit + 0.001

    def _force_cancel_oid(self, oid: Optional[str], subaccount: int) -> None:
        if oid:
            kalshi_cancel_order(oid, subaccount=subaccount)

    def _enforce_no_entry_legs_when_positioned(
        self,
        position: float,
        subaccount: int,
    ) -> None:
        """Never leave entry-side resting orders open while positioned."""
        if position > 0 and self.my_bid_oid:
            log.warning(
                "INVARIANT cancel entry bid (long pos) oid=%s", self.my_bid_oid,
            )
            self._force_cancel_oid(self.my_bid_oid, subaccount)
            self.my_bid_oid = None
            self.submitted_bid_price = None
        elif position < 0 and self.my_ask_oid:
            log.warning(
                "INVARIANT cancel entry ask (short pos) oid=%s", self.my_ask_oid,
            )
            self._force_cancel_oid(self.my_ask_oid, subaccount)
            self.my_ask_oid = None
            self.submitted_ask_price = None

    # -- Market data --------------------------------------------------------

    def _resolve_active_contract(self) -> tuple[Optional[str], Optional[Dict[str, Any]]]:
        from backend.core import live_state_cache
        from backend.core.market_watchdog.venues.kalshi.schedule import clock_current_15m_ticker

        mkt = live_state_cache.get_market_data("kalshi", self.market, self.symbol)
        if not mkt:
            return None, None
        markets = mkt.get("markets") or []
        if self.market == "15m":
            want = clock_current_15m_ticker(self.symbol, time.time())
            for m in markets:
                if not isinstance(m, dict):
                    continue
                t = str(m.get("ticker") or "").strip()
                if t == want and market_row_has_usable_strike_inputs(m):
                    return want, m
            return want, None
        for m in markets:
            if not isinstance(m, dict):
                continue
            t = str(m.get("ticker") or "").strip()
            if t and market_row_has_usable_strike_inputs(m):
                return t, m
        return None, None

    @staticmethod
    def _buffer_pct(floor_strike: float, spot: Optional[float]) -> Optional[float]:
        if spot is None or float(spot) <= 0:
            return None
        return abs(float(floor_strike) - float(spot)) / float(spot) * 100.0

    def _read_strike_data(self) -> Optional[Dict[str, Any]]:
        env = get_strike_ladder("kalshi", self.market, self.symbol)
        if not env:
            return None
        data = env.get("data") if isinstance(env, dict) else None
        if not data:
            return None
        meta = data.get("meta") or {}
        ttc = meta.get("ttc") or meta.get("ttc_seconds")
        if ttc is None:
            return None
        ticker, market_row = self._resolve_active_contract()
        if not ticker or not isinstance(market_row, dict):
            return None
        try:
            fs = float(market_row["floor_strike"])
        except (TypeError, ValueError):
            return None
        try:
            spot = float(meta.get("current_price")) if meta.get("current_price") else None
        except (TypeError, ValueError):
            spot = None
        buf = self._buffer_pct(fs, spot)
        return {"ttc": float(ttc), "buffer_pct": buf, "ticker": ticker}

    def _read_orderbook(self, ticker: str) -> Optional[Dict[str, Any]]:
        r = redis_client_optional()
        if not r:
            return None
        raw = r.get(trade_monitor_orderbook_redis_key(ticker))
        if not raw:
            return None
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return None

    @staticmethod
    def _best_bid_ask(ob: Dict[str, Any]) -> tuple[Optional[Decimal], Optional[Decimal]]:
        yes_levels = ob.get("yes") or {}
        no_levels = ob.get("no") or {}
        best_bid = None
        for p_str in yes_levels:
            try:
                p = Decimal(p_str)
                if best_bid is None or p > best_bid:
                    best_bid = p
            except Exception:
                continue
        best_ask = None
        for p_str in no_levels:
            try:
                c = Decimal("1") - Decimal(p_str)
                if c > 0 and (best_ask is None or c < best_ask):
                    best_ask = c
            except Exception:
                continue
        return best_bid, best_ask

    def _read_position(self, r, ticker: str, subaccount: int) -> float:
        key = tenant_kalshi_positions_key(self.user_no)
        field = f"{ticker}:{subaccount}"
        try:
            raw = r.hget(key, field)
            if not raw:
                return 0.0
            return float(json.loads(raw).get("position_fp") or 0)
        except Exception:
            return 0.0

    def _order_status(self, r, oid: Optional[str]) -> Optional[str]:
        if not oid or not r:
            return None
        from backend.core.live_state_kalshi_portfolio import tenant_kalshi_orders_key
        try:
            raw = r.hget(tenant_kalshi_orders_key(self.user_no), oid)
            if not raw:
                return None
            return str(json.loads(raw).get("status") or "").lower() or None
        except Exception:
            return None

    @staticmethod
    def _touch(side: str, best_bid: Decimal, best_ask: Decimal) -> Decimal:
        raw = best_bid if side == "bid" else best_ask
        return raw.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    # -- Gates ----------------------------------------------------------------

    def _check_gates(self, strike_data: Optional[Dict[str, Any]]) -> bool:
        self.gate_block_reason = None
        if not strike_data:
            self.gate_block_reason = "strike_pending"
            return False
        ttc = strike_data.get("ttc")
        if ttc is None or float(ttc) <= MIN_TTC_SEC:
            self.gate_block_reason = "ttc_below_120s"
            return False
        buf = strike_data.get("buffer_pct")
        try:
            buf_f = float(buf) if buf is not None else None
        except (TypeError, ValueError):
            buf_f = None
        if buf_f is None or buf_f <= MIN_BUFFER_PCT:
            self.gate_block_reason = "buffer_below_min"
            return False
        return True

    # -- Actions ------------------------------------------------------------

    def _amend_if_misaligned(
        self,
        ticker: str,
        *,
        oid: str,
        side: str,
        tracked: Optional[Decimal],
        best_bid: Decimal,
        best_ask: Decimal,
        count: str,
        subaccount: int,
        label: str,
    ) -> bool:
        """True if this tick performed an amend."""
        touch = self._touch(side, best_bid, best_ask)
        touch = _clamp_kalshi_submit_price(touch)
        if tracked is not None:
            if touch == tracked.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP):
                return False
        last_mono = (
            self._last_amend_bid_mono if side == "bid" else self._last_amend_ask_mono
        )
        if time.monotonic() - last_mono < AMEND_INTERVAL_SEC:
            return False
        result = kalshi_amend_order(
            oid, ticker=ticker, side=side, price=f"{touch:.4f}",
            count=count, subaccount=subaccount,
        )
        if result is None:
            return False
        now = time.monotonic()
        if side == "bid":
            self._last_amend_bid_mono = now
        else:
            self._last_amend_ask_mono = now
        log.info("%s amend %s -> %s", label, tracked, touch)
        if side == "bid":
            self.submitted_bid_price = touch
        else:
            self.submitted_ask_price = touch
        return True

    def _rejoin_leg(
        self,
        ticker: str,
        side: str,
        best_bid: Decimal,
        best_ask: Decimal,
        count: str,
        subaccount: int,
    ) -> bool:
        """Place post-only at touch after exchange canceled this leg."""
        touch = _clamp_kalshi_submit_price(self._touch(side, best_bid, best_ask))
        result = kalshi_place_limit_order(
            ticker=ticker, side=side, price=f"{touch:.4f}",
            count=count, subaccount=subaccount, post_only=True,
        )
        if not result or float(result.get("remaining_count", "0")) < 0.001:
            log.info("REJOIN %s did not rest @ %s", side, touch)
            return False
        oid = result.get("order_id")
        if side == "bid":
            self.my_bid_oid = oid
            self.submitted_bid_price = touch
        else:
            self.my_ask_oid = oid
            self.submitted_ask_price = touch
        log.info("REJOIN %s oid=%s @ %s", side, oid, touch)
        return True

    def _place_entry_pair(
        self,
        ticker: str,
        best_bid: Decimal,
        best_ask: Decimal,
        count: str,
        subaccount: int,
    ) -> bool:
        bid_p = _clamp_kalshi_submit_price(
            best_bid.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
        ask_p = _clamp_kalshi_submit_price(
            best_ask.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
        if bid_p >= ask_p:
            log.info("ENTRY skip: bid %s >= ask %s", bid_p, ask_p)
            return False
        base = {
            "ticker": ticker,
            "count": count,
            "time_in_force": "good_till_canceled",
            "self_trade_prevention_type": "taker_at_cross",
            "post_only": True,
            "cancel_order_on_pause": True,
            "subaccount": subaccount,
        }
        orders = [
            {**base, "client_order_id": str(uuid.uuid4()), "side": "bid", "price": f"{bid_p:.4f}"},
            {**base, "client_order_id": str(uuid.uuid4()), "side": "ask", "price": f"{ask_p:.4f}"},
        ]
        result = kalshi_batch_create_orders(orders)
        if not result or not isinstance(result.get("orders"), list):
            return False
        resp = result["orders"]
        bid_ok = len(resp) > 0 and not resp[0].get("error")
        ask_ok = len(resp) > 1 and not resp[1].get("error")
        if bid_ok:
            self.my_bid_oid = resp[0].get("order_id")
            self.submitted_bid_price = bid_p
        if ask_ok:
            self.my_ask_oid = resp[1].get("order_id")
            self.submitted_ask_price = ask_p
        if not self.my_bid_oid and not self.my_ask_oid:
            return False
        self.state = HFTState.ENTRY
        log.info(
            "ACQUISITION -> ENTRY bid_oid=%s ask_oid=%s bid=%s ask=%s",
            self.my_bid_oid, self.my_ask_oid, bid_p, ask_p,
        )
        return True

    def _loss_cents(self, position: float, best_bid: Decimal, best_ask: Decimal) -> Optional[Decimal]:
        if self.entry_price is None or abs(position) < 0.001:
            return None
        if position > 0:
            return self.entry_price - best_bid
        return best_ask - self.entry_price

    def _ripcord(
        self,
        ticker: str,
        position: float,
        count: str,
        subaccount: int,
        *,
        reason: str = "loss",
    ) -> None:
        log.warning(
            "RIPCORD (%s) position=%.2f limit=%s entry=%s",
            reason, position, count, self.entry_price,
        )
        self._cancel_all_resting(subaccount)
        side = "ask" if position > 0 else "bid"
        abs_pos = abs(position)
        exit_count = count if abs_pos <= float(count) + 0.001 else f"{abs_pos:.2f}"
        kalshi_market_order(
            ticker=ticker, side=side, count=exit_count, subaccount=subaccount,
        )
        self._clear_orders()
        self.entry_price = None
        self.entry_side = None
        self.state = HFTState.ACQUISITION

    def _transition_to_closing(
        self,
        position: float,
        r,
        best_bid: Decimal,
        best_ask: Decimal,
        subaccount: int,
    ) -> None:
        """One entry leg filled: keep the other leg as the close; drop entry leg."""
        if position > 0:
            self.entry_side = "long"
            self.entry_price = self.submitted_bid_price or best_bid
            self._force_cancel_oid(self.my_bid_oid, subaccount)
            self.my_bid_oid = None
            self.submitted_bid_price = None
        else:
            self.entry_side = "short"
            self.entry_price = self.submitted_ask_price or best_ask
            self._force_cancel_oid(self.my_ask_oid, subaccount)
            self.my_ask_oid = None
            self.submitted_ask_price = None
        self.state = HFTState.CLOSING
        log.info(
            "-> CLOSING position=%.2f side=%s entry=%s close_oid=%s",
            position, self.entry_side, self.entry_price, self._close_oid(),
        )

    # -- Phases ---------------------------------------------------------------

    def _run_acquisition(
        self,
        ticker: str,
        best_bid: Decimal,
        best_ask: Decimal,
        count: str,
        subaccount: int,
        *,
        position: float = 0.0,
    ) -> None:
        if abs(position) >= 0.001:
            return
        if self.my_bid_oid or self.my_ask_oid:
            return
        self._place_entry_pair(ticker, best_bid, best_ask, count, subaccount)

    def _run_entry(
        self,
        r,
        ticker: str,
        best_bid: Decimal,
        best_ask: Decimal,
        count: str,
        subaccount: int,
        *,
        position: float = 0.0,
    ) -> None:
        if abs(position) >= 0.001:
            log.warning("ENTRY skipped — position=%.2f", position)
            return

        bid_st = self._order_status(r, self.my_bid_oid) if self.my_bid_oid else None
        ask_st = self._order_status(r, self.my_ask_oid) if self.my_ask_oid else None

        if self.my_bid_oid and bid_st == "executed":
            log.info("ENTRY bid filled — ask leg is close")
            self._transition_to_closing(1.0, r, best_bid, best_ask, subaccount)
            return
        if self.my_ask_oid and ask_st == "executed":
            log.info("ENTRY ask filled — bid leg is close")
            self._transition_to_closing(-1.0, r, best_bid, best_ask, subaccount)
            return

        if self.my_bid_oid and bid_st == "canceled":
            log.info("ENTRY bid canceled — rejoin at touch")
            self.my_bid_oid = None
            self.submitted_bid_price = None
            self._rejoin_leg(ticker, "bid", best_bid, best_ask, count, subaccount)
            return
        if self.my_ask_oid and ask_st == "canceled":
            log.info("ENTRY ask canceled — rejoin at touch")
            self.my_ask_oid = None
            self.submitted_ask_price = None
            self._rejoin_leg(ticker, "ask", best_bid, best_ask, count, subaccount)
            return

        if self.my_bid_oid and bid_st in (None, "resting"):
            self._amend_if_misaligned(
                ticker, oid=self.my_bid_oid, side="bid",
                tracked=self.submitted_bid_price,
                best_bid=best_bid, best_ask=best_ask,
                count=count, subaccount=subaccount, label="entry bid",
            )

        if self.my_ask_oid and ask_st in (None, "resting"):
            self._amend_if_misaligned(
                ticker, oid=self.my_ask_oid, side="ask",
                tracked=self.submitted_ask_price,
                best_bid=best_bid, best_ask=best_ask,
                count=count, subaccount=subaccount, label="entry ask",
            )

        if not self.my_bid_oid and not self.my_ask_oid:
            log.info("ENTRY legs gone — ACQUISITION")
            self.state = HFTState.ACQUISITION

    def _run_closing(
        self,
        r,
        ticker: str,
        position: float,
        best_bid: Decimal,
        best_ask: Decimal,
        count: str,
        subaccount: int,
    ) -> None:
        if not self.entry_side:
            self._transition_to_closing(position, r, best_bid, best_ask, subaccount)

        self._enforce_no_entry_legs_when_positioned(position, subaccount)

        loss = self._loss_cents(position, best_bid, best_ask)
        if loss is not None and loss >= MAX_LOSS_CENTS:
            self._ripcord(ticker, position, count, subaccount, reason="loss")
            return

        close_side = self._close_side()
        close_oid = self._close_oid()
        if not close_side:
            return

        tracked = (
            self.submitted_ask_price if close_side == "ask" else self.submitted_bid_price
        )

        if close_oid:
            st = self._order_status(r, close_oid)
            if st == "executed":
                log.info("CLOSE filled oid=%s", close_oid)
                if close_side == "ask":
                    self.my_ask_oid = None
                    self.submitted_ask_price = None
                else:
                    self.my_bid_oid = None
                    self.submitted_bid_price = None
                return
            if st == "canceled":
                log.info("CLOSE %s canceled — rejoin at touch", close_side)
                if close_side == "ask":
                    self.my_ask_oid = None
                    self.submitted_ask_price = None
                else:
                    self.my_bid_oid = None
                    self.submitted_bid_price = None
                close_oid = None
            elif st not in (None, "resting"):
                if close_side == "ask":
                    self.my_ask_oid = None
                    self.submitted_ask_price = None
                else:
                    self.my_bid_oid = None
                    self.submitted_bid_price = None
                close_oid = None

        close_oid = self._close_oid()
        if close_oid:
            self._amend_if_misaligned(
                ticker, oid=close_oid, side=close_side,
                tracked=tracked,
                best_bid=best_bid, best_ask=best_ask,
                count=count, subaccount=subaccount, label="close",
            )
            return

        log.info("CLOSE missing — rejoin %s at touch", close_side)
        self._rejoin_leg(ticker, close_side, best_bid, best_ask, count, subaccount)

    # -- Main eval ------------------------------------------------------------

    def evaluate(self, r) -> None:
        ctrl = self._read_control(r)
        enabled = bool(ctrl.get("enabled", False))
        subaccount = int(ctrl.get("subaccount", 2))
        count = str(ctrl.get("count", "1.00"))
        self.control_neutral_mode = bool(ctrl.get("neutral_mode", False))

        strike_data = self._read_strike_data()
        prev_ticker = self.active_ticker
        if strike_data:
            self.gate_ttc = strike_data["ttc"]
            self.gate_buffer_pct = strike_data.get("buffer_pct")
            self.active_ticker = strike_data["ticker"]
        else:
            self.gate_ttc = None
            self.gate_buffer_pct = None

        ticker = self.active_ticker
        best_bid, best_ask = None, None
        if ticker:
            ob = self._read_orderbook(ticker)
            if ob:
                best_bid, best_ask = self._best_bid_ask(ob)
                self.gate_best_bid = f"{best_bid:.4f}" if best_bid else None
                self.gate_best_ask = f"{best_ask:.4f}" if best_ask else None

        position = self._read_position(r, ticker, subaccount) if ticker else 0.0
        is_flat = abs(position) < 0.001

        if prev_ticker and ticker and ticker != prev_ticker:
            log.info("Ticker roll %s -> %s: cancel all", prev_ticker, ticker)
            self._cancel_all_resting(subaccount)
            self.entry_price = None
            self.entry_side = None
            self.state = HFTState.ACQUISITION

        if strike_data and best_bid is not None and best_ask is not None:
            self.gates_pass = self._check_gates(strike_data)
        else:
            self.gates_pass = False
            self.gate_block_reason = "orderbook_pending"

        if not enabled:
            if self.state != HFTState.ACQUISITION or self.my_bid_oid or self.my_ask_oid:
                log.info("AUTO TRADE off — cancel all")
                self._cancel_all_resting(subaccount)
                self.entry_price = None
                self.entry_side = None
                self.state = HFTState.ACQUISITION
            self.gates_pass = False
            self.gate_block_reason = "auto_trade_off"
            self._finish(r)
            return

        if not strike_data or best_bid is None or best_ask is None:
            self._finish(r)
            return

        if (
            not is_flat
            and ticker
            and self._position_over_limit(position, count)
        ):
            self._ripcord(ticker, position, count, subaccount, reason="over_limit")
            self._finish(r)
            return

        if not is_flat:
            self._enforce_no_entry_legs_when_positioned(position, subaccount)
            if self.state in (HFTState.ACQUISITION, HFTState.ENTRY):
                self._transition_to_closing(
                    position, r, best_bid, best_ask, subaccount,
                )
            self._run_closing(r, ticker, position, best_bid, best_ask, count, subaccount)
            position = self._read_position(r, ticker, subaccount)
            if abs(position) < 0.001:
                log.info("CLOSING -> flat — ACQUISITION")
                self._clear_orders()
                self.entry_price = None
                self.entry_side = None
                self.state = HFTState.ACQUISITION
            self._finish(r)
            return

        if not self.gates_pass:
            if self.state == HFTState.ENTRY:
                log.info("Gates failed (%s) — cancel entry", self.gate_block_reason)
                self._cancel_all_resting(subaccount)
                self.state = HFTState.ACQUISITION
            self._finish(r)
            return

        if self.state == HFTState.CLOSING:
            if self._close_oid() or self.my_bid_oid or self.my_ask_oid:
                pos_use = position
                if is_flat and self.entry_side:
                    pos_use = 1.0 if self.entry_side == "long" else -1.0
                if self.entry_side:
                    self._run_closing(
                        r, ticker, pos_use, best_bid, best_ask, count, subaccount,
                    )
                self._finish(r)
                return
            self.entry_price = None
            self.entry_side = None
            self.state = HFTState.ACQUISITION

        if self.state == HFTState.ACQUISITION:
            self._run_acquisition(
                ticker, best_bid, best_ask, count, subaccount, position=position,
            )
        elif self.state == HFTState.ENTRY:
            self._run_entry(
                r, ticker, best_bid, best_ask, count, subaccount, position=position,
            )

        self._finish(r)

    def _finish(self, r) -> None:
        self.last_eval_mono = time.monotonic()
        self._write_state(r)


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

HFT_LOCK_KEY = "rec_io:hft:engine_lock"
HFT_LOCK_TTL = 10


def _acquire_singleton_lock(r_cmd) -> bool:
    my_pid = str(os.getpid())
    acquired = r_cmd.set(HFT_LOCK_KEY, my_pid, nx=True, ex=HFT_LOCK_TTL)
    if acquired:
        return True
    holder = r_cmd.get(HFT_LOCK_KEY)
    if holder and holder != my_pid:
        try:
            os.kill(int(holder), 0)
        except (OSError, ValueError):
            r_cmd.delete(HFT_LOCK_KEY)
            return bool(r_cmd.set(HFT_LOCK_KEY, my_pid, nx=True, ex=HFT_LOCK_TTL))
        return False
    return True


def _refresh_lock(r_cmd) -> bool:
    my_pid = str(os.getpid())
    if r_cmd.get(HFT_LOCK_KEY) == my_pid:
        r_cmd.expire(HFT_LOCK_KEY, HFT_LOCK_TTL)
        return True
    return False


def run_hft_engine():
    log.info("HFT Engine v2 starting (port=%d)", HFT_PORT)
    user_no = os.getenv("REC_USER_NO", "0001").strip()
    symbol = os.getenv("HFT_SYMBOL", "BTC").strip().upper()
    market = os.getenv("HFT_MARKET", "15m").strip().lower()

    engine = HFTEngine(user_no=user_no, symbol=symbol, market=market)
    log.info("Configured: user_no=%s symbol=%s market=%s", user_no, symbol, market)

    import redis as redis_lib

    url = os.getenv("REDIS_URL", "").strip()
    if url:
        r_sub = redis_lib.from_url(url, decode_responses=True)
        r_cmd = redis_lib.from_url(url, decode_responses=True)
    else:
        conn_kw = dict(
            host=os.getenv("REDIS_HOST", "localhost"),
            port=int(os.getenv("REDIS_PORT", "6379")),
            password=os.getenv("REDIS_PASSWORD") or None,
            decode_responses=True,
        )
        r_sub = redis_lib.Redis(**conn_kw)
        r_cmd = redis_lib.Redis(**conn_kw)

    if not _acquire_singleton_lock(r_cmd):
        log.error("Another HFT engine holds the lock. Exiting.")
        sys.exit(1)
    log.info("Singleton lock acquired (PID %d)", os.getpid())

    engine._write_state(r_cmd)
    pubsub = r_sub.pubsub()
    pubsub.subscribe(UPDATED_CHANNEL)

    relevant_kinds = {
        "orderbook", "strike_ladder", "market", "symbol",
        "kalshi_positions", "kalshi_orders", "kalshi_fills",
    }
    last_lock_refresh = time.monotonic()

    try:
        while True:
            now = time.monotonic()
            if now - last_lock_refresh > (HFT_LOCK_TTL / 2):
                if not _refresh_lock(r_cmd):
                    log.error("Lost singleton lock — exiting.")
                    break
                last_lock_refresh = now

            msg = pubsub.get_message(timeout=1.0)
            if msg and msg.get("type") == "message":
                try:
                    payload = json.loads(msg["data"])
                    if payload.get("kind", "") in relevant_kinds:
                        engine.evaluate(r_cmd)
                except (json.JSONDecodeError, TypeError):
                    pass
                except Exception:
                    log.exception("evaluate failed (pubsub)")
            elif msg is None and now - engine.last_eval_mono > 2.0:
                try:
                    engine.evaluate(r_cmd)
                except Exception:
                    log.exception("evaluate failed (heartbeat)")
    except KeyboardInterrupt:
        log.info("Shutting down")
    finally:
        r_cmd.delete(HFT_LOCK_KEY)
        pubsub.unsubscribe()
        pubsub.close()
        r_sub.close()
        r_cmd.close()


if __name__ == "__main__":
    run_hft_engine()
