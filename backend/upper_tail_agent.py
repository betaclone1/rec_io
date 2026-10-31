"""
Upper Tail agent — one GTC limit when orderbook touch reaches the target rail.

Outside trade_executor. Watches Kalshi orderbook Redis (market_watchdog OB
channel) during the monitor time window. When best YES or NO bid/ask is at or
above the target (e.g. $0.99), places a single GTC at that price on that side
(``post_only`` off). Venue fill confirmation books into trade_manager.
Paper monitors book when orderbook touch qualifies (no venue order).
"""

from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional

import requests
import uvicorn
from fastapi import FastAPI

from backend.core.aes_btc15m_lower_tail_cutout import resolve_monitor_limit_dollars
from backend.core.kalshi_event_market_fetch import fetch_market_payload
from backend.core.lower_tail_kalshi import (
    cancel_order,
    extract_order_id,
    place_limit_gtc,
    v2_price_for_limit_side,
)
from backend.core.lower_tail_open import (
    fetch_series_15m_markets,
    select_live_targets_by_symbol,
)
from backend.core.orderbook_strike_prices import touch_dollars_for_ticker
from backend.core.port_config import default_pool_user_number, get_port
from backend.core.upper_tail import (
    STRATEGY_NAME,
    floor_strike_from_market,
    list_active_upper_tail_monitor_rows,
    upper_tail_series_tickers,
    upper_tail_side_from_orderbook,
    ttc_in_entry_window,
)
from backend.core.time_eastern import now_est
from backend.trading_mode import effective_paper_trade

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] upper_tail_agent: %(message)s",
)
log = logging.getLogger("upper_tail_agent")

POLL_SEC = float(os.getenv("UPPER_TAIL_POLL_SEC", "0.25"))

app = FastAPI(title="Upper Tail Agent")
_wake = threading.Event()
_lock = threading.Lock()
_started_at = time.time()
_prev_auto_trade_status: Dict[str, str] = {}


def _user_no() -> str:
    return default_pool_user_number()


def _log(msg: str) -> None:
    log.info("[%s] %s", _user_no(), msg)


@dataclass
class _Cycle:
    monitor_id: str
    symbol: str
    ticker: str
    event_ticker: str
    limit_px: float
    contracts: int
    subaccount: int
    paper: bool
    floor_strike: Optional[float]
    close_ts: float
    min_time: int
    max_time: int
    bankroll_cents: Optional[float]
    side: Optional[str] = None
    order_id: Optional[str] = None
    placed: bool = False
    done: bool = False
    trade_id: Optional[int] = None
    fill_sync_done: bool = False
    floor_fetch_mono: float = 0.0
    floor_miss_logged: bool = False


_cycles: Dict[str, _Cycle] = {}


def _parse_int(raw: Any, default: int = 0) -> int:
    try:
        return int(float(raw))
    except (TypeError, ValueError):
        return default


def _parse_px(raw: Any) -> Optional[float]:
    if raw is None or str(raw).strip() == "":
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _set_auto_trade_status(monitor_id: str, status: str) -> None:
    """Persist auto_trade_status + preferences notify (no-op when unchanged)."""
    mid = str(monitor_id)
    prev = _prev_auto_trade_status.get(mid)
    if prev == status:
        return
    _prev_auto_trade_status[mid] = status
    un = _user_no()
    try:
        from backend.core.config.database import get_postgresql_connection
        from backend.core.tenant_legacy_sql import legacy_users_monitor_list

        ml = legacy_users_monitor_list(un)
        conn = get_postgresql_connection()
        if not conn:
            return
        try:
            with conn.cursor() as cur:
                cur.execute(
                    f"UPDATE {ml} SET auto_trade_status = %s, updated_at = CURRENT_TIMESTAMP WHERE id = %s",
                    (status, int(mid)),
                )
            conn.commit()
        finally:
            conn.close()
        _log(f"auto_trade_status monitor={mid} {prev} → {status}")
    except Exception as exc:
        _log(f"auto_trade_status write failed monitor={mid}: {exc}")
        return
    try:
        from backend.core.trading_redis_comms import (
            publish_preferences_event,
            use_trading_redis_comms,
        )

        if use_trading_redis_comms():
            publish_preferences_event(
                "auto_trade_status_change",
                {
                    "monitor_id": f"mon_{un}_{mid}",
                    "auto_trade_status": status,
                },
                tenant_user_no=un,
            )
    except Exception as exc:
        _log(f"auto_trade_status notify failed monitor={mid}: {exc}")


def _sync_statuses(monitors: list) -> None:
    for mon in monitors:
        mid = str(mon["monitor_id"])
        limit_px = resolve_monitor_limit_dollars(mon)
        contracts = _parse_int(mon.get("total_position"))
        if not mon.get("auto_trade"):
            status = "DISABLED"
        elif limit_px is None or limit_px <= 0 or limit_px >= 1 or contracts <= 0:
            status = "DISABLED"
        else:
            status = "ACTIVE"
        _set_auto_trade_status(mid, status)


def _order_fill_qty(order_id: Optional[str]) -> float:
    if not order_id:
        return 0.0
    try:
        from backend.core.live_state_kalshi_portfolio import get_order

        rec = get_order(_user_no(), order_id)
        if not isinstance(rec, dict):
            return 0.0
        return float(rec.get("fill_count_fp") or 0)
    except (TypeError, ValueError):
        return 0.0
    except Exception:
        return 0.0


def _cancel(order_id: Optional[str], *, ticker: str, subaccount: int) -> None:
    oid = str(order_id or "").strip()
    if not oid or oid.startswith("paper_"):
        return
    ok = cancel_order(oid, subaccount=subaccount, market_ticker=ticker)
    if not ok:
        cancel_order(oid, subaccount=subaccount, market_ticker=ticker)


_FLOOR_FETCH_COOLDOWN_SEC = 5.0


def _maybe_fetch_floor(cy: _Cycle) -> None:
    """Fill floor_strike from GET /markets/{ticker} when the series list omitted it."""
    if cy.floor_strike is not None:
        return
    now = time.monotonic()
    if now - cy.floor_fetch_mono < _FLOOR_FETCH_COOLDOWN_SEC:
        return
    cy.floor_fetch_mono = now
    market = fetch_market_payload(cy.ticker, timeout_sec=4.0)
    floor = floor_strike_from_market(market)
    if floor is None:
        if not cy.floor_miss_logged:
            _log(
                f"floor pending monitor={cy.monitor_id} ticker={cy.ticker}: "
                "GET /markets omitted floor_strike"
            )
            cy.floor_miss_logged = True
        return
    cy.floor_strike = floor
    cy.floor_miss_logged = False
    _log(
        f"floor monitor={cy.monitor_id} ticker={cy.ticker} floor_strike={floor}"
    )


def _fill_prob_diff(ticker: str, side: str) -> tuple:
    """Side-aware strike-ladder prob (%) and diff. (None, None) when the symbol has no ladder row."""
    from backend.lower_tail_agent import ladder_prob_diff_at_fill

    return ladder_prob_diff_at_fill(ticker, side)


def _book(cy: _Cycle, *, side: str, fill_qty: float) -> Optional[int]:
    if cy.floor_strike is None:
        if not cy.floor_miss_logged:
            _log(f"TM book skipped monitor={cy.monitor_id}: missing floor_strike")
            cy.floor_miss_logged = True
        return None
    port = get_port("trade_manager")
    est = now_est()
    un = _user_no()
    ticket_id = f"ut_{un}_{cy.monitor_id}_{cy.ticker}_{side}"
    prob, diff = _fill_prob_diff(cy.ticker, side)
    payload = {
        "intent": "upper_tail_fill",
        "ticket_id": ticket_id,
        "symbol": cy.symbol,
        "market": "15m",
        "exchange": "kalshi",
        "trade_strategy": STRATEGY_NAME,
        "strike": float(cy.floor_strike),
        "side": side,
        "ticker": cy.ticker,
        "buy_price": cy.limit_px,
        "position": fill_qty,
        "count_fp": f"{fill_qty:.2f}",
        "initial_count": float(cy.contracts),
        "monitor": f"mon_{un}_{cy.monitor_id}",
        "subaccount": int(cy.subaccount),
        "paper_trade": bool(cy.paper),
        "entry_method": "upper_tail",
        "order_id_open": cy.order_id or "",
        "time_in_force": "good_till_canceled",
        "order_type": "limit",
        "date": est.strftime("%Y-%m-%d"),
        "time": est.strftime("%H:%M:%S"),
    }
    if cy.bankroll_cents is not None:
        payload["bankroll_allotment_total"] = cy.bankroll_cents
    # Strike-table snapshot when this symbol publishes prob/diff. Lean markets stay NULL.
    if prob is not None:
        payload["prob"] = prob
    if diff is not None:
        payload["diff"] = diff
    elif prob is None:
        _log(
            f"fill ladder snapshot missing ticker={cy.ticker} side={side} "
            f"monitor={cy.monitor_id} — booking with NULL prob/diff"
        )
    try:
        resp = requests.post(
            f"http://127.0.0.1:{port}/trades",
            json=payload,
            timeout=30,
        )
        if resp.status_code not in (200, 201):
            _log(f"TM book failed status={resp.status_code} body={resp.text[:400]}")
            return None
        data = resp.json() if resp.content else {}
        tid = data.get("id") or data.get("trade_id")
        return int(tid) if tid is not None else None
    except Exception as exc:
        _log(f"TM book exception: {exc}")
        return None


def _place_live(cy: _Cycle, side: str) -> bool:
    book_side = "bid" if side == "yes" else "ask"
    try:
        v2_price_for_limit_side(side=book_side, limit_dollars=cy.limit_px)
    except ValueError as exc:
        _log(f"skip monitor={cy.monitor_id}: price map failed: {exc}")
        return False
    res = place_limit_gtc(
        ticker=cy.ticker,
        side=book_side,
        limit_dollars=cy.limit_px,
        count=cy.contracts,
        subaccount=cy.subaccount,
        post_only=False,
        self_trade_prevention_type="taker_at_cross",
    )
    oid = extract_order_id(res.api_json if res else None)
    if not oid:
        _log(f"place failed monitor={cy.monitor_id} side={side} ticker={cy.ticker}")
        return False
    cy.side = side
    cy.order_id = oid
    cy.placed = True
    _log(
        f"GTC monitor={cy.monitor_id} ticker={cy.ticker} side={side} "
        f"oid={oid} @{cy.limit_px:.4f} ct={cy.contracts} sa={cy.subaccount}"
    )
    return True


def _qualifying_side(cy: _Cycle, *, now: float) -> Optional[str]:
    """Fire when orderbook best bid or ask has reached the monitor limit."""
    now_ttc = cy.close_ts - now
    if not ttc_in_entry_window(ttc=now_ttc, min_time=cy.min_time, max_time=cy.max_time):
        return None
    touch = touch_dollars_for_ticker(cy.ticker)
    if not touch:
        return None
    return upper_tail_side_from_orderbook(
        yes_ask=_parse_px(touch.get("yes_ask_dollars")),
        no_ask=_parse_px(touch.get("no_ask_dollars")),
        yes_bid=_parse_px(touch.get("yes_bid_dollars")),
        no_bid=_parse_px(touch.get("no_bid_dollars")),
        limit_px=cy.limit_px,
    )


def _drop_cycle(mid: str, cy: _Cycle, *, reason: str) -> None:
    if cy.placed and not cy.done and not cy.paper:
        _cancel(cy.order_id, ticker=cy.ticker, subaccount=cy.subaccount)
    _log(f"drop monitor={mid} event={cy.event_ticker} reason={reason}")
    _cycles.pop(mid, None)


def _on_fill(cy: _Cycle, *, side: str, qty: float) -> None:
    if qty <= 0 or cy.done and cy.fill_sync_done:
        return
    tid = _book(cy, side=side, fill_qty=qty)
    if tid is None:
        return
    cy.trade_id = tid
    cy.done = True
    cy.fill_sync_done = bool(cy.paper)
    _log(
        f"fill monitor={cy.monitor_id} side={side} qty={qty} "
        f"trade_id={tid} ticker={cy.ticker}"
    )


def _live_markets() -> list:
    out: list = []
    for series in upper_tail_series_tickers():
        out.extend(fetch_series_15m_markets(series))
    return out


def _tick() -> None:
    monitors = list_active_upper_tail_monitor_rows()
    _sync_statuses(monitors)
    live = select_live_targets_by_symbol(_live_markets())
    now = time.time()
    active_ids = set()
    for mon in monitors:
        if not mon.get("auto_trade"):
            continue
        mid = str(mon["monitor_id"])
        sym = str(mon.get("symbol") or "").strip().upper()
        limit_px = resolve_monitor_limit_dollars(mon)
        contracts = _parse_int(mon.get("total_position"))
        if limit_px is None or contracts <= 0:
            continue
        tgt = live.get(sym)
        if tgt is None:
            cy = _cycles.get(mid)
            if cy is not None:
                _drop_cycle(mid, cy, reason="no_live_market")
            continue
        active_ids.add(mid)
        paper = effective_paper_trade(mon.get("paper_trade") or mon.get("test_filter"))
        cy = _cycles.get(mid)
        if cy is None or cy.event_ticker != tgt.event_ticker:
            if cy is not None:
                _drop_cycle(mid, cy, reason="new_cycle")
            try:
                bankroll = (
                    float(mon["bankroll_allotment_total"])
                    if mon.get("bankroll_allotment_total") is not None
                    else None
                )
            except (TypeError, ValueError):
                bankroll = None
            cy = _Cycle(
                monitor_id=mid,
                symbol=sym,
                ticker=tgt.market_ticker,
                event_ticker=tgt.event_ticker,
                limit_px=float(limit_px),
                contracts=contracts,
                subaccount=int(mon.get("subaccount") or 1),
                paper=paper,
                floor_strike=tgt.floor_strike,
                close_ts=float(tgt.close_ts),
                min_time=_parse_int(mon.get("min_time")),
                max_time=_parse_int(mon.get("max_time"), 900),
                bankroll_cents=bankroll,
            )
            _cycles[mid] = cy

        if cy.floor_strike is None and tgt.floor_strike is not None:
            cy.floor_strike = float(tgt.floor_strike)
        if cy.floor_strike is None:
            _maybe_fetch_floor(cy)

        now_ttc = cy.close_ts - now
        in_window = ttc_in_entry_window(
            ttc=now_ttc, min_time=cy.min_time, max_time=cy.max_time
        )
        if cy.done and not cy.fill_sync_done and not cy.paper and cy.side:
            qty = _order_fill_qty(cy.order_id)
            if qty > 0:
                _on_fill(cy, side=cy.side, qty=qty)
            if qty + 1e-9 >= float(cy.contracts) or now_ttc <= 0:
                cy.fill_sync_done = True
            continue
        if cy.placed and not cy.done:
            if cy.paper:
                continue
            qty = _order_fill_qty(cy.order_id)
            if qty > 0 and cy.side:
                _on_fill(cy, side=cy.side, qty=qty)
            elif not in_window:
                _cancel(cy.order_id, ticker=cy.ticker, subaccount=cy.subaccount)
                cy.done = True
                cy.fill_sync_done = True
                _log(
                    f"cancel unfilled monitor={mid} ticker={cy.ticker} "
                    f"ttc={now_ttc:.1f} window={cy.min_time}-{cy.max_time}"
                )
            continue
        if cy.done or cy.placed or not in_window:
            continue
        side = _qualifying_side(cy, now=now)
        if not side:
            continue
        if cy.paper:
            cy.side = side
            cy.order_id = f"paper_{side}_{mid}"
            _on_fill(cy, side=side, qty=float(cy.contracts))
            if cy.done:
                cy.placed = True
                cy.fill_sync_done = True
            continue
        _place_live(cy, side)

    for mid, cy in list(_cycles.items()):
        if mid not in active_ids:
            _drop_cycle(mid, cy, reason="monitor_inactive")


def _loop() -> None:
    _log("main loop started")
    while True:
        try:
            _tick()
        except Exception as exc:
            _log(f"tick error: {exc}")
        _wake.wait(timeout=POLL_SEC)
        _wake.clear()


def _start_listeners() -> None:
    try:
        from backend.core.orderbook_hot_subscriber import start_orderbook_hot_subscriber

        def _on_ob(_snap: Any) -> None:
            _wake.set()

        ok = start_orderbook_hot_subscriber(
            _on_ob,
            thread_name="upper_tail_ob",
        )
        if ok:
            _log("subscribed rec_io:live_state:updated (orderbook touch)")
        else:
            _log("orderbook listener not started: redis unavailable")
    except Exception as exc:
        _log(f"orderbook listener not started: {exc}")


@app.get("/health")
def health() -> Dict[str, Any]:
    with _lock:
        n = len(_cycles)
    return {
        "status": "ok",
        "service": "upper_tail_agent",
        "user_no": _user_no(),
        "cycles": n,
        "uptime_sec": round(time.time() - _started_at, 1),
    }


def main() -> None:
    un = _user_no()
    _start_listeners()
    threading.Thread(target=_loop, name="upper_tail_main", daemon=True).start()
    try:
        port = get_port(f"upper_tail_agent_{un}")
    except Exception:
        port = 8052 if un == "0001" else 8053
    _log(f"health on port {port}")
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


if __name__ == "__main__":
    main()
