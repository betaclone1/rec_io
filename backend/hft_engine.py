"""
HFT Engine -- minimal, low-latency market-making daemon.

Standalone process that subscribes to Redis hot-state updates, evaluates
gates, and fires batch orders directly to the Kalshi API.  No PG in the
hot path; no trade_executor dependency.

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
    KEY_PREFIX,
    UPDATED_CHANNEL,
    get_strike_ladder,
    redis_client_optional,
)
from backend.core.trade_monitor_orderbook_keys import trade_monitor_orderbook_redis_key
from backend.core.kalshi_event_market_readiness import market_row_has_usable_strike_inputs
from backend.core.live_state_kalshi_portfolio import (
    list_positions,
    list_orders,
    tenant_kalshi_positions_key,
    tenant_kalshi_orders_key,
)
from backend.core.strike_pipeline_health import floor_strike_vs_spot_check
from backend.strike_table_generator import strikes_equivalent
from backend.util.paths import get_kalshi_credentials_dir

EST = ZoneInfo("America/New_York")
try:
    HFT_PORT = get_port("hft_engine")
except Exception:
    HFT_PORT = 8060

KALSHI_BASE_URL = "https://external-api.kalshi.com/trade-api/v2"
HFT_CONTROL_KEY = "rec_io:hft:control"
HFT_STATE_KEY = "rec_io:hft:state"

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
# Kalshi API auth (same pattern as trade_executor)
# ---------------------------------------------------------------------------

_cached_credentials: Optional[Dict[str, Any]] = None


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


_cached_private_key = None


def _get_private_key():
    global _cached_private_key
    if _cached_private_key:
        return _cached_private_key
    creds = _load_credentials()
    with open(creds["KEY_PATH"], "rb") as f:
        _cached_private_key = serialization.load_pem_private_key(
            f.read(), password=None, backend=default_backend()
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


# ---------------------------------------------------------------------------
# Kalshi API calls
# ---------------------------------------------------------------------------

def kalshi_batch_create_orders(orders: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    path = "/portfolio/events/orders/batched"
    url = f"{KALSHI_BASE_URL}{path}"
    headers = _auth_headers("POST", path)
    body = {"orders": orders}
    t0 = time.monotonic()
    try:
        resp = requests.post(url, headers=headers, json=body, timeout=5)
        elapsed_ms = (time.monotonic() - t0) * 1000
        log.info("BATCH_ORDER sent=%d status=%d elapsed=%.1fms", len(orders), resp.status_code, elapsed_ms)
        log.info("BATCH_ORDER raw_response: %s", resp.text[:2000])
        if resp.status_code in (200, 201):
            data = resp.json()
            for i, o in enumerate(data.get("orders", [])):
                req_side = orders[i].get("side", "?") if i < len(orders) else "?"
                req_price = orders[i].get("price", "?") if i < len(orders) else "?"
                log.info(
                    "BATCH_ORDER_DETAIL [%d] side=%s req_price=%s order_id=%s status=%s "
                    "fill_count=%s remaining_count=%s error=%s",
                    i, req_side, req_price,
                    o.get("order_id", "NONE"),
                    o.get("status", "NOT_IN_RESPONSE"),
                    o.get("fill_count", "?"),
                    o.get("remaining_count", "?"),
                    o.get("error", "none"),
                )
            return data
        return None
    except Exception as exc:
        log.error("BATCH_ORDER request failed: %s", exc)
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
    """Amend a resting order via V2: POST /portfolio/events/orders/{order_id}/amend."""
    path = f"/portfolio/events/orders/{order_id}/amend"
    url = f"{KALSHI_BASE_URL}{path}?subaccount={subaccount}"
    headers = _auth_headers("POST", path)
    try:
        price = f"{_clamp_kalshi_submit_price(Decimal(str(price))):.4f}"
    except Exception:
        return None
    body = {
        "ticker": ticker,
        "side": side,
        "price": price,
        "count": count,
    }
    t0 = time.monotonic()
    try:
        resp = requests.post(url, headers=headers, json=body, timeout=5)
        elapsed_ms = (time.monotonic() - t0) * 1000
        log.info(
            "AMEND order_id=%s side=%s price=%s count=%s status=%d elapsed=%.1fms body=%s",
            order_id, side, price, count, resp.status_code, elapsed_ms, resp.text[:1500],
        )
        if resp.status_code == 200:
            return resp.json()
        return None
    except Exception as exc:
        log.error("AMEND failed order_id=%s: %s", order_id, exc)
        return None


def kalshi_place_limit_order(
    *,
    ticker: str,
    side: str,
    price: str,
    count: str,
    subaccount: int,
    post_only: bool = False,
) -> Optional[Dict[str, Any]]:
    """Place a single GTC limit order via V2: POST /portfolio/events/orders."""
    try:
        price = f"{_clamp_kalshi_submit_price(Decimal(str(price))):.4f}"
    except Exception:
        return None
    path = "/portfolio/events/orders"
    url = f"{KALSHI_BASE_URL}{path}"
    headers = _auth_headers("POST", path)
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
    t0 = time.monotonic()
    try:
        resp = requests.post(url, headers=headers, json=body, timeout=5)
        elapsed_ms = (time.monotonic() - t0) * 1000
        log.info(
            "REPLACE_ORDER side=%s price=%s count=%s status=%d elapsed=%.1fms body=%s",
            side, price, count, resp.status_code, elapsed_ms, resp.text[:1500],
        )
        if resp.status_code in (200, 201):
            return resp.json()
        return None
    except Exception as exc:
        log.error("REPLACE_ORDER failed: %s", exc)
        return None


def kalshi_market_order(
    *,
    ticker: str,
    side: str,
    count: str,
    subaccount: int,
) -> Optional[Dict[str, Any]]:
    """Place an aggressive FoK order via V2 to close a position immediately."""
    path = "/portfolio/events/orders"
    url = f"{KALSHI_BASE_URL}{path}"
    headers = _auth_headers("POST", path)
    body = {
        "ticker": ticker,
        "client_order_id": str(uuid.uuid4()),
        "side": side,
        "count": count,
        "price": (
            f"{MAX_SUBMIT_PRICE:.4f}"
            if side == "bid"
            else f"{MIN_SUBMIT_PRICE:.4f}"
        ),
        "time_in_force": "fill_or_kill",
        "self_trade_prevention_type": "maker",
        "cancel_order_on_pause": True,
        "subaccount": subaccount,
    }
    t0 = time.monotonic()
    try:
        resp = requests.post(url, headers=headers, json=body, timeout=5)
        elapsed_ms = (time.monotonic() - t0) * 1000
        log.info(
            "RIPCORD_MARKET side=%s count=%s status=%d elapsed=%.1fms body=%s",
            side, count, resp.status_code, elapsed_ms, resp.text[:1500],
        )
        if resp.status_code in (200, 201):
            return resp.json()
        return None
    except Exception as exc:
        log.error("RIPCORD_MARKET failed: %s", exc)
        return None


def kalshi_cancel_order(order_id: str, *, subaccount: int = 2) -> bool:
    path = f"/portfolio/events/orders/{order_id}"
    url = f"{KALSHI_BASE_URL}{path}?subaccount={subaccount}"
    headers = _auth_headers("DELETE", path)
    try:
        resp = requests.delete(url, headers=headers, timeout=5)
        log.info(
            "CANCEL order_id=%s status=%d body=%s",
            order_id, resp.status_code, resp.text[:500],
        )
        return resp.status_code in (200, 204)
    except Exception as exc:
        log.error("CANCEL failed order_id=%s: %s", order_id, exc)
        return False


# ---------------------------------------------------------------------------
# State machine
# ---------------------------------------------------------------------------

class HFTState(str, Enum):
    IDLE = "IDLE"
    QUOTING = "QUOTING"
    CLOSING = "CLOSING"

# Per-side pause after post-only cross/reject (entry/quote re-place only; CLOSING exempt).
POST_ONLY_BACKOFF_SEC = float(os.getenv("HFT_POST_ONLY_BACKOFF_SEC", "0.15"))
# Minimum gap between directional entry amends in QUOTING (CLOSING/stop-loss exempt).
HFT_ENTRY_AMEND_INTERVAL_SEC = float(os.getenv("HFT_ENTRY_AMEND_INTERVAL_SEC", "0.2"))
# buffer_pct is in percent points (strike table): 0.025 = 0.025%, 2.5 = 2.5%.
MIN_BUFFER_PCT = float(os.getenv("HFT_MIN_BUFFER_PCT", "0.025"))
MAX_BUFFER_PCT_FOR_ENTRY = float(os.getenv("HFT_MAX_BUFFER_PCT_FOR_ENTRY", "6.0"))
ROLLOVER_SETTLE_SEC = float(os.getenv("HFT_ROLLOVER_SETTLE_SEC", "60"))
# First ~3 min of a 15m window: require real buffer buildup, not stale prior-cycle floor_strike.
ROLLOVER_FRESH_TTC_SEC = 750.0
ROLLOVER_FRESH_MIN_BUFFER_PCT = float(os.getenv("HFT_ROLLOVER_FRESH_MIN_BUFFER_PCT", "0.025"))
LADDER_BUFFER_MAX_DELTA_PCT = 0.5  # ladder vs spot/floor compute (percent points)
MIN_ENTRY_PRICE = Decimal("0.02")  # 2c — no entry below
MAX_ENTRY_PRICE = Decimal("0.98")  # 98c — no entry above
# Kalshi V2 resting/aggressive limits (10c–99.9c).
MIN_SUBMIT_PRICE = Decimal("0.10")
MAX_SUBMIT_PRICE = Decimal("0.999")


def _clamp_kalshi_submit_price(price: Decimal) -> Decimal:
    """Hard floor/cap for any price sent to Kalshi."""
    p = price.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
    if p < MIN_SUBMIT_PRICE:
        return MIN_SUBMIT_PRICE
    if p > MAX_SUBMIT_PRICE:
        return MAX_SUBMIT_PRICE
    return p


class HFTEngine:
    """Single-ticker HFT state machine with flight control."""

    DEFAULT_MAX_LOSS_CENTS = Decimal("0.03")

    def __init__(self, *, user_no: str = "0001", symbol: str = "BTC", market: str = "15m"):
        self.user_no = user_no
        self.symbol = symbol.upper()
        self.market = market
        self.state = HFTState.IDLE
        self.last_eval_mono: float = 0.0
        self.last_api_mono: float = 0.0
        self._post_only_backoff_until: Dict[str, float] = {}
        self._last_entry_amend_mono: float = 0.0
        self._startup_done: bool = False

        # Gate snapshot (updated each eval)
        self.gate_ttc: Optional[float] = None
        self.gate_buffer_pct: Optional[float] = None
        self.gate_mom_1m: Optional[float] = None
        self.gate_best_bid: Optional[str] = None
        self.gate_best_ask: Optional[str] = None
        self.active_ticker: Optional[str] = None

        # Own-order tracking (set from API responses, never from hot state)
        self.my_bid_oid: Optional[str] = None
        self.my_ask_oid: Optional[str] = None
        self.submitted_bid_price: Optional[Decimal] = None
        self.submitted_ask_price: Optional[Decimal] = None
        self.counter_oid: Optional[str] = None

        # Trade mode for current cycle
        self.trade_mode: Optional[str] = None   # "neutral" | "bullish" | "bearish"
        self.target_spread: Optional[Decimal] = None
        self.entry_order_price: Optional[Decimal] = None  # current price on entry order

        # Stop-loss tracking
        self.entry_price: Optional[Decimal] = None
        self.entry_side: Optional[str] = None  # "long" or "short"
        self.last_amend_price: Optional[Decimal] = None
        self.max_loss_cents: Decimal = self.DEFAULT_MAX_LOSS_CENTS
        self.pending_cancel_oid: Optional[str] = None
        self.awaiting_flat_after_counter: bool = False
        self.gate_floor_strike: Optional[float] = None
        self.gate_spot: Optional[float] = None
        self._last_strike_gate_reason: Optional[str] = None
        self._last_idle_skip_reason: Optional[str] = None
        self._rollover_quiet_until_mono: float = 0.0
        self._anchor_ticker: Optional[str] = None
        self._anchor_floor_strike: Optional[float] = None
        # Sides ("bid" / "ask") that must join the book after a post-only cross.
        self._post_only_catch_up_sides: set[str] = set()

    # -- Redis control plane ------------------------------------------------

    def _read_control(self, r) -> Dict[str, Any]:
        raw = r.get(HFT_CONTROL_KEY)
        if not raw:
            return {"enabled": False, "subaccount": 2, "count": "1.00", "ticker_filter": ""}
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return {"enabled": False, "subaccount": 2, "count": "1.00", "ticker_filter": ""}

    def _seeking_resting_close(self) -> bool:
        """CLOSING with no resting counter (post-only cross / cancel / awaiting-flat lag)."""
        return (
            self.state == HFTState.CLOSING
            and not self.counter_oid
            and self.entry_side is not None
        )

    def _write_state(self, r) -> None:
        seeking_close = self._seeking_resting_close()
        close_side = self._close_side() if seeking_close else None
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
            "gate_mom_1m": self.gate_mom_1m,
            "gate_best_bid": self.gate_best_bid,
            "gate_best_ask": self.gate_best_ask,
            "gate_floor_strike": self.gate_floor_strike,
            "my_bid_oid": self.my_bid_oid,
            "my_ask_oid": self.my_ask_oid,
            "counter_oid": self.counter_oid,
            "trade_mode": self.trade_mode,
            "target_spread": str(self.target_spread) if self.target_spread is not None else None,
            "entry_price": str(self.entry_price) if self.entry_price is not None else None,
            "entry_side": self.entry_side,
            "max_loss_cents": str(self.max_loss_cents),
            # Legacy UI key: short per-side backoff after post-only cross (not global API freeze).
            "in_cooldown": self._any_post_only_backoff(),
            "awaiting_flat_after_counter": self.awaiting_flat_after_counter,
            "seeking_resting_close": seeking_close,
            "seeking_close_side": close_side,
            "updated_at": datetime.now(EST).isoformat(),
        }
        try:
            r.setex(HFT_STATE_KEY, 120, json.dumps(payload))
        except Exception:
            pass

    # -- Data readers (Redis only) ------------------------------------------

    def _resolve_active_contract_from_market_cache(
        self,
    ) -> tuple[Optional[str], Optional[Dict[str, Any]]]:
        """Live Kalshi market row for the clock-current contract (floor_strike at rollover)."""
        from backend.core import live_state_cache
        from backend.core.market_watchdog.venues.kalshi.schedule import (
            clock_current_15m_ticker,
        )

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

        ready: list[tuple[str, Dict[str, Any]]] = []
        for m in markets:
            if not isinstance(m, dict):
                continue
            t = str(m.get("ticker") or "").strip()
            if t and market_row_has_usable_strike_inputs(m):
                ready.append((t, m))
        if ready:
            return ready[0]
        return None, None

    @staticmethod
    def _buffer_pct_from_floor_strike(
        floor_strike: float, spot: Optional[float],
    ) -> Optional[float]:
        """Buffer % from Kalshi floor_strike vs live symbol spot (same formula as strike table)."""
        if spot is None or float(spot) <= 0:
            return None
        try:
            fs = float(floor_strike)
        except (TypeError, ValueError):
            return None
        return abs(fs - float(spot)) / float(spot) * 100.0

    def _ladder_row_for_ticker(
        self, rows: List[Dict[str, Any]], ticker: str,
    ) -> Optional[Dict[str, Any]]:
        t = str(ticker or "").strip()
        if not t:
            return None
        for row in rows:
            if str(row.get("ticker") or "").strip() == t:
                return row
        return None

    def _read_strike_data(self) -> Optional[Dict[str, Any]]:
        env = get_strike_ladder("kalshi", self.market, self.symbol)
        if not env:
            return None
        data = env.get("data") if isinstance(env, dict) else None
        if not data or not isinstance(data, dict):
            return None
        meta = data.get("meta") or {}
        rows = data.get("rows") or []
        if not rows and isinstance(meta.get("strikes"), list):
            rows = [r for r in meta["strikes"] if isinstance(r, dict)]

        ttc = meta.get("ttc") or meta.get("ttc_seconds")
        if ttc is None:
            return None

        contract_ticker, market_row = self._resolve_active_contract_from_market_cache()
        if not contract_ticker or not isinstance(market_row, dict):
            return None
        if not market_row_has_usable_strike_inputs(market_row):
            return None
        if str(market_row.get("ticker") or "").strip() != contract_ticker:
            return None

        try:
            fs_f = float(market_row["floor_strike"])
        except (TypeError, ValueError):
            return None

        current_price = meta.get("current_price")
        try:
            cp_f = float(current_price) if current_price is not None else None
        except (TypeError, ValueError):
            cp_f = None

        buf_f = self._buffer_pct_from_floor_strike(fs_f, cp_f)
        ladder_row = self._ladder_row_for_ticker(rows, contract_ticker)
        ladder_buffer_pct = None
        if isinstance(ladder_row, dict) and ladder_row.get("buffer_pct") is not None:
            try:
                ladder_buffer_pct = float(ladder_row["buffer_pct"])
            except (TypeError, ValueError):
                ladder_buffer_pct = None

        return {
            "ttc": float(ttc),
            "buffer_pct": buf_f,
            "ladder_buffer_pct": ladder_buffer_pct,
            "ticker": contract_ticker,
            "floor_strike": fs_f,
            "current_price": cp_f,
            "market_row": market_row,
            "ladder_row": ladder_row,
        }

    def _strike_anchor_ready(self, strike_data: Dict[str, Any]) -> tuple[bool, str]:
        """
        Block trading until the active contract has Kalshi floor_strike + quotes and a
        buffer % computed from that floor_strike vs live spot (not stale ladder fields).
        """
        if time.monotonic() < self._rollover_quiet_until_mono:
            return False, "rollover_settle"

        ticker = str(strike_data.get("ticker") or "").strip()
        market_row = strike_data.get("market_row")
        if not ticker:
            return False, "no_active_ticker"
        if not isinstance(market_row, dict):
            return False, "market_cache_pending"
        if str(market_row.get("ticker") or "").strip() != ticker:
            return False, "market_ticker_mismatch"
        if not market_row_has_usable_strike_inputs(market_row):
            return False, "floor_strike_or_quotes_pending"

        floor_strike = strike_data.get("floor_strike")
        if floor_strike is None:
            return False, "no_floor_strike"
        try:
            fs = float(floor_strike)
        except (TypeError, ValueError):
            return False, "no_floor_strike"
        if fs <= 0:
            return False, "invalid_floor_strike"

        spot = strike_data.get("current_price")
        spot_f = None
        if spot is not None:
            try:
                spot_f = float(spot)
            except (TypeError, ValueError):
                spot_f = None
        if spot_f is None or spot_f <= 0:
            return False, "no_spot_for_buffer"

        buf_f = self._buffer_pct_from_floor_strike(fs, spot_f)
        if buf_f is None or buf_f <= MIN_BUFFER_PCT:
            return False, f"buffer_pct_not_ready_{buf_f or 0:.3f}_lt_{MIN_BUFFER_PCT}"
        if buf_f > MAX_BUFFER_PCT_FOR_ENTRY:
            return False, (
                f"buffer_pct_stale_anchor_{buf_f:.3f}_gt_{MAX_BUFFER_PCT_FOR_ENTRY}"
            )

        ttc = strike_data.get("ttc")
        try:
            ttc_f = float(ttc) if ttc is not None else None
        except (TypeError, ValueError):
            ttc_f = None
        if (
            self.market == "15m"
            and ttc_f is not None
            and ttc_f > ROLLOVER_FRESH_TTC_SEC
            and buf_f < ROLLOVER_FRESH_MIN_BUFFER_PCT
        ):
            return False, "rollover_fresh_contract_low_buffer"

        ok, reason, _drift = floor_strike_vs_spot_check(fs, spot_f)
        if not ok:
            return False, reason

        ladder_row = strike_data.get("ladder_row")
        if not isinstance(ladder_row, dict):
            return False, "ladder_row_pending_for_ticker"
        ladder_strike = ladder_row.get("strike")
        try:
            ls = float(ladder_strike) if ladder_strike is not None else None
        except (TypeError, ValueError):
            ls = None
        if ls is None or not strikes_equivalent(self.symbol, ls, fs):
            return False, "ladder_strike_not_aligned_with_floor"

        if self._anchor_ticker != ticker:
            self._anchor_ticker = ticker
            self._anchor_floor_strike = fs
        elif self._anchor_floor_strike is not None and abs(fs - self._anchor_floor_strike) > 0.01:
            self._anchor_floor_strike = fs

        ladder_buf = strike_data.get("ladder_buffer_pct")
        try:
            lb = float(ladder_buf) if ladder_buf is not None else None
        except (TypeError, ValueError):
            lb = None
        if lb is None or lb <= MIN_BUFFER_PCT:
            return False, "ladder_buffer_pct_not_ready"
        if abs(lb - buf_f) > LADDER_BUFFER_MAX_DELTA_PCT:
            return False, "ladder_buffer_mismatch"

        return True, "ok"

    def _log_strike_gate_block(self, reason: str, strike_data: Optional[Dict[str, Any]] = None) -> None:
        if reason != self._last_strike_gate_reason:
            self._last_strike_gate_reason = reason
            if strike_data:
                log.info(
                    "HFT gates blocked: %s (ticker=%s floor=%s spot=%s buf=%.3f%% ttc=%s)",
                    reason,
                    strike_data.get("ticker"),
                    strike_data.get("floor_strike"),
                    strike_data.get("current_price"),
                    float(strike_data.get("buffer_pct") or 0),
                    strike_data.get("ttc"),
                )
            else:
                log.info("HFT gates blocked: %s", reason)

    def _log_idle_skip(self, reason_key: str, msg: str, *args) -> None:
        """Log an IDLE entry skip once per stable reason_key (not per bid/ask tick)."""
        if reason_key == self._last_idle_skip_reason:
            return
        self._last_idle_skip_reason = reason_key
        log.info(msg, *args)

    def _clear_idle_skip_log(self) -> None:
        self._last_idle_skip_reason = None

    def _read_orderbook(self, market_ticker: str) -> Optional[Dict[str, Any]]:
        r = redis_client_optional()
        if not r:
            return None
        raw = r.get(trade_monitor_orderbook_redis_key(market_ticker))
        if not raw:
            return None
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return None
        if not isinstance(data, dict) or data.get("valid") is False:
            return None
        return data

    def _best_bid_ask(self, ob: Dict[str, Any]) -> tuple[Optional[Decimal], Optional[Decimal]]:
        """Extract best YES bid and best YES ask from the orderbook snapshot."""
        yes_levels = ob.get("yes", {})
        no_levels = ob.get("no", {})
        if not yes_levels and not no_levels:
            return None, None

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
                complement = Decimal("1") - Decimal(p_str)
                if complement > 0 and (best_ask is None or complement < best_ask):
                    best_ask = complement
            except Exception:
                continue

        return best_bid, best_ask

    def _read_momentum_1m(self) -> Optional[float]:
        r = redis_client_optional()
        if not r:
            return None
        sym_key = f"{KEY_PREFIX}:symbol:{self.symbol}"
        raw = r.get(sym_key)
        if not raw:
            return None
        try:
            env = json.loads(raw)
            data = env.get("data") if isinstance(env, dict) else None
            if not data:
                return None
            val = data.get("momentum_1m_avg")
            if val is None:
                val = data.get("momentum_percentile")
            return float(val) if val is not None else None
        except Exception:
            return None

    def _read_position(self, r, ticker: str, subaccount: int) -> float:
        key = tenant_kalshi_positions_key(self.user_no)
        field = f"{ticker}:{subaccount}"
        try:
            raw = r.hget(key, field)
            if not raw:
                return 0.0
            rec = json.loads(raw)
            fp = rec.get("position_fp")
            if fp is None:
                return 0.0
            return float(fp)
        except Exception:
            return 0.0

    def _read_resting_orders_for_ticker(self, r, ticker: str, subaccount: int) -> List[Dict[str, Any]]:
        key = tenant_kalshi_orders_key(self.user_no)
        try:
            all_raw = r.hgetall(key) or {}
        except Exception:
            return []
        resting = []
        for _oid, blob in all_raw.items():
            try:
                rec = json.loads(blob)
                if (
                    rec.get("ticker") == ticker
                    and rec.get("subaccount") == subaccount
                    and rec.get("status") == "resting"
                ):
                    resting.append(rec)
            except Exception:
                continue
        return resting

    def _check_order_status(self, r, oid: str) -> Optional[str]:
        """Single O(1) lookup: returns the order status string or None."""
        if not oid:
            return None
        key = tenant_kalshi_orders_key(self.user_no)
        try:
            blob = r.hget(key, oid)
            if not blob:
                return None
            rec = json.loads(blob)
            return rec.get("status")
        except Exception:
            return None

    def _mark_api_action(self) -> None:
        self.last_api_mono = time.monotonic()

    def _set_post_only_backoff(self, side: str) -> None:
        self._post_only_backoff_until[side] = (
            time.monotonic() + POST_ONLY_BACKOFF_SEC
        )

    def _side_in_post_only_backoff(self, side: str) -> bool:
        until = self._post_only_backoff_until.get(side, 0.0)
        now = time.monotonic()
        if now < until:
            return True
        self._post_only_backoff_until.pop(side, None)
        return False

    def _any_post_only_backoff(self) -> bool:
        now = time.monotonic()
        self._post_only_backoff_until = {
            side: until
            for side, until in self._post_only_backoff_until.items()
            if until > now
        }
        return bool(self._post_only_backoff_until)

    # -- Gate evaluation ----------------------------------------------------

    def _gates_pass(
        self,
        ttc: float,
        buffer_pct: float,
        mom_1m: Optional[float],
        strike_data: Optional[Dict[str, Any]],
    ) -> bool:
        if ttc <= 120:
            return False
        if mom_1m is None:
            return False
        if not strike_data:
            self._log_strike_gate_block("strike_ladder_pending")
            return False
        anchor_ok, reason = self._strike_anchor_ready(strike_data)
        if not anchor_ok:
            self._log_strike_gate_block(reason, strike_data)
            return False
        buf = strike_data.get("buffer_pct")
        try:
            buf_f = float(buf) if buf is not None else None
        except (TypeError, ValueError):
            buf_f = None
        if buf_f is None or buf_f <= MIN_BUFFER_PCT:
            return False
        return True

    # -- Order building -----------------------------------------------------

    @staticmethod
    def _momentum_spread(mom_1m: float) -> tuple[int, str]:
        """Return (spread_cents, mode) based on 1m momentum band.

        Modes:
          "neutral"  -- symmetric bid/ask around best bid/ask (spread 1c)
          "bullish"  -- anchor bid at best_bid, ask = bid + spread
          "bearish"  -- anchor ask at best_ask, bid = ask - spread
        """
        abs_mom = abs(mom_1m)
        if abs_mom <= 20:
            return 1, "neutral"
        if abs_mom <= 50:
            spread = 2
        elif abs_mom <= 90:
            spread = 3
        else:
            spread = 4
        return spread, ("bullish" if mom_1m > 0 else "bearish")

    def _build_mm_batch(
        self, ticker: str, best_bid: Decimal, best_ask: Decimal,
        count: str, subaccount: int, mom_1m: float,
    ) -> List[Dict[str, Any]]:
        spread_cents, mode = self._momentum_spread(mom_1m)
        spread = Decimal(spread_cents) / Decimal(100)

        if mode == "neutral":
            bid_price = best_bid.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            ask_price = best_ask.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        elif mode == "bullish":
            bid_price = best_bid.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            ask_price = (bid_price + spread).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        else:
            ask_price = best_ask.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            bid_price = (ask_price - spread).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        if bid_price <= 0 or bid_price >= Decimal("1"):
            return []
        if ask_price <= 0 or ask_price >= Decimal("1"):
            return []
        if bid_price >= ask_price:
            return []
        bid_price = _clamp_kalshi_submit_price(bid_price)
        ask_price = _clamp_kalshi_submit_price(ask_price)
        if bid_price >= ask_price:
            return []
        if not self._entry_price_allowed(bid_price) or not self._entry_price_allowed(ask_price):
            self._log_idle_skip(
                "mm_batch_entry_band",
                "IDLE: skip mm batch, bid=%s ask=%s outside entry band [%.2f, %.2f]",
                bid_price, ask_price, MIN_ENTRY_PRICE, MAX_ENTRY_PRICE,
            )
            return []

        log.info(
            "ORDER_PARAMS mode=%s mom=%.1f spread=%dc bid=%s ask=%s ticker=%s",
            mode, mom_1m, spread_cents, bid_price, ask_price, ticker,
        )

        base = {
            "ticker": ticker,
            "count": count,
            "time_in_force": "good_till_canceled",
            "self_trade_prevention_type": "taker_at_cross",
            "post_only": True,
            "cancel_order_on_pause": True,
            "subaccount": subaccount,
        }
        bid_leg = {
            **base,
            "client_order_id": str(uuid.uuid4()),
            "side": "bid",
            "price": f"{bid_price:.4f}",
        }
        ask_leg = {
            **base,
            "client_order_id": str(uuid.uuid4()),
            "side": "ask",
            "price": f"{ask_price:.4f}",
        }
        return [bid_leg, ask_leg]

    def _clear_all_order_state(self) -> None:
        self.my_bid_oid = None
        self.my_ask_oid = None
        self.submitted_bid_price = None
        self.submitted_ask_price = None
        self.counter_oid = None
        self.trade_mode = None
        self.target_spread = None
        self.entry_order_price = None
        self.entry_price = None
        self.entry_side = None
        self.last_amend_price = None
        self.pending_cancel_oid = None
        self.awaiting_flat_after_counter = False
        self._post_only_catch_up_sides.clear()
        self._post_only_backoff_until.clear()
        self._last_entry_amend_mono = 0.0

    @staticmethod
    def _max_contracts(count: str) -> float:
        try:
            return float(count)
        except (TypeError, ValueError):
            return 1.0

    @staticmethod
    def _entry_price_allowed(price: Decimal) -> bool:
        return MIN_ENTRY_PRICE <= price <= MAX_ENTRY_PRICE

    def _book_price_for_side(
        self, side: str, best_bid: Decimal, best_ask: Decimal,
    ) -> Optional[Decimal]:
        raw = best_bid if side == "bid" else best_ask
        price = raw.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        if price <= 0 or price >= Decimal("1"):
            return None
        return price

    def _limit_price_for_order(
        self,
        side: str,
        best_bid: Decimal,
        best_ask: Decimal,
        target_price: Decimal,
    ) -> Optional[Decimal]:
        if side in self._post_only_catch_up_sides:
            return self._book_price_for_side(side, best_bid, best_ask)
        return target_price

    def _mark_post_only_cross(
        self,
        side: str,
        attempted: Decimal,
        best_bid: Decimal,
        best_ask: Decimal,
        *,
        apply_backoff: bool = True,
    ) -> None:
        self._post_only_catch_up_sides.add(side)
        if apply_backoff:
            self._set_post_only_backoff(side)
        log.info(
            "Post-only cross on %s @ %s -- next attempt joins book (bid=%s ask=%s)"
            "%s",
            side,
            attempted,
            best_bid,
            best_ask,
            f" backoff={POST_ONLY_BACKOFF_SEC:.2f}s" if apply_backoff else "",
        )

    def _effective_submit_price(
        self,
        target: Decimal,
        side: str,
        best_bid: Decimal,
        best_ask: Decimal,
    ) -> Optional[Decimal]:
        """Map strategy target to a Kalshi-acceptable limit (10c–99.9c)."""
        p = target.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        if p <= 0 or p >= Decimal("1"):
            return None
        if p < MIN_SUBMIT_PRICE:
            touch = self._book_price_for_side(side, best_bid, best_ask)
            if touch is not None and MIN_SUBMIT_PRICE <= touch <= MAX_SUBMIT_PRICE:
                log.info(
                    "Submit price %s below floor %s — using book touch %s (%s)",
                    p, MIN_SUBMIT_PRICE, touch, side,
                )
                p = touch
            else:
                log.info(
                    "Submit price %s below floor %s — clamping to floor",
                    p, MIN_SUBMIT_PRICE,
                )
                p = MIN_SUBMIT_PRICE
        elif p > MAX_SUBMIT_PRICE:
            touch = self._book_price_for_side(side, best_bid, best_ask)
            if touch is not None and MIN_SUBMIT_PRICE <= touch <= MAX_SUBMIT_PRICE:
                log.info(
                    "Submit price %s above cap %s — using book touch %s (%s)",
                    p, MAX_SUBMIT_PRICE, touch, side,
                )
                p = touch
            else:
                log.info(
                    "Submit price %s above cap %s — clamping to cap",
                    p, MAX_SUBMIT_PRICE,
                )
                p = MAX_SUBMIT_PRICE
        return p

    def _place_post_only_at_price(
        self,
        *,
        ticker: str,
        side: str,
        price: Decimal,
        count: str,
        subaccount: int,
        best_bid: Decimal,
        best_ask: Decimal,
        label: str,
        exempt_post_only_backoff: bool = False,
    ) -> Optional[str]:
        """Place a post-only limit; return order_id when resting."""
        if not exempt_post_only_backoff and self._side_in_post_only_backoff(side):
            log.info(
                "%s side=%s skipped: post-only backoff %.2fs remaining",
                label,
                side,
                max(
                    0.0,
                    self._post_only_backoff_until.get(side, 0.0) - time.monotonic(),
                ),
            )
            return None
        price = self._effective_submit_price(price, side, best_bid, best_ask)
        if price is None:
            return None
        price_str = f"{price:.4f}"
        catch_up = side in self._post_only_catch_up_sides
        if catch_up:
            log.info(
                "%s side=%s price=%s post_only=True (book catch-up)",
                label, side, price_str,
            )
        else:
            log.info("%s side=%s price=%s post_only=True", label, side, price_str)
        result = kalshi_place_limit_order(
            ticker=ticker, side=side, price=price_str,
            count=count, subaccount=subaccount, post_only=True)
        self._mark_api_action()
        if result and float(result.get("remaining_count", "0")) > 0:
            self._post_only_catch_up_sides.discard(side)
            return result.get("order_id")
        self._mark_post_only_cross(
            side,
            price,
            best_bid,
            best_ask,
            apply_backoff=not exempt_post_only_backoff,
        )
        return None

    def _book_allows_entry(
        self, best_bid: Decimal, best_ask: Decimal, mom_1m: Optional[float],
    ) -> bool:
        """True if the side(s) we would quote for entry are inside [2c, 98c]."""
        _, mode = self._momentum_spread(mom_1m or 0)
        bid = best_bid.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        ask = best_ask.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        if mode == "neutral":
            return self._entry_price_allowed(bid) and self._entry_price_allowed(ask)
        if mode == "bullish":
            return self._entry_price_allowed(bid)
        return self._entry_price_allowed(ask)

    def _cancel_entry_orders(
        self, subaccount: int, *, keep_oid: Optional[str] = None,
    ) -> None:
        """Cancel resting entry legs; keep_oid is left tracked (e.g. neutral counter)."""
        cancelled = False
        for oid in (self.my_bid_oid, self.my_ask_oid):
            if not oid or oid == keep_oid:
                continue
            kalshi_cancel_order(oid, subaccount=subaccount)
            cancelled = True
        if self.my_bid_oid != keep_oid:
            self.my_bid_oid = None
        if self.my_ask_oid != keep_oid:
            self.my_ask_oid = None
        if cancelled:
            self._mark_api_action()

    def _cancel_entry_and_idle(self, subaccount: int, reason: str) -> None:
        log.info("QUOTING -> IDLE: %s", reason)
        self._cancel_entry_orders(subaccount)
        self._clear_all_order_state()
        self.state = HFTState.IDLE

    def _close_side(self) -> Optional[str]:
        """Close order side from recorded entry, not from position (avoids stale sign)."""
        if self.entry_side == "long":
            return "ask"
        if self.entry_side == "short":
            return "bid"
        return None

    def _position_matches_entry(self, position: float) -> bool:
        if self.entry_side == "long":
            return position > 0.001
        if self.entry_side == "short":
            return position < -0.001
        return False

    @staticmethod
    def _close_side_for_position(position: float) -> Optional[str]:
        if position > 0.001:
            return "ask"
        if position < -0.001:
            return "bid"
        return None

    def _unrealized_loss_cents(
        self,
        position: float,
        best_bid: Decimal,
        best_ask: Decimal,
    ) -> Optional[Decimal]:
        """Mark-to-market loss from position sign (long marks bid, short marks ask)."""
        if self.entry_price is None or abs(position) < 0.001:
            return None
        if position > 0.001:
            return self.entry_price - best_bid
        if position < -0.001:
            return best_ask - self.entry_price
        return None

    def _sync_entry_with_position(
        self,
        position: float,
        best_bid: Decimal,
        best_ask: Decimal,
    ) -> None:
        if self._position_matches_entry(position):
            return
        recovered = self._infer_entry_side(position, self.trade_mode)
        if not recovered:
            return
        log.warning(
            "Reconcile entry_side %s -> %s for position=%.2f",
            self.entry_side, recovered, position,
        )
        self.entry_side = recovered
        if recovered == "long":
            self.entry_price = self.submitted_bid_price or best_bid
        else:
            self.entry_price = self.submitted_ask_price or best_ask

    def _effective_close_side(self, position: float) -> Optional[str]:
        if self._position_matches_entry(position):
            return self._close_side()
        return self._close_side_for_position(position)

    def _maybe_ripcord_on_loss(
        self,
        ticker: str,
        position: float,
        best_bid: Decimal,
        best_ask: Decimal,
        count: str,
        subaccount: int,
        *,
        r=None,
    ) -> bool:
        """Cancel resting counter and market-flatten if loss exceeds max. Returns True if fired."""
        loss = self._unrealized_loss_cents(position, best_bid, best_ask)
        catastrophic = False
        if self.entry_price is not None:
            ep = self.entry_price
            if position > 0.001 and ep >= Decimal("0.50") and best_bid <= Decimal("0.20"):
                catastrophic = True
            elif position < -0.001 and ep <= Decimal("0.50") and best_ask >= Decimal("0.80"):
                catastrophic = True
        if loss is None and not catastrophic:
            return False
        if not catastrophic and loss is not None and loss <= self.max_loss_cents:
            return False
        log.warning(
            "RIPCORD: entry=%s position=%.2f loss=%s max=%s catastrophic=%s bid=%s ask=%s",
            self.entry_price, position, loss, self.max_loss_cents, catastrophic,
            best_bid, best_ask,
        )
        if self.counter_oid and r is not None:
            kalshi_cancel_order(self.counter_oid, subaccount=subaccount)
            self.counter_oid = None
        self._ripcord_flatten(ticker, count, subaccount, position=position)
        return True

    @staticmethod
    def _infer_entry_side_from_position(position: float) -> Optional[str]:
        if position > 0.001:
            return "long"
        if position < -0.001:
            return "short"
        return None

    def _infer_entry_side(self, position: float, trade_mode: Optional[str]) -> Optional[str]:
        """Infer long/short from position; reject mismatch with directional mode."""
        side = self._infer_entry_side_from_position(position)
        if side is None:
            return None
        if trade_mode == "bullish" and side != "long":
            return None
        if trade_mode == "bearish" and side != "short":
            return None
        return side

    def _target_counter_price(
        self, best_bid: Decimal, best_ask: Decimal,
    ) -> Optional[Decimal]:
        """Profit-taking price for directional; join book for neutral."""
        close_side = self._close_side()
        if not close_side:
            return None
        raw: Optional[Decimal] = None
        if self.entry_side == "long" and self.entry_price is not None and self.target_spread:
            raw = (self.entry_price + self.target_spread).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP)
        elif self.entry_side == "short" and self.entry_price is not None and self.target_spread:
            raw = (self.entry_price - self.target_spread).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP)
        elif self.entry_side == "long":
            raw = best_ask.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        elif self.entry_side == "short":
            raw = best_bid.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        if raw is None:
            return None
        return self._effective_submit_price(raw, close_side, best_bid, best_ask)

    def _ripcord_flatten(
        self,
        ticker: str,
        count: str,
        subaccount: int,
        *,
        position: float = 0.0,
    ) -> None:
        close_side = self._effective_close_side(position)
        if not close_side:
            log.warning("RIPCORD skipped: flat and no entry_side")
            self._clear_all_order_state()
            self.state = HFTState.IDLE
            return
        abs_pos = abs(position)
        max_c = self._max_contracts(count)
        exit_count = count
        if abs_pos > max_c + 0.001:
            exit_count = f"{abs_pos:.2f}"
            log.warning(
                "RIPCORD size %.2f contracts (config count=%s)",
                abs_pos, count,
            )
        log.warning("RIPCORD flatten side=%s position=%.2f", close_side, position)
        kalshi_market_order(
            ticker=ticker, side=close_side, count=exit_count, subaccount=subaccount)
        self._clear_all_order_state()
        self.state = HFTState.IDLE
        self._mark_api_action()

    # -- Core eval loop -----------------------------------------------------
    #
    # Architecture rules (non-negotiable):
    #   1. ONE API action per tick, then return.
    #   2. Never place a replacement order in the same tick that detected
    #      the original was gone. Clear the OID and return; next tick decides.
    #   3. Position is the single source of truth for state transitions.
    #      Order status is only used to clear OID tracking.
    #   4. Gates are re-checked every tick in QUOTING.
    #   5. No global API cooldown. Entry re-place uses per-side post-only
    #      backoff (HFT_POST_ONLY_BACKOFF_SEC). CLOSING/counter/ripcord exempt.

    def _cancel_tracked_orders(self, subaccount: int) -> None:
        for oid in (self.my_bid_oid, self.my_ask_oid, self.counter_oid):
            if oid:
                kalshi_cancel_order(oid, subaccount=subaccount)

    def evaluate(self, r) -> None:
        ctrl = self._read_control(r)
        enabled = ctrl.get("enabled", False)
        subaccount = int(ctrl.get("subaccount", 2))
        count = str(ctrl.get("count", "1.00"))

        # ---- Always read market data for UI ----
        strike_data = self._read_strike_data()
        prev_ticker = self.active_ticker
        if strike_data:
            self.gate_ttc = strike_data["ttc"]
            self.gate_buffer_pct = strike_data.get("buffer_pct")
            self.gate_floor_strike = strike_data.get("floor_strike")
            self.gate_spot = strike_data.get("current_price")
            self.active_ticker = strike_data["ticker"]
        else:
            self.gate_buffer_pct = None
            self.gate_floor_strike = None
            self.gate_spot = None
        self.gate_mom_1m = self._read_momentum_1m()

        ticker = self.active_ticker

        best_bid, best_ask = None, None
        if ticker:
            ob = self._read_orderbook(ticker)
            if ob:
                best_bid, best_ask = self._best_bid_ask(ob)
                self.gate_best_bid = f"{best_bid:.4f}" if best_bid else None
                self.gate_best_ask = f"{best_ask:.4f}" if best_ask else None
            else:
                self.gate_best_bid = None
                self.gate_best_ask = None

        position = self._read_position(r, ticker, subaccount) if ticker else 0.0
        is_flat = abs(position) < 0.001

        # ---- Ticker changed: mandatory settle before any new entry ----
        if prev_ticker and ticker and ticker != prev_ticker:
            self._last_strike_gate_reason = None
            self._clear_idle_skip_log()
            self._anchor_ticker = None
            self._anchor_floor_strike = None
            self._rollover_quiet_until_mono = (
                time.monotonic() + ROLLOVER_SETTLE_SEC
            )
            log.info(
                "Ticker changed %s -> %s: rollover settle %.0fs (no entry until then)",
                prev_ticker, ticker, ROLLOVER_SETTLE_SEC,
            )
            if self.state != HFTState.IDLE:
                self._cancel_tracked_orders(subaccount)
                self._clear_all_order_state()
                self.state = HFTState.IDLE
                self._mark_api_action()
            self._finish(r)
            return

        # ---- DISABLED: cancel own tracked orders, go IDLE ----
        if not enabled:
            if self.state != HFTState.IDLE:
                log.info("HFT disabled -> IDLE")
                self._cancel_tracked_orders(subaccount)
                self._clear_all_order_state()
                self.state = HFTState.IDLE
            self._finish(r)
            return

        # ---- No market data yet ----
        if not strike_data or best_bid is None or best_ask is None:
            self._finish(r)
            return

        # ---- Startup: detect pre-existing position ----
        if not self._startup_done:
            self._startup_done = True
            if not is_flat and self.state == HFTState.IDLE:
                self.entry_side = "long" if position > 0 else "short"
                self.entry_price = best_bid if position > 0 else best_ask
                self.state = HFTState.CLOSING
                log.info("Startup: position=%.2f -> CLOSING entry=%s side=%s",
                         position, self.entry_price, self.entry_side)
                self._finish(r)
                return

        # =============================================================
        # STATE: IDLE
        # =============================================================
        if self.state == HFTState.IDLE:
            if not is_flat:
                if self.my_bid_oid or self.my_ask_oid:
                    log.warning(
                        "IDLE: open position %.2f with tracked entry oids bid=%s ask=%s — canceling",
                        position, self.my_bid_oid, self.my_ask_oid,
                    )
                    self._cancel_entry_orders(subaccount)
                    self._finish(r)
                    return
                self.entry_side = "long" if position > 0 else "short"
                self.entry_price = best_bid if position > 0 else best_ask
                if self.target_spread is None:
                    spread_cents, mode = self._momentum_spread(self.gate_mom_1m or 0)
                    self.target_spread = Decimal(spread_cents) / Decimal(100)
                    if self.trade_mode is None:
                        self.trade_mode = mode
                self.state = HFTState.CLOSING
                log.info(
                    "IDLE -> CLOSING: position=%.2f entry=%s side=%s mode=%s spread=%s",
                    position, self.entry_price, self.entry_side,
                    self.trade_mode, self.target_spread,
                )
            else:
                gates_ok = self._gates_pass(
                    self.gate_ttc or 0,
                    self.gate_buffer_pct or 0,
                    self.gate_mom_1m,
                    strike_data,
                )
                max_c = self._max_contracts(count)
                if abs(position) >= max_c - 0.001:
                    self._log_idle_skip(
                        "position_at_max",
                        "IDLE: skip entry, |position|=%.2f at max %.2f",
                        position, max_c,
                    )
                elif gates_ok:
                    if self._book_allows_entry(
                        best_bid, best_ask, self.gate_mom_1m,
                    ):
                        self._clear_idle_skip_log()
                        self._idle_place_entry(
                            ticker, best_bid, best_ask, count, subaccount)
                    else:
                        _, entry_mode = self._momentum_spread(self.gate_mom_1m or 0)
                        self._log_idle_skip(
                            f"book_entry_band:{entry_mode}",
                            "IDLE: skip entry, book outside entry band [%.2f, %.2f] "
                            "(mode=%s bid=%s ask=%s mom=%.1f)",
                            MIN_ENTRY_PRICE, MAX_ENTRY_PRICE,
                            entry_mode, best_bid, best_ask, self.gate_mom_1m or 0,
                        )

        # =============================================================
        # STATE: QUOTING
        # =============================================================
        elif self.state == HFTState.QUOTING:
            if not is_flat:
                self._quoting_fill_detected(
                    position, best_bid, best_ask, count, subaccount)
            else:
                self._quoting_still_flat(r, ticker, best_bid, best_ask, count, subaccount)

        # =============================================================
        # STATE: CLOSING
        # =============================================================
        elif self.state == HFTState.CLOSING:
            if is_flat:
                log.info("CLOSING -> IDLE: position closed")
                self._clear_all_order_state()
                self.state = HFTState.IDLE
            else:
                if self.my_bid_oid or self.my_ask_oid:
                    log.warning(
                        "CLOSING: stray entry oids bid=%s ask=%s (counter=%s) — canceling",
                        self.my_bid_oid, self.my_ask_oid, self.counter_oid,
                    )
                    self._cancel_entry_orders(
                        subaccount, keep_oid=self.counter_oid,
                    )
                    self._finish(r)
                    return
                if self.entry_side is None:
                    recovered = self._infer_entry_side(position, self.trade_mode)
                    if recovered:
                        self.entry_side = recovered
                        self.entry_price = (
                            best_bid if recovered == "long" else best_ask
                        )
                        log.info(
                            "CLOSING: recovered entry_side=%s from position=%.2f",
                            recovered, position,
                        )
                    else:
                        log.warning(
                            "CLOSING: no entry_side, position=%.2f -> IDLE",
                            position,
                        )
                        self._clear_all_order_state()
                        self.state = HFTState.IDLE
                        self._finish(r)
                        return
                max_c = self._max_contracts(count)
                if abs(position) > max_c + 0.001:
                    log.warning(
                        "Position %.2f exceeds max %.2f -> ripcord",
                        position, max_c,
                    )
                    self._ripcord_flatten(
                        ticker, count, subaccount, position=position)
                elif self.pending_cancel_oid:
                    oid = self.pending_cancel_oid
                    self.pending_cancel_oid = None
                    log.info("Canceling stray entry oid=%s", oid)
                    kalshi_cancel_order(oid, subaccount=subaccount)
                    self._mark_api_action()
                else:
                    self._closing_manage(
                        r, ticker, position, best_bid, best_ask, count, subaccount)

        self._finish(r)

    def _finish(self, r) -> None:
        self.last_eval_mono = time.monotonic()
        self._write_state(r)

    # -- IDLE: place entry orders -------------------------------------------

    def _idle_place_entry(self, ticker, best_bid, best_ask, count, subaccount):
        spread_cents, mode = self._momentum_spread(self.gate_mom_1m)
        spread = Decimal(spread_cents) / Decimal(100)

        if mode == "neutral":
            orders = self._build_mm_batch(
                ticker, best_bid, best_ask, count, subaccount, self.gate_mom_1m)
            if not orders:
                return
            result = kalshi_batch_create_orders(orders)
            self._mark_api_action()
            if not result or not isinstance(result.get("orders"), list):
                return
            resp_orders = result["orders"]
            bid_ok = len(resp_orders) > 0 and not resp_orders[0].get("error")
            ask_ok = len(resp_orders) > 1 and not resp_orders[1].get("error")
            if bid_ok:
                self.my_bid_oid = resp_orders[0].get("order_id")
            else:
                self._post_only_catch_up_sides.add("bid")
                self._set_post_only_backoff("bid")
            if ask_ok:
                self.my_ask_oid = resp_orders[1].get("order_id")
            else:
                self._post_only_catch_up_sides.add("ask")
                self._set_post_only_backoff("ask")
            self.submitted_bid_price = best_bid
            self.submitted_ask_price = best_ask
            self.trade_mode = "neutral"
            if self.my_bid_oid or self.my_ask_oid:
                self._clear_idle_skip_log()
                self.state = HFTState.QUOTING
                log.info("IDLE -> QUOTING [neutral] bid_oid=%s ask_oid=%s bid=%s ask=%s",
                         self.my_bid_oid, self.my_ask_oid,
                         self.gate_best_bid, self.gate_best_ask)
        else:
            entry_side = "bid" if mode == "bullish" else "ask"
            entry_price = (best_bid if mode == "bullish" else best_ask).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP)
            if entry_price <= 0 or entry_price >= Decimal("1"):
                return
            if not self._entry_price_allowed(entry_price):
                self._log_idle_skip(
                    f"entry_price_band:{mode}",
                    "IDLE: skip entry, price %s outside band [%.2f, %.2f] (mode=%s)",
                    entry_price, MIN_ENTRY_PRICE, MAX_ENTRY_PRICE, mode,
                )
                return
            place_price = self._limit_price_for_order(
                entry_side, best_bid, best_ask, entry_price)
            if place_price is None:
                return
            log.info(
                "ORDER_PARAMS mode=%s mom=%.1f spread=%dc entry_side=%s entry_price=%s "
                "ticker=%s floor_strike=%s buffer_pct=%s spot=%s ttc=%s",
                mode, self.gate_mom_1m, spread_cents, entry_side, f"{place_price:.4f}",
                ticker, self.gate_floor_strike, self.gate_buffer_pct,
                self.gate_spot, self.gate_ttc,
            )
            oid = self._place_post_only_at_price(
                ticker=ticker, side=entry_side, price=place_price,
                count=count, subaccount=subaccount,
                best_bid=best_bid, best_ask=best_ask, label="Placing entry",
            )
            if oid:
                if entry_side == "bid":
                    self.my_bid_oid = oid
                    self.submitted_bid_price = place_price
                else:
                    self.my_ask_oid = oid
                    self.submitted_ask_price = place_price
                self.entry_order_price = place_price
                self.trade_mode = mode
                self.target_spread = spread
                self._clear_idle_skip_log()
                self.state = HFTState.QUOTING
                log.info("IDLE -> QUOTING [%s] oid=%s side=%s price=%s spread=%dc",
                         mode, oid, entry_side, f"{place_price:.4f}", spread_cents)
            else:
                log.info(
                    "Entry order did not rest -- will retry at book after post-only backoff",
                )

    # -- QUOTING: fill detected ---------------------------------------------

    def _quoting_fill_detected(
        self, position, best_bid, best_ask, count, subaccount,
    ):
        """Position != 0 while in QUOTING: cancel entry legs on exchange, -> CLOSING."""
        max_c = self._max_contracts(count)
        if abs(position) > max_c + 0.001:
            log.warning(
                "QUOTING: |position|=%.2f > max %.2f -- will ripcord in CLOSING",
                position, max_c,
            )

        bid_oid, ask_oid = self.my_bid_oid, self.my_ask_oid

        entry_side = self._infer_entry_side(position, self.trade_mode)
        if entry_side is None:
            entry_side = self._infer_entry_side_from_position(position)
            if entry_side is None:
                log.warning(
                    "QUOTING: position=%.2f but no side — cancel entries -> IDLE",
                    position,
                )
                self._cancel_entry_orders(subaccount)
                self.state = HFTState.IDLE
                return
            log.warning(
                "QUOTING: position=%.2f mismatches trade_mode=%s — using %s",
                position, self.trade_mode, entry_side,
            )

        self.entry_side = entry_side
        if entry_side == "long":
            self.entry_price = self.submitted_bid_price or best_bid
        else:
            self.entry_price = self.submitted_ask_price or best_ask

        counter_keep: Optional[str] = None
        if self.trade_mode == "neutral":
            counter_keep = ask_oid if entry_side == "long" else bid_oid

        self._cancel_entry_orders(subaccount, keep_oid=counter_keep)
        self.counter_oid = counter_keep
        self.my_bid_oid = None
        self.my_ask_oid = None
        self.pending_cancel_oid = None
        self.awaiting_flat_after_counter = False
        self.state = HFTState.CLOSING
        log.info(
            "QUOTING -> CLOSING [%s] position=%.2f entry_side=%s entry_price=%s "
            "counter_oid=%s (canceled stray entry legs)",
            self.trade_mode, position, self.entry_side, self.entry_price,
            self.counter_oid,
        )

    # -- QUOTING: still flat ------------------------------------------------

    def _quoting_still_flat(self, r, ticker, best_bid, best_ask, count, subaccount):
        """Position == 0 while in QUOTING. Re-check gates, manage entry orders."""

        # Gate re-check: cancel entry orders if conditions changed
        strike_data = self._read_strike_data()
        gates_ok = self._gates_pass(
            self.gate_ttc or 0,
            self.gate_buffer_pct or 0,
            self.gate_mom_1m,
            strike_data,
        )
        if not gates_ok:
            log.info("QUOTING -> IDLE: gates no longer pass")
            for oid in (self.my_bid_oid, self.my_ask_oid):
                if oid:
                    kalshi_cancel_order(oid, subaccount=subaccount)
            self._clear_all_order_state()
            self.state = HFTState.IDLE
            self._mark_api_action()
            return

        # Momentum band changed
        _, new_mode = self._momentum_spread(self.gate_mom_1m)
        if new_mode != self.trade_mode:
            log.info("QUOTING -> IDLE: momentum band %s -> %s", self.trade_mode, new_mode)
            for oid in (self.my_bid_oid, self.my_ask_oid):
                if oid:
                    kalshi_cancel_order(oid, subaccount=subaccount)
            self._clear_all_order_state()
            self.state = HFTState.IDLE
            self._mark_api_action()
            return

        # -- Directional: manage single entry order --
        if self.trade_mode != "neutral" and self.trade_mode is not None:
            entry_side = "bid" if self.trade_mode == "bullish" else "ask"
            entry_oid = self.my_bid_oid or self.my_ask_oid

            if not entry_oid:
                log.info("QUOTING -> IDLE: flat, no resting entry — re-acquire via IDLE")
                self._clear_all_order_state()
                self.state = HFTState.IDLE
                return

            tracked = (
                self.entry_order_price
                or self.submitted_bid_price
                or self.submitted_ask_price
            )
            if tracked is not None and not self._entry_price_allowed(tracked):
                self._cancel_entry_and_idle(
                    subaccount,
                    f"entry price {tracked} outside band [{MIN_ENTRY_PRICE}, {MAX_ENTRY_PRICE}]",
                )
                return

            entry_status = self._check_order_status(r, entry_oid)
            if entry_status == "executed":
                # Fill with lagging position: cancel any resting entry remainder, -> CLOSING.
                if self.trade_mode == "bullish":
                    self.entry_side = "long"
                    self.entry_price = self.submitted_bid_price or best_bid
                else:
                    self.entry_side = "short"
                    self.entry_price = self.submitted_ask_price or best_ask
                self._cancel_entry_orders(subaccount)
                self.counter_oid = None
                self.awaiting_flat_after_counter = False
                self.state = HFTState.CLOSING
                log.info(
                    "QUOTING -> CLOSING [%s, fill lag] entry_side=%s entry_price=%s "
                    "spread=%s",
                    self.trade_mode, self.entry_side, self.entry_price,
                    self.target_spread,
                )
                return
            if entry_status == "canceled":
                log.info(
                    "QUOTING -> IDLE: entry oid=%s canceled while flat",
                    entry_oid,
                )
                self._clear_all_order_state()
                self.state = HFTState.IDLE
                return
            if entry_status is not None and entry_status != "resting":
                log.info("QUOTING -> IDLE: entry oid=%s status=%s", entry_oid, entry_status)
                self._clear_all_order_state()
                self.state = HFTState.IDLE
                return

            # Amend to follow book only when it moves AWAY from fill
            if self.trade_mode == "bullish":
                current_best = best_bid.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            else:
                current_best = best_ask.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

            should_amend = False
            if self.entry_order_price is not None and current_best != self.entry_order_price:
                if self.trade_mode == "bullish" and current_best > self.entry_order_price:
                    should_amend = True
                elif self.trade_mode == "bearish" and current_best < self.entry_order_price:
                    should_amend = True

            if should_amend:
                if (
                    time.monotonic() - self._last_entry_amend_mono
                    < HFT_ENTRY_AMEND_INTERVAL_SEC
                ):
                    return
                if not self._entry_price_allowed(current_best):
                    self._cancel_entry_and_idle(
                        subaccount,
                        f"amend target {current_best} outside entry band "
                        f"[{MIN_ENTRY_PRICE}, {MAX_ENTRY_PRICE}]",
                    )
                    return
                entry_side = "bid" if self.trade_mode == "bullish" else "ask"
                price_str = f"{current_best:.4f}"
                log.info("QUOTING amend: %s moved away %s -> %s",
                         entry_side, self.entry_order_price, price_str)
                result = kalshi_amend_order(
                    entry_oid, ticker=ticker, side=entry_side,
                    price=price_str, count=count, subaccount=subaccount)
                self._mark_api_action()
                if result is None:
                    self._set_post_only_backoff(entry_side)
                    log.info(
                        "QUOTING -> IDLE: entry amend rejected while flat",
                    )
                    self._clear_all_order_state()
                    self.state = HFTState.IDLE
                    return
                if float(result.get("remaining_count", "1")) < 0.001:
                    log.info("QUOTING -> IDLE: entry amend left no resting size")
                    self._clear_all_order_state()
                    self.state = HFTState.IDLE
                else:
                    self._last_entry_amend_mono = time.monotonic()
                    self.entry_order_price = current_best
                    if self.trade_mode == "bullish":
                        self.submitted_bid_price = current_best
                    else:
                        self.submitted_ask_price = current_best

        # -- Neutral: check if both orders are gone --
        elif self.trade_mode == "neutral":
            bid_bad = (
                self.submitted_bid_price is not None
                and not self._entry_price_allowed(self.submitted_bid_price)
            )
            ask_bad = (
                self.submitted_ask_price is not None
                and not self._entry_price_allowed(self.submitted_ask_price)
            )
            if bid_bad or ask_bad:
                self._cancel_entry_and_idle(
                    subaccount,
                    f"neutral entry bid={self.submitted_bid_price} ask="
                    f"{self.submitted_ask_price} outside entry band "
                    f"[{MIN_ENTRY_PRICE}, {MAX_ENTRY_PRICE}]",
                )
                return

            bid_status = self._check_order_status(r, self.my_bid_oid) if self.my_bid_oid else None
            ask_status = self._check_order_status(r, self.my_ask_oid) if self.my_ask_oid else None
            if self.my_bid_oid and bid_status == "executed":
                log.info(
                    "Neutral bid oid=%s executed (position may lag) — not re-placing bid",
                    self.my_bid_oid,
                )
                self.my_bid_oid = None
            elif self.my_bid_oid and bid_status == "canceled":
                log.info("Neutral bid oid=%s canceled -- will re-place at book", self.my_bid_oid)
                self._post_only_catch_up_sides.add("bid")
                self.my_bid_oid = None
            if self.my_ask_oid and ask_status == "executed":
                log.info(
                    "Neutral ask oid=%s executed (position may lag) — not re-placing ask",
                    self.my_ask_oid,
                )
                self.my_ask_oid = None
            elif self.my_ask_oid and ask_status == "canceled":
                log.info("Neutral ask oid=%s canceled -- will re-place at book", self.my_ask_oid)
                self._post_only_catch_up_sides.add("ask")
                self.my_ask_oid = None

            if not self.my_bid_oid:
                target = best_bid.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                if not self._entry_price_allowed(target):
                    self._cancel_entry_and_idle(
                        subaccount,
                        f"neutral bid re-place {target} outside entry band "
                        f"[{MIN_ENTRY_PRICE}, {MAX_ENTRY_PRICE}]",
                    )
                    return
                place_price = self._limit_price_for_order(
                    "bid", best_bid, best_ask, target)
                if place_price is None:
                    return
                oid = self._place_post_only_at_price(
                    ticker=ticker, side="bid", price=place_price,
                    count=count, subaccount=subaccount,
                    best_bid=best_bid, best_ask=best_ask,
                    label="QUOTING re-place bid",
                )
                if oid:
                    self.my_bid_oid = oid
                    self.submitted_bid_price = place_price
                return

            if not self.my_ask_oid:
                target = best_ask.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                if not self._entry_price_allowed(target):
                    self._cancel_entry_and_idle(
                        subaccount,
                        f"neutral ask re-place {target} outside entry band "
                        f"[{MIN_ENTRY_PRICE}, {MAX_ENTRY_PRICE}]",
                    )
                    return
                place_price = self._limit_price_for_order(
                    "ask", best_bid, best_ask, target)
                if place_price is None:
                    return
                oid = self._place_post_only_at_price(
                    ticker=ticker, side="ask", price=place_price,
                    count=count, subaccount=subaccount,
                    best_bid=best_bid, best_ask=best_ask,
                    label="QUOTING re-place ask",
                )
                if oid:
                    self.my_ask_oid = oid
                    self.submitted_ask_price = place_price
                return

            bid_gone = self.my_bid_oid and bid_status not in (None, "resting")
            ask_gone = self.my_ask_oid and ask_status not in (None, "resting")
            if bid_gone and ask_gone:
                log.info("QUOTING -> IDLE: both orders gone (bid=%s ask=%s)", bid_status, ask_status)
                self._clear_all_order_state()
                self.state = HFTState.IDLE

    # -- CLOSING: manage counter-order and stop-loss ------------------------

    def _closing_manage(self, r, ticker, position, best_bid, best_ask, count, subaccount):
        self._sync_entry_with_position(position, best_bid, best_ask)
        close_side = self._effective_close_side(position)
        if not close_side:
            return

        # Check counter-order status
        if self.counter_oid:
            status = self._check_order_status(r, self.counter_oid)
            if status == "executed":
                log.info(
                    "Counter oid=%s executed -- awaiting flat (no replacement limit)",
                    self.counter_oid,
                )
                self.counter_oid = None
                self.awaiting_flat_after_counter = True
                return
            if status is not None and status != "resting":
                log.info("Counter oid=%s status=%s -- cleared", self.counter_oid, status)
                if status == "canceled":
                    self._post_only_catch_up_sides.add(close_side)
                    log.info(
                        "Counter canceled (post-only) -- will re-place %s at book",
                        close_side,
                    )
                self.counter_oid = None
                if status == "canceled":
                    self.awaiting_flat_after_counter = False

        # Counter filled: wait for flat unless loss or position mismatch requires action.
        if self.awaiting_flat_after_counter:
            if abs(position) < 0.001:
                log.info("CLOSING: flat after counter — done awaiting")
                self.awaiting_flat_after_counter = False
                return
            max_c = self._max_contracts(count)
            if abs(position) > max_c + 0.001:
                log.warning(
                    "Still |position|=%.2f > max %.2f after counter fill -> ripcord",
                    position, max_c,
                )
                self._ripcord_flatten(
                    ticker, count, subaccount, position=position)
                return
            if self._maybe_ripcord_on_loss(
                ticker, position, best_bid, best_ask, count, subaccount, r=r,
            ):
                self.awaiting_flat_after_counter = False
                return
            if not self._position_matches_entry(position):
                log.warning(
                    "Awaiting flat but position=%.2f vs entry_side=%s — resume close",
                    position, self.entry_side,
                )
                self.awaiting_flat_after_counter = False
                self._sync_entry_with_position(position, best_bid, best_ask)
                close_side = self._effective_close_side(position)
            else:
                return

        if self._maybe_ripcord_on_loss(
            ticker, position, best_bid, best_ask, count, subaccount, r=r,
        ):
            return

        loss = self._unrealized_loss_cents(position, best_bid, best_ask)
        if (
            loss is not None
            and loss >= self.max_loss_cents
            and self.counter_oid
        ):
            raw_touch = best_bid if position > 0.001 else best_ask
            submit_px = self._effective_submit_price(
                raw_touch, close_side, best_bid, best_ask,
            )
            if submit_px is None:
                return
            if self.last_amend_price is None or submit_px != self.last_amend_price:
                price_str = f"{submit_px:.4f}"
                log.info(
                    "STOP_LOSS amend: loss=%s -> %s at %s",
                    loss, close_side, price_str,
                )
                result = kalshi_amend_order(
                    self.counter_oid, ticker=ticker, side=close_side,
                    price=price_str, count=count, subaccount=subaccount)
                self._mark_api_action()
                if result is None:
                    self._mark_post_only_cross(
                        close_side,
                        submit_px,
                        best_bid,
                        best_ask,
                        apply_backoff=False,
                    )
                    self.counter_oid = None
                    self.last_amend_price = None
                    return
                self.last_amend_price = submit_px
                return

        # No counter-order: place one (side from position when entry label lags)
        if not self.counter_oid:
            if not self._position_matches_entry(position):
                log.warning(
                    "CLOSING: position=%.2f vs entry_side=%s — placing close from position",
                    position, self.entry_side,
                )
                close_side = self._effective_close_side(position)
                if not close_side:
                    return
            target_price = self._target_counter_price(best_bid, best_ask)
            if target_price is None:
                return
            close_price = self._limit_price_for_order(
                close_side, best_bid, best_ask, target_price)
            if close_price is None:
                return
            oid = self._place_post_only_at_price(
                ticker=ticker, side=close_side, price=close_price,
                count=count, subaccount=subaccount,
                best_bid=best_bid, best_ask=best_ask, label="Placing counter",
                exempt_post_only_backoff=True,
            )
            if oid:
                self.counter_oid = oid
                log.info("Counter resting oid=%s price=%s", oid, f"{close_price:.4f}")
            else:
                log.info(
                    "Counter did not rest -- will retry at book on next tick",
                )


# ---------------------------------------------------------------------------
# Main event loop
# ---------------------------------------------------------------------------

HFT_LOCK_KEY = "rec_io:hft:engine_lock"
HFT_LOCK_TTL = 10


def _acquire_singleton_lock(r_cmd) -> bool:
    """Acquire a Redis-based singleton lock. Returns True if this is the only instance."""
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
    """Refresh the lock TTL. Returns False if we lost the lock."""
    my_pid = str(os.getpid())
    holder = r_cmd.get(HFT_LOCK_KEY)
    if holder == my_pid:
        r_cmd.expire(HFT_LOCK_KEY, HFT_LOCK_TTL)
        return True
    return False


def run_hft_engine():
    log.info("HFT Engine starting (port=%d)", HFT_PORT)

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
        log.error("Another HFT engine is already running (lock held by PID %s). Exiting.",
                  r_cmd.get(HFT_LOCK_KEY))
        sys.exit(1)
    log.info("Singleton lock acquired (PID %d)", os.getpid())

    engine._write_state(r_cmd)

    pubsub = r_sub.pubsub()
    pubsub.subscribe(UPDATED_CHANNEL)
    log.info("Subscribed to %s", UPDATED_CHANNEL)

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
                    log.error("Lost singleton lock -- another instance took over. Exiting.")
                    break
                last_lock_refresh = now

            msg = pubsub.get_message(timeout=1.0)
            if msg and msg.get("type") == "message":
                try:
                    payload = json.loads(msg["data"])
                    kind = payload.get("kind", "")
                    if kind in relevant_kinds:
                        engine.evaluate(r_cmd)
                except (json.JSONDecodeError, TypeError):
                    pass
            elif msg is None:
                if now - engine.last_eval_mono > 2.0:
                    engine.evaluate(r_cmd)
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
