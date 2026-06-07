"""HFT engine control routes -- toggle, status, config."""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from backend.hft_process_ctl import hft_process_status, start_hft_engine, stop_hft_engine

logger = logging.getLogger("hft_routes")

hft_router = APIRouter(tags=["hft"])

HFT_CONTROL_KEY = "rec_io:hft:control"
HFT_STATE_KEY = "rec_io:hft:state"

_CONTROL_DEFAULTS: Dict[str, Any] = {
    "enabled": False,
    "subaccount": 2,
    "count": "1.00",
    "ticker_filter": "",
    "neutral_mode": False,
}


def _redis():
    from backend.core.live_state_cache import redis_client_optional
    return redis_client_optional()


def _read_control(r) -> Dict[str, Any]:
    raw = r.get(HFT_CONTROL_KEY)
    if not raw:
        return dict(_CONTROL_DEFAULTS)
    try:
        return {**_CONTROL_DEFAULTS, **json.loads(raw)}
    except (json.JSONDecodeError, TypeError):
        return dict(_CONTROL_DEFAULTS)


def _write_control(r, ctrl: Dict[str, Any]) -> None:
    r.set(HFT_CONTROL_KEY, json.dumps(ctrl))


def _read_state(r) -> Optional[Dict[str, Any]]:
    raw = r.get(HFT_STATE_KEY)
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None


def _read_order_by_id(r, user_no: str, order_id: str) -> Optional[Dict[str, Any]]:
    if not order_id:
        return None
    from backend.core.live_state_kalshi_portfolio import tenant_kalshi_orders_key
    try:
        raw = r.hget(tenant_kalshi_orders_key(user_no), order_id)
        if not raw:
            return None
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None


def _format_order_price(rec: Dict[str, Any]) -> str:
    price = rec.get("yes_price_dollars")
    if price is not None:
        try:
            return f"{float(price):.2f}"
        except (TypeError, ValueError):
            pass
    return "--"


def _format_remaining(rec: Dict[str, Any]) -> str:
    rem = rec.get("remaining_count_fp")
    if rem is None:
        rem = rec.get("remaining_count")
    if rem is None:
        return "--"
    try:
        val = float(rem)
        if val == int(val):
            return str(int(val))
        return f"{val:.2f}"
    except (TypeError, ValueError):
        return "--"


def _position_fp(rec: Dict[str, Any]) -> float:
    try:
        return float(rec.get("position_fp") or 0)
    except (TypeError, ValueError):
        return 0.0


def _close_side_for_position_fp(position_fp: float) -> Optional[str]:
    if position_fp > 0.001:
        return "ask"
    if position_fp < -0.001:
        return "bid"
    return None


def _order_row_from_rec(rec: Dict[str, Any], dir_label: str, fallback_side: str) -> Dict[str, Any]:
    side = str(rec.get("orderbook_side") or rec.get("side") or fallback_side).lower()
    if side not in ("bid", "ask"):
        side = fallback_side
    return {
        "order_id": rec.get("order_id"),
        "ticker": rec.get("ticker"),
        "side": side,
        "price": _format_order_price(rec),
        "remaining_count": _format_remaining(rec),
        "dir": dir_label,
    }


def _build_resting_orders_for_ui(
    r,
    user_no: str,
    engine: Optional[Dict[str, Any]],
) -> list:
    """Rows for HF monitor: engine-tracked OIDs plus live hot-state lookup."""
    rows: list = []
    seen_oids: set[str] = set()

    def _append(oid: Optional[str], dir_label: str, fallback_side: str, fallback_price: str):
        if not oid or oid in seen_oids:
            return
        rec = _read_order_by_id(r, user_no, oid)
        if rec and str(rec.get("status") or "").lower() not in ("", "resting"):
            return
        side = fallback_side
        if rec:
            side = str(rec.get("orderbook_side") or rec.get("side") or fallback_side).lower()
            if side not in ("bid", "ask"):
                side = fallback_side
        price = _format_order_price(rec) if rec else fallback_price
        remaining = _format_remaining(rec) if rec else "--"
        ticker = ""
        if rec:
            ticker = str(rec.get("ticker") or "").strip()
        if not ticker and engine:
            ticker = str(engine.get("active_ticker") or "").strip()
        rows.append({
            "order_id": oid,
            "ticker": ticker or None,
            "side": side,
            "price": price,
            "remaining_count": remaining,
            "dir": dir_label,
        })
        seen_oids.add(oid)

    if engine:
        bid_oid = engine.get("my_bid_oid")
        ask_oid = engine.get("my_ask_oid")
        counter_oid = engine.get("counter_oid")
        entry_side = engine.get("entry_side")
        gate_bid = engine.get("gate_best_bid") or "--"
        gate_ask = engine.get("gate_best_ask") or "--"
        entry_price = engine.get("entry_price") or "--"

        _append(bid_oid, "entry", "bid", gate_bid if gate_bid != "--" else str(entry_price))
        _append(ask_oid, "entry", "ask", gate_ask if gate_ask != "--" else str(entry_price))
        close_side = "ask" if entry_side == "long" else "bid"
        close_price = gate_ask if close_side == "ask" else gate_bid
        if close_price == "--":
            close_price = str(entry_price)
        _append(counter_oid, "close", close_side, close_price)

    return rows


def _merge_portfolio_resting_for_open_positions(
    user_no: str,
    subaccount: int,
    positions: list,
    rows: list,
) -> list:
    """Add resting orders from portfolio hot state for tickers with open positions."""
    from backend.core.live_state_kalshi_portfolio import list_orders

    open_by_ticker: Dict[str, float] = {}
    for pos in positions:
        fp = _position_fp(pos)
        ticker = str(pos.get("ticker") or "").strip()
        if ticker and abs(fp) > 0.001:
            open_by_ticker[ticker] = fp
    if not open_by_ticker:
        return rows

    seen_oids = {str(o.get("order_id") or "") for o in rows if o.get("order_id")}

    try:
        all_orders = list_orders(user_no)
    except Exception:
        return rows

    for rec in all_orders:
        if str(rec.get("status") or "").lower() != "resting":
            continue
        try:
            if int(rec.get("subaccount") or 0) != int(subaccount):
                continue
        except (TypeError, ValueError):
            continue
        ticker = str(rec.get("ticker") or "").strip()
        if ticker not in open_by_ticker:
            continue
        oid = str(rec.get("order_id") or "")
        if not oid or oid in seen_oids:
            continue
        pos_fp = open_by_ticker[ticker]
        side = str(rec.get("orderbook_side") or "").lower()
        if side not in ("bid", "ask"):
            continue
        close_side = _close_side_for_position_fp(pos_fp)
        dir_label = "close" if close_side and side == close_side else "entry"
        rows.append(_order_row_from_rec(rec, dir_label, side))
        seen_oids.add(oid)

    return rows


def _compute_resting_orders_panel(
    positions: list,
    engine: Optional[Dict[str, Any]],
    orders: list,
) -> Dict[str, Any]:
    """UI hint when subaccount has exposure but no visible resting close order."""
    open_pos = [p for p in positions if abs(_position_fp(p)) > 0.001]
    in_cooldown = bool(engine and engine.get("in_cooldown"))
    has_close_resting = any(str(o.get("dir") or "").lower() == "close" for o in orders)

    if not open_pos:
        return {
            "has_open_position": False,
            "seeking_close": False,
            "seeking_close_side": None,
            "in_cooldown": in_cooldown,
        }

    if has_close_resting:
        return {
            "has_open_position": True,
            "seeking_close": False,
            "seeking_close_side": None,
            "in_cooldown": in_cooldown,
        }

    seeking_side: Optional[str] = None
    if engine and engine.get("seeking_close_side") in ("bid", "ask"):
        seeking_side = str(engine["seeking_close_side"])
    if not seeking_side and engine and engine.get("entry_side") == "long":
        seeking_side = "ask"
    elif not seeking_side and engine and engine.get("entry_side") == "short":
        seeking_side = "bid"
    if not seeking_side:
        active = str((engine or {}).get("active_ticker") or "").strip()
        primary = None
        for pos in open_pos:
            if active and str(pos.get("ticker") or "").strip() == active:
                primary = pos
                break
        if primary is None:
            primary = max(open_pos, key=lambda p: abs(_position_fp(p)))
        seeking_side = _close_side_for_position_fp(_position_fp(primary))

    return {
        "has_open_position": True,
        "seeking_close": True,
        "seeking_close_side": seeking_side,
        "in_cooldown": in_cooldown,
    }


def _read_positions_for_subaccount(r, subaccount: int) -> list:
    """Read positions from Redis hot state filtered by subaccount."""
    import os
    from backend.core.live_state_kalshi_portfolio import (
        list_positions,
    )
    user_no = os.getenv("REC_USER_NO", "0001").strip()
    try:
        all_pos = list_positions(user_no)
    except Exception:
        return []
    return [
        p for p in all_pos
        if p.get("subaccount") == subaccount
    ]


@hft_router.post("/api/hft/toggle")
async def hft_toggle(request: dict):
    """Toggle HFT engine enabled/disabled."""
    r = _redis()
    if not r:
        return JSONResponse({"status": "error", "message": "Redis unavailable"}, status_code=503)
    ctrl = _read_control(r)
    if "enabled" in request:
        ctrl["enabled"] = bool(request["enabled"])
    else:
        ctrl["enabled"] = not ctrl["enabled"]
    _write_control(r, ctrl)
    logger.info("HFT toggle: enabled=%s", ctrl["enabled"])
    return {"status": "ok", "enabled": ctrl["enabled"]}


@hft_router.get("/api/hft/status")
async def hft_status():
    """Return current HFT state, gate values, control config, and positions for the HFT subaccount."""
    r = _redis()
    if not r:
        return JSONResponse({"status": "error", "message": "Redis unavailable"}, status_code=503)
    import os
    ctrl = _read_control(r)
    state = _read_state(r)
    subaccount = ctrl.get("subaccount", 2)
    positions = _read_positions_for_subaccount(r, subaccount)
    user_no = os.getenv("REC_USER_NO", "0001").strip()
    resting_orders = _build_resting_orders_for_ui(r, user_no, state)
    resting_orders = _merge_portfolio_resting_for_open_positions(
        user_no, subaccount, positions, resting_orders,
    )
    resting_orders_panel = _compute_resting_orders_panel(
        positions, state, resting_orders,
    )
    return {
        "status": "ok",
        "control": ctrl,
        "engine": state,
        "process": hft_process_status(r),
        "positions": positions,
        "resting_orders": resting_orders,
        "resting_orders_panel": resting_orders_panel,
    }


@hft_router.post("/api/hft/process")
async def hft_process(request: dict):
    """Start or stop the HFT engine process (singleton — at most one instance)."""
    import os

    action = str(request.get("action") or "").strip().lower()
    if not action and "running" in request:
        action = "start" if bool(request["running"]) else "stop"
    if action not in ("start", "stop"):
        return JSONResponse(
            {"status": "error", "message": "action must be 'start' or 'stop'"},
            status_code=400,
        )

    user_no = os.getenv("REC_USER_NO", "0001").strip()
    if action == "start":
        result = start_hft_engine(user_no=user_no)
    else:
        result = stop_hft_engine()

    if result.get("status") == "error":
        return JSONResponse(result, status_code=500)
    return result


@hft_router.post("/api/hft/config")
async def hft_config(request: dict):
    """Update HFT configuration (subaccount, count, ticker_filter)."""
    r = _redis()
    if not r:
        return JSONResponse({"status": "error", "message": "Redis unavailable"}, status_code=503)
    ctrl = _read_control(r)
    if "subaccount" in request:
        try:
            ctrl["subaccount"] = int(request["subaccount"])
        except (TypeError, ValueError):
            return JSONResponse({"status": "error", "message": "Invalid subaccount"}, status_code=400)
    if "count" in request:
        try:
            val = float(request["count"])
            ctrl["count"] = f"{val:.2f}"
        except (TypeError, ValueError):
            return JSONResponse({"status": "error", "message": "Invalid count"}, status_code=400)
    if "ticker_filter" in request:
        ctrl["ticker_filter"] = str(request["ticker_filter"]).strip()
    if "neutral_mode" in request:
        ctrl["neutral_mode"] = bool(request["neutral_mode"])
    _write_control(r, ctrl)
    logger.info("HFT config updated: %s", ctrl)
    return {"status": "ok", "control": ctrl}
