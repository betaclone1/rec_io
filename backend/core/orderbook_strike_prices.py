"""
Orderbook-derived touch and taker fill estimates for strike ladder and execution gates.

Reads Redis snapshots written by market_watchdog (no REST on hot path).
"""

from __future__ import annotations

import os
import time
from decimal import Decimal
from typing import Any, Dict, Optional

from backend.core.trade_monitor_live_orderbook_payload import (
    _book_rows_near_touch,
    _transform_complement_levels,
    load_orderbook_snapshot_from_redis,
)

_REQUIRED_TOUCH_KEYS = (
    "yes_ask_dollars",
    "no_ask_dollars",
)


def orderbook_max_age_sec() -> float:
    """Max Redis orderbook age before strike-table pricing treats the feed as degraded."""
    raw = os.getenv("STRIKE_ORDERBOOK_MAX_AGE_SEC")
    if raw is not None and str(raw).strip() != "":
        return max(1.0, float(raw))
    return 30.0


def _snapshot_age_sec(snap: dict[str, Any]) -> Optional[float]:
    now_ms = time.time() * 1000
    rw_ms = snap.get("redis_written_ms")
    ts_ms = snap.get("ts_ms")
    ref_ms = rw_ms if rw_ms is not None else ts_ms
    if ref_ms is None:
        return None
    try:
        return max(0.0, (now_ms - float(ref_ms)) / 1000.0)
    except (TypeError, ValueError):
        return None


def _levels_from_snapshot(data: dict[str, Any]) -> tuple[dict[Decimal, Decimal], dict[Decimal, Decimal]]:
    yes_levels: dict[Decimal, Decimal] = {}
    no_levels: dict[Decimal, Decimal] = {}
    yt = data.get("yes")
    nt = data.get("no")
    if isinstance(yt, dict):
        for p_str, sz_str in yt.items():
            try:
                yes_levels[Decimal(str(p_str))] = Decimal(str(sz_str))
            except Exception:
                continue
    if isinstance(nt, dict):
        for p_str, sz_str in nt.items():
            try:
                no_levels[Decimal(str(p_str))] = Decimal(str(sz_str))
            except Exception:
                continue
    return yes_levels, no_levels


def touch_dollars_from_orderbook_snapshot(
    data: dict[str, Any],
) -> Optional[dict[str, str]]:
    """
    Best touch yes/no bid and ask in dollar strings (4 dp), from a Redis orderbook envelope.
  """
    if not data or data.get("valid") is False:
        return None
    yes_levels, no_levels = _levels_from_snapshot(data)
    if not yes_levels and not no_levels:
        return None

    yes_bids = _book_rows_near_touch(yes_levels, is_ask=False, limit=1)
    no_bids = _book_rows_near_touch(no_levels, is_ask=False, limit=1)
    yes_asks = _book_rows_near_touch(_transform_complement_levels(no_levels), is_ask=True, limit=1)
    no_asks = _book_rows_near_touch(_transform_complement_levels(yes_levels), is_ask=True, limit=1)

    out: dict[str, str] = {}
    if yes_bids:
        out["yes_bid_dollars"] = f"{float(yes_bids[0]['price']):.4f}"
    if no_bids:
        out["no_bid_dollars"] = f"{float(no_bids[0]['price']):.4f}"
    if yes_asks:
        out["yes_ask_dollars"] = f"{float(yes_asks[0]['price']):.4f}"
    if no_asks:
        out["no_ask_dollars"] = f"{float(no_asks[0]['price']):.4f}"

    # Complement fill: opposite-side bid implies this side's ask.
    if not out.get("no_ask_dollars") and yes_bids:
        out["no_ask_dollars"] = f"{1.0 - float(yes_bids[0]['price']):.4f}"
    if not out.get("yes_ask_dollars") and no_bids:
        out["yes_ask_dollars"] = f"{1.0 - float(no_bids[0]['price']):.4f}"
    # One-sided book: no contra resting liquidity → ask caps at $1.00 (still OB-derived).
    if not out.get("yes_ask_dollars") and yes_bids and not no_levels:
        out["yes_ask_dollars"] = "1.0000"
    if not out.get("no_ask_dollars") and no_bids and not yes_levels:
        out["no_ask_dollars"] = "1.0000"
    if not out.get("yes_bid_dollars") and out.get("no_ask_dollars"):
        out["yes_bid_dollars"] = f"{max(0.0, 1.0 - float(out['no_ask_dollars'])):.4f}"
    if not out.get("no_bid_dollars") and out.get("yes_ask_dollars"):
        out["no_bid_dollars"] = f"{max(0.0, 1.0 - float(out['yes_ask_dollars'])):.4f}"

    if not out.get("yes_ask_dollars") and not out.get("no_ask_dollars"):
        return None
    return out


def touch_dollars_for_ticker(market_ticker: str) -> Optional[dict[str, str]]:
    """Load Redis OB for ``market_ticker`` and return touch bid/ask dollars."""
    touch, _reason = resolve_orderbook_touch_dollars(market_ticker)
    return touch


def resolve_orderbook_touch_dollars(
    market_ticker: str,
    *,
    max_age_sec: Optional[float] = None,
) -> tuple[Optional[dict[str, str]], str]:
    """
    Strict strike-table pricing: full OB touch or failure (no ticker fallback).

    Returns (touch_dict, reason). touch_dict has yes/no bid+ask dollar strings when ok.
    """
    mt = str(market_ticker or "").strip()
    if not mt:
        return None, "missing_ticker"
    snap = load_orderbook_snapshot_from_redis(mt)
    if not snap:
        return None, "orderbook_miss"
    if snap.get("valid") is False:
        return None, "orderbook_invalid"
    age_limit = float(max_age_sec if max_age_sec is not None else orderbook_max_age_sec())
    age_sec = _snapshot_age_sec(snap)
    if age_sec is None:
        return None, "orderbook_no_timestamp"
    if age_sec > age_limit:
        return None, f"orderbook_stale:{age_sec:.1f}s>{age_limit:.1f}s"
    touch = touch_dollars_from_orderbook_snapshot(snap)
    if not touch:
        return None, "orderbook_empty"
    for key in _REQUIRED_TOUCH_KEYS:
        if not touch.get(key):
            return None, f"orderbook_incomplete:{key}"
    return touch, "ok"


def _normalize_side(side_val: object) -> Optional[str]:
    side = str(side_val or "").strip().lower()
    if side in ("yes", "y"):
        return "yes"
    if side in ("no", "n"):
        return "no"
    return None


def project_taker_buy_from_levels(
    yes_levels: Dict[Any, Any],
    no_levels: Dict[Any, Any],
    side: str,
    position: int,
    *,
    limit_price: Optional[float] = None,
) -> dict[str, Any]:
    """
    Walk complementary asks built from opposite-side bids (same geometry as paper IOC / TM).

    ``limit_price`` set → IOC-style: only take levels with ask <= limit.
    ``limit_price`` None → market-style full depth up to ``position``.

    Returns: ok, reason, filled, initial_proj_price, initial_proj_fees, available_contracts.
    """
    import math

    result: dict[str, Any] = {
        "ok": False,
        "reason": "projection_failed",
        "filled": 0,
        "initial_proj_price": None,
        "initial_proj_fees": None,
        "available_contracts": None,
    }
    side_n = _normalize_side(side)
    if not side_n or not position or int(position) <= 0:
        result["reason"] = "missing_projection_inputs"
        return result

    src_bids = no_levels if side_n == "yes" else yes_levels
    asks: list[tuple[float, float]] = []
    for px, qty in (src_bids or {}).items():
        try:
            bid_px = float(px)
            sz = float(qty)
        except (TypeError, ValueError):
            continue
        ask_px = 1.0 - bid_px
        if sz <= 0 or ask_px <= 0 or ask_px >= 1:
            continue
        asks.append((ask_px, sz))
    asks.sort(key=lambda x: x[0])

    lim: Optional[float] = None
    if limit_price is not None:
        try:
            lim = float(limit_price)
        except (TypeError, ValueError):
            result["reason"] = "bad_limit_price"
            return result
        if lim <= 0 or lim >= 1:
            result["reason"] = "bad_limit_price"
            return result

    if lim is None:
        available = sum(q for _, q in asks)
    else:
        available = sum(q for px, q in asks if px <= lim + 1e-12)

    remaining = float(position)
    filled = 0.0
    notional = 0.0
    for px, qty in asks:
        if remaining <= 0:
            break
        if lim is not None and px > lim + 1e-12:
            continue
        take = min(remaining, qty)
        if take <= 0:
            continue
        notional += px * take
        filled += take
        remaining -= take

    result["available_contracts"] = round(available, 2)
    result["filled"] = int(round(filled))
    if filled <= 0:
        result["reason"] = "no_fill_at_limit" if lim is not None else "no_resting_volume"
        return result

    avg_price = notional / filled
    # Same taker fee formula as trade_manager.estimate_kalshi_taker_fee
    raw_fee = 0.07 * filled * avg_price * (1.0 - avg_price)
    result["initial_proj_price"] = round(avg_price, 8)
    result["initial_proj_fees"] = round(math.ceil(raw_fee * 100) / 100, 2)
    if lim is not None:
        result["ok"] = True
        result["reason"] = "ok"
    else:
        result["ok"] = filled >= float(position)
        result["reason"] = "ok" if result["ok"] else "insufficient_resting_volume"
    return result


def project_taker_fill_price(
    market_ticker: str,
    side: str,
    position: int,
) -> dict[str, Any]:
    """
    Walk Redis orderbook for a taker buy on ``side`` for ``position`` contracts.
    Returns keys: ok, reason, initial_proj_price, available_contracts (same shape as trade_manager).
    """
    result: dict[str, Any] = {
        "ok": False,
        "reason": "projection_failed",
        "initial_proj_price": None,
        "available_contracts": None,
    }
    mt = str(market_ticker or "").strip()
    side_n = _normalize_side(side)
    if not mt or not side_n or not position or position <= 0:
        result["reason"] = "missing_projection_inputs"
        return result

    snap = load_orderbook_snapshot_from_redis(mt)
    if not snap or snap.get("valid") is False:
        result["reason"] = "orderbook_miss"
        return result

    yes_levels, no_levels = _levels_from_snapshot(snap)
    proj = project_taker_buy_from_levels(
        yes_levels, no_levels, side_n, int(position), limit_price=None
    )
    result["available_contracts"] = proj.get("available_contracts")
    result["initial_proj_price"] = proj.get("initial_proj_price")
    result["ok"] = bool(proj.get("ok"))
    result["reason"] = proj.get("reason") or "projection_failed"
    return result


def apply_orderbook_touch_overrides(
    ticker: Optional[str],
    yes_ask_dollars: Any,
    no_ask_dollars: Any,
    yes_bid_dollars: Any,
    no_bid_dollars: Any,
) -> tuple[Any, Any, Any, Any]:
    """
    Deprecated: strike table uses resolve_orderbook_touch_dollars only (no ticker fallback).

    Kept for callers that still pass ticker values; returns OB touch or Nones.
    """
    touch, _reason = resolve_orderbook_touch_dollars(str(ticker or "").strip() or "")
    if not touch:
        return None, None, None, None
    return (
        touch["yes_ask_dollars"],
        touch["no_ask_dollars"],
        touch["yes_bid_dollars"],
        touch["no_bid_dollars"],
    )
