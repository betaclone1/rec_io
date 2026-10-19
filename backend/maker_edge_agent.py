"""
Maker Edge agent — dual BID/ASK post-only GTC at Kalshi market open_time.

Outside trade_executor: places/cancels rests, books first fill into trade_manager.
Per-tenant supervisord worker (REC_USER_SCHEMA / REC_POOL_USER_NUMBER).

Placement is armed from Kalshi ``open_time`` and fires at that instant (sleep +
short busy-spin). No TTC / ladder gate for arming or place.
"""

from __future__ import annotations

import logging
import os
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

import requests
import uvicorn
from fastapi import FastAPI

from backend.core.aes_btc15m_maker_edge_cutout import (
    STRATEGY_NAME,
    list_active_maker_edge_monitor_rows,
    resolve_monitor_limit_dollars,
)
from backend.core.maker_edge_kalshi import (
    PlaceResult,
    build_place_body,
    cancel_order,
    encode_place_body,
    extract_order_id,
    place_post_only_gtc,
    warm_kalshi_http,
    v2_price_for_limit_side,
)
from backend.core.maker_edge_open import (
    LATE_PLACE_GRACE_SEC,
    OpenTarget,
    fetch_live_market,
    fetch_next_open_target,
    wait_until_open_ts,
)
from backend.core.port_config import default_pool_user_number, get_port
from backend.core.time_eastern import now_est
from backend.trading_mode import effective_paper_trade

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] maker_edge_agent: %(message)s",
)
log = logging.getLogger("maker_edge_agent")

FAILSAFE_POLL_SEC = float(os.getenv("MAKER_EDGE_FAILSAFE_POLL_SEC", "1.0"))
MAX_CONCURRENT_MARKETS = int(os.getenv("MAKER_EDGE_MAX_CONCURRENT", "1"))
# Re-warm TLS/signing ~1s before open so a long arm sleep does not leave a cold pool.
_REWARM_BEFORE_OPEN_SEC = float(os.getenv("MAKER_EDGE_REWARM_BEFORE_OPEN_SEC", "1.0"))
# Persistent pool — avoid ThreadPoolExecutor construct/teardown on every open.
_PLACE_POOL = ThreadPoolExecutor(max_workers=4, thread_name_prefix="me_place")
# How often to refresh the next open_time target while waiting.
OPEN_DISCOVER_POLL_SEC = float(os.getenv("MAKER_EDGE_OPEN_DISCOVER_POLL_SEC", "5.0"))

app = FastAPI(title="Maker Edge Agent")
_wake = threading.Event()
_lock = threading.Lock()


def _user_no() -> str:
    return default_pool_user_number()


@dataclass
class DualRestState:
    monitor_id: str
    ticker: str
    event_ticker: str
    limit_px: float
    contracts: int
    subaccount: int
    paper: bool
    floor_strike: Optional[float]
    bankroll_cents: Optional[float] = None
    # min_time > 0: cancel unfilled rests when TTC <= min_time. min_time == 0: never.
    min_time: int = 0
    bid_order_id: Optional[str] = None
    ask_order_id: Optional[str] = None
    filled_side: Optional[str] = None  # yes | no
    fill_qty: Optional[float] = None
    # Ladder snapshot at fill (after sibling cancel); reused on TM book retry.
    fill_prob: Optional[float] = None
    fill_diff: Optional[float] = None
    trade_id: Optional[int] = None
    # Placement/sibling work finished for this cycle (do not re-arm dual rests).
    done: bool = False
    # Live: keep pushing venue cumulative fill_count to TM until order residual is 0.
    fill_sync_done: bool = False


# monitor_id -> active dual rest for current cycle
_active: Dict[str, DualRestState] = {}
_last_event_ticker: Optional[str] = None
_started_at = time.time()
# monitor_id -> last written auto_trade_status (dashboard badge)
_prev_auto_trade_status: Dict[str, str] = {}
# Open-time arming: one waiter per event_ticker
_armed_event: Optional[str] = None
_armed_target: Optional[OpenTarget] = None
_arm_thread: Optional[threading.Thread] = None
_placed_events: set[str] = set()
# Events finished for this process (fill booked or min_ttc cancel) — do not recovery-place.
_completed_events: set[str] = set()
_last_discover_mono: float = 0.0


@dataclass
class _PreparedPlace:
    """Hot-path place plan built before open_time (no I/O after fire)."""

    monitor_id: str
    ticker: str
    event_ticker: str
    limit_px: float
    contracts: int
    subaccount: int
    paper: bool
    floor_strike: Optional[float]
    bankroll_cents: Optional[float]
    min_time: int
    bid_price: str
    ask_price: str
    bid_body_bytes: bytes
    ask_body_bytes: bytes


def _log(msg: str) -> None:
    log.info("[%s] %s", _user_no(), msg)


def determine_maker_edge_auto_trade_status(
    *,
    auto_trade: bool,
    limit_px: Optional[float],
    contracts: int,
    ttc: Optional[int] = None,
    min_time: Any = None,
    max_time: Any = None,
) -> str:
    """
    Dashboard badge values (same vocabulary as AES): DISABLED / ACTIVE / INACTIVE.

    Placement is open_time-driven (not TTC). ACTIVE = configured and armed to place
    at each market open; INACTIVE unused for window gating.
    """
    del ttc, min_time, max_time  # retained for call-site compat; not used
    if not auto_trade:
        return "DISABLED"
    if limit_px is None or limit_px <= 0 or limit_px >= 1:
        return "DISABLED"
    if contracts <= 0:
        return "DISABLED"
    return "ACTIVE"


def _set_auto_trade_status(monitor_id: str, status: str) -> None:
    """Persist auto_trade_status + preferences WS notify (no-op when unchanged)."""
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


def _sync_monitor_statuses(monitors: list) -> None:
    for mon in monitors:
        mid = str(mon["monitor_id"])
        limit_px = resolve_monitor_limit_dollars(mon)
        try:
            contracts = int(round(float(mon.get("total_position") or 0)))
        except (TypeError, ValueError):
            contracts = 0
        status = determine_maker_edge_auto_trade_status(
            auto_trade=bool(mon.get("auto_trade")),
            limit_px=limit_px,
            contracts=contracts,
        )
        _set_auto_trade_status(mid, status)


@app.get("/health")
def health() -> Dict[str, Any]:
    with _lock:
        n = len(_active)
    return {
        "status": "ok",
        "service": "maker_edge_agent",
        "user_no": _user_no(),
        "active_dual_rests": n,
        "uptime_sec": round(time.time() - _started_at, 1),
    }


def _resolve_floor_strike(ticker: str, hint: Optional[float] = None) -> Optional[float]:
    """Authoritative floor from live ladder when available; else hint from market payload."""
    if hint is not None:
        try:
            return float(hint)
        except (TypeError, ValueError):
            pass
    row = _ladder_row_for_ticker(ticker)
    if not row:
        return None
    for key in ("strike", "floor_strike"):
        raw = row.get(key)
        if raw is None:
            continue
        try:
            return float(raw)
        except (TypeError, ValueError):
            continue
    return None


def _current_ttc_seconds() -> Optional[int]:
    from backend.core.tradeflow_live_reads import strike_ladder, ttc_seconds_from_ladder

    ladder = strike_ladder("BTC", "15m", "kalshi")
    if not ladder:
        return None
    ttc = ttc_seconds_from_ladder(ladder, "15m")
    return int(ttc) if ttc is not None else None


def _parse_min_time(raw: Any) -> int:
    try:
        return max(0, int(float(raw)))
    except (TypeError, ValueError):
        return 0


def should_cancel_unfilled_at_min_ttc(*, min_time: int, ttc: Optional[int]) -> bool:
    """True when min_time > 0 and live TTC has reached/passed that floor."""
    if min_time <= 0 or ttc is None:
        return False
    return int(ttc) <= int(min_time)


def _cancel_order_routed(order_id: Optional[str], *, ticker: str, subaccount: int) -> bool:
    """Cancel with V2 market_ticker routing; retry once on failure."""
    oid = str(order_id or "").strip()
    if not oid:
        return False
    ok = cancel_order(oid, subaccount=subaccount, market_ticker=ticker)
    if ok:
        return True
    ok = cancel_order(oid, subaccount=subaccount, market_ticker=ticker)
    if not ok:
        _log(f"CANCEL FAILED oid={oid} ticker={ticker} sa={subaccount}")
    return ok


def _cancel_unfilled_rests(st: DualRestState, *, reason: str) -> None:
    """Cancel both resting legs; mark cycle done with no fill (no TM book)."""
    if st.done:
        return
    if not st.paper:
        if st.bid_order_id:
            _cancel_order_routed(
                st.bid_order_id, ticker=st.ticker, subaccount=st.subaccount
            )
        if st.ask_order_id:
            _cancel_order_routed(
                st.ask_order_id, ticker=st.ticker, subaccount=st.subaccount
            )
    st.done = True
    _completed_events.add(st.event_ticker)
    _log(
        f"cancel unfilled monitor={st.monitor_id} ticker={st.ticker} "
        f"reason={reason} min_time={st.min_time}"
    )


def _order_portfolio_rec(order_id: Optional[str]) -> Optional[Dict[str, Any]]:
    if not order_id:
        return None
    try:
        from backend.core.live_state_kalshi_portfolio import get_order

        rec = get_order(_user_no(), order_id)
        return rec if isinstance(rec, dict) else None
    except Exception:
        return None


def _order_fill_qty(order_id: Optional[str]) -> float:
    rec = _order_portfolio_rec(order_id)
    if not rec:
        return 0.0
    try:
        return float(rec.get("fill_count_fp") or 0)
    except (TypeError, ValueError):
        return 0.0


def _order_remaining_qty(order_id: Optional[str]) -> Optional[float]:
    """Remaining resting size from portfolio hot state; None if unknown."""
    rec = _order_portfolio_rec(order_id)
    if not rec:
        return None
    raw = rec.get("remaining_count_fp")
    if raw is None:
        raw = rec.get("remaining_count")
    if raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _ladder_row_for_ticker(ticker: str) -> Optional[Dict[str, Any]]:
    from backend.core.tradeflow_live_reads import strike_ladder

    ladder = strike_ladder("BTC", "15m", "kalshi")
    if not ladder:
        return None
    want = str(ticker or "").strip()
    for row in ladder.get("strikes") or []:
        if not isinstance(row, dict):
            continue
        if str(row.get("ticker") or "").strip() == want:
            return row
    return None


def _ladder_side_ask(ticker: str, side: str) -> Optional[float]:
    """Paper fill probe: yes_ask / no_ask for the resting ticker.

    Prefer Redis orderbook for that exact market_ticker (works at open before the
    strike ladder rolls). Ladder is secondary only when OB touch is unavailable.
    """
    key = "yes_ask_dollars" if side == "yes" else "no_ask_dollars"
    try:
        from backend.core.orderbook_strike_prices import resolve_orderbook_touch_dollars

        touch, _reason = resolve_orderbook_touch_dollars(ticker)
        if touch and touch.get(key) is not None:
            return float(touch[key])
    except (TypeError, ValueError):
        pass
    except Exception:
        pass
    row = _ladder_row_for_ticker(ticker)
    if not row:
        return None
    try:
        v = row.get(key)
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def ladder_prob_diff_at_fill(
    ticker: str, side: str
) -> Tuple[Optional[float], Optional[float]]:
    """Side-aware model prob (%) and ladder edge diff for the filled leg.

    Same sources AES stamps on HTC / exp-scalp add_trade. Returns (None, None) when
    the ladder row is missing — caller leaves trades.prob/diff NULL (no fallback).
    """
    row = _ladder_row_for_ticker(ticker)
    if not row:
        return None, None
    from backend.core.strike_ladder_fetch import probability_from_strike_row_side_aware

    side_key = "yes" if str(side).strip().lower() in ("y", "yes", "bid") else "no"
    prob = probability_from_strike_row_side_aware(row, "15m", side_key)
    if prob is None:
        try:
            raw = row.get("probability")
            prob = float(raw) if raw is not None else None
        except (TypeError, ValueError):
            prob = None
    diff_key = "yes_diff" if side_key == "yes" else "no_diff"
    diff: Optional[float] = None
    try:
        raw_d = row.get(diff_key)
        if raw_d is not None:
            diff = float(raw_d)
    except (TypeError, ValueError):
        diff = None
    return prob, diff


def _book_fill_to_tm(st: DualRestState, *, side: str, fill_qty: float) -> Optional[int]:
    """Hand filled leg to trade_manager (intent=maker_edge_fill)."""
    if st.floor_strike is None:
        st.floor_strike = _resolve_floor_strike(st.ticker)
    if st.floor_strike is None:
        _log(f"TM book skipped monitor={st.monitor_id}: missing floor_strike")
        return None
    port = get_port("trade_manager")
    est = now_est()
    un = _user_no()
    # Stable per monitor/ticker/side so retries are idempotent in TM.
    ticket_id = f"me_{un}_{st.monitor_id}_{st.ticker}_{side}"
    monitor_key = f"mon_{un}_{st.monitor_id}"
    payload = {
        "intent": "maker_edge_fill",
        "ticket_id": ticket_id,
        "symbol": "BTC",
        "market": "15m",
        "exchange": "kalshi",
        "trade_strategy": STRATEGY_NAME,
        # contract label derived in TM from ticker (do not send bare "BTC")
        "strike": float(st.floor_strike),
        "side": side,
        "ticker": st.ticker,
        "buy_price": st.limit_px,
        "position": fill_qty,
        "count_fp": f"{fill_qty:.2f}",
        # Resting size placed (may exceed cumulative fill until fully filled).
        "initial_count": float(st.contracts),
        "monitor": monitor_key,
        "subaccount": int(st.subaccount),
        "paper_trade": bool(st.paper),
        "entry_method": "maker_edge",
        "order_id_open": st.bid_order_id if side == "yes" else st.ask_order_id,
        "time_in_force": "good_till_canceled",
        "order_type": "limit",
        "date": est.strftime("%Y-%m-%d"),
        "time": est.strftime("%H:%M:%S"),
    }
    if st.bankroll_cents is not None:
        payload["bankroll_allotment_total"] = st.bankroll_cents
    # Fill-time ladder snapshot (NULL omitted → DB NULL; no invented values).
    if st.fill_prob is not None:
        payload["prob"] = st.fill_prob
    if st.fill_diff is not None:
        payload["diff"] = st.fill_diff
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


def _prepare_place(
    monitor: Dict[str, Any],
    ticker: str,
    event_ticker: str,
    floor_strike: Optional[float],
) -> Optional[_PreparedPlace]:
    """Build a place plan before open_time (DB / price map / validation only)."""
    limit_px = resolve_monitor_limit_dollars(monitor)
    if limit_px is None or limit_px <= 0 or limit_px >= 1:
        _log(f"skip monitor={monitor.get('monitor_id')}: invalid limit min/max ask")
        return None
    try:
        contracts = int(round(float(monitor.get("total_position") or 0)))
    except (TypeError, ValueError):
        contracts = 0
    if contracts <= 0:
        _log(f"skip monitor={monitor.get('monitor_id')}: total_position<=0")
        return None
    floor: Optional[float]
    try:
        floor = float(floor_strike) if floor_strike is not None else None
    except (TypeError, ValueError):
        floor = None
    subaccount = int(monitor.get("subaccount") or 1)
    paper = effective_paper_trade(
        monitor.get("paper_trade") or monitor.get("test_filter")
    )
    try:
        bankroll_cents = (
            float(monitor["bankroll_allotment_total"])
            if monitor.get("bankroll_allotment_total") is not None
            else None
        )
    except (TypeError, ValueError):
        bankroll_cents = None
    mid = str(monitor["monitor_id"])
    bid_price = ask_price = ""
    bid_body = ask_body = b""
    if not paper:
        try:
            bid_price = v2_price_for_limit_side(side="bid", limit_dollars=limit_px)
            ask_price = v2_price_for_limit_side(side="ask", limit_dollars=limit_px)
        except ValueError as exc:
            _log(f"skip monitor={mid}: price map failed: {exc}")
            return None
        bid_body = encode_place_body(
            build_place_body(
                ticker=ticker,
                side="bid",
                price=bid_price,
                count=contracts,
                subaccount=subaccount,
            )
        )
        ask_body = encode_place_body(
            build_place_body(
                ticker=ticker,
                side="ask",
                price=ask_price,
                count=contracts,
                subaccount=subaccount,
            )
        )
    return _PreparedPlace(
        monitor_id=mid,
        ticker=ticker,
        event_ticker=event_ticker,
        limit_px=limit_px,
        contracts=contracts,
        subaccount=subaccount,
        paper=paper,
        floor_strike=floor,
        bankroll_cents=bankroll_cents,
        min_time=_parse_min_time(monitor.get("min_time")),
        bid_price=bid_price,
        ask_price=ask_price,
        bid_body_bytes=bid_body,
        ask_body_bytes=ask_body,
    )


def _fire_prepared_place(
    plan: _PreparedPlace,
) -> Tuple[Optional[DualRestState], Optional[PlaceResult], Optional[PlaceResult]]:
    """Hot path: send dual rests. Returns (state, bid_result, ask_result)."""
    st = DualRestState(
        monitor_id=plan.monitor_id,
        ticker=plan.ticker,
        event_ticker=plan.event_ticker,
        limit_px=plan.limit_px,
        contracts=plan.contracts,
        subaccount=plan.subaccount,
        paper=plan.paper,
        floor_strike=plan.floor_strike,
        bankroll_cents=plan.bankroll_cents,
        min_time=plan.min_time,
    )
    if plan.paper:
        st.bid_order_id = f"paper_bid_{uuid.uuid4().hex[:12]}"
        st.ask_order_id = f"paper_ask_{uuid.uuid4().hex[:12]}"
        _log(
            f"PAPER dual rest monitor={plan.monitor_id} ticker={plan.ticker} "
            f"BID+ASK @{plan.limit_px:.4f} ct={plan.contracts} sa={plan.subaccount} "
            f"(open_time place)"
        )
        return st, None, None

    fut_bid = _PLACE_POOL.submit(
        place_post_only_gtc,
        ticker=plan.ticker,
        side="bid",
        limit_dollars=plan.limit_px,
        count=plan.contracts,
        subaccount=plan.subaccount,
        prebuilt_price=plan.bid_price,
        prebuilt_body_bytes=plan.bid_body_bytes,
    )
    fut_ask = _PLACE_POOL.submit(
        place_post_only_gtc,
        ticker=plan.ticker,
        side="ask",
        limit_dollars=plan.limit_px,
        count=plan.contracts,
        subaccount=plan.subaccount,
        prebuilt_price=plan.ask_price,
        prebuilt_body_bytes=plan.ask_body_bytes,
    )
    bid_res = fut_bid.result()
    ask_res = fut_ask.result()
    bid_oid = extract_order_id(bid_res.api_json if bid_res else None)
    ask_oid = extract_order_id(ask_res.api_json if ask_res else None)
    if not bid_oid or not ask_oid:
        _log(
            f"place incomplete monitor={plan.monitor_id} bid={bid_oid} ask={ask_oid} "
            f"— canceling orphans"
        )
        if bid_oid:
            _cancel_order_routed(
                bid_oid, ticker=plan.ticker, subaccount=plan.subaccount
            )
        if ask_oid:
            _cancel_order_routed(
                ask_oid, ticker=plan.ticker, subaccount=plan.subaccount
            )
        return None, bid_res, ask_res
    st.bid_order_id = bid_oid
    st.ask_order_id = ask_oid
    _log(
        f"LIVE dual rest monitor={plan.monitor_id} ticker={plan.ticker} "
        f"BID={bid_oid} ASK={ask_oid} @{plan.limit_px:.4f} ct={plan.contracts} "
        f"sa={plan.subaccount} (open_time place)"
    )
    return st, bid_res, ask_res


def _place_dual(
    monitor: Dict[str, Any],
    ticker: str,
    event_ticker: str,
    floor_strike: Optional[float],
) -> Optional[DualRestState]:
    plan = _prepare_place(monitor, ticker, event_ticker, floor_strike)
    if plan is None:
        return None
    st, _, _ = _fire_prepared_place(plan)
    return st


def _cleanup_foreign_cycle_rests(keep_event: str) -> None:
    """Cancel / drop rests for other cycles. Safe after new places are in flight."""
    with _lock:
        foreign = [
            (mid, st)
            for mid, st in list(_active.items())
            if st.event_ticker != keep_event
        ]
    for mid, st in foreign:
        if st.done and not st.paper and not st.fill_sync_done:
            _sync_live_fill_totals(st)
        elif not st.done and not st.paper:
            if st.bid_order_id:
                _cancel_order_routed(
                    st.bid_order_id, ticker=st.ticker, subaccount=st.subaccount
                )
            if st.ask_order_id:
                _cancel_order_routed(
                    st.ask_order_id, ticker=st.ticker, subaccount=st.subaccount
                )
        with _lock:
            cur = _active.get(mid)
            if cur is st or (cur and cur.event_ticker != keep_event):
                _active.pop(mid, None)


def _on_first_fill(st: DualRestState, *, side: str, fill_qty: float) -> None:
    if st.done or fill_qty <= 0:
        return
    st.filled_side = side
    st.fill_qty = float(fill_qty)
    # Cancel sibling first — ladder snapshot / TM book must not delay cancel.
    sibling_oid = st.ask_order_id if side == "yes" else st.bid_order_id
    sibling_ok = True
    if sibling_oid and not st.paper:
        sibling_ok = _cancel_order_routed(
            sibling_oid, ticker=st.ticker, subaccount=st.subaccount
        )
    elif sibling_oid and st.paper:
        _log(f"PAPER cancel sibling {sibling_oid} after {side} fill")
    prob, diff = ladder_prob_diff_at_fill(st.ticker, side)
    st.fill_prob = prob
    st.fill_diff = diff
    if prob is None and diff is None:
        _log(
            f"fill ladder snapshot missing ticker={st.ticker} side={side} "
            f"monitor={st.monitor_id} — booking with NULL prob/diff"
        )
    tid = _book_fill_to_tm(st, side=side, fill_qty=float(fill_qty))
    st.trade_id = tid
    # Always mark done for this cycle so we do not re-arm dual rests while ask<=L.
    st.done = True
    _completed_events.add(st.event_ticker)
    # Paper books full size once; live keeps syncing venue cumulative fills to TM.
    st.fill_sync_done = bool(st.paper)
    sib_msg = "sibling canceled" if sibling_ok else "SIBLING CANCEL FAILED"
    _log(
        f"first fill side={side} qty={fill_qty} monitor={st.monitor_id} "
        f"trade_id={tid} {sib_msg} sibling_oid={sibling_oid} "
        f"prob={prob} diff={diff}"
    )


def _retry_book_if_needed(st: DualRestState) -> None:
    if not st.done or st.trade_id is not None:
        return
    if not st.filled_side or st.fill_qty is None or st.fill_qty <= 0:
        return
    tid = _book_fill_to_tm(st, side=st.filled_side, fill_qty=float(st.fill_qty))
    if tid is not None:
        st.trade_id = tid
        _log(f"TM book retry ok monitor={st.monitor_id} trade_id={tid}")


def _sync_live_fill_totals(st: DualRestState) -> None:
    """Push cumulative venue fill_count for the filled leg into TM trade.position."""
    if st.paper or st.fill_sync_done or not st.filled_side:
        return
    oid = st.bid_order_id if st.filled_side == "yes" else st.ask_order_id
    qty = _order_fill_qty(oid)
    if qty <= 0:
        return
    prev = float(st.fill_qty or 0.0)
    if qty > prev + 1e-9 or st.trade_id is None:
        st.fill_qty = float(qty)
        tid = _book_fill_to_tm(st, side=st.filled_side, fill_qty=float(qty))
        if tid is not None:
            st.trade_id = tid
            if qty > prev + 1e-9:
                _log(
                    f"fill total sync monitor={st.monitor_id} side={st.filled_side} "
                    f"qty {prev} → {qty} trade_id={tid}"
                )
    rem = _order_remaining_qty(oid)
    if rem is not None and rem <= 1e-9 and qty > 0:
        st.fill_sync_done = True
        _log(
            f"fill sync complete monitor={st.monitor_id} side={st.filled_side} "
            f"qty={qty} remaining=0"
        )


def _check_fills(st: DualRestState, *, ttc: Optional[int] = None) -> None:
    if st.done:
        _retry_book_if_needed(st)
        _sync_live_fill_totals(st)
        return
    if st.paper:
        yes_ask = _ladder_side_ask(st.ticker, "yes")
        no_ask = _ladder_side_ask(st.ticker, "no")
        # Fill when ask on that side drops to <= limit (market reached our rest).
        if yes_ask is not None and yes_ask <= st.limit_px + 1e-9:
            _on_first_fill(st, side="yes", fill_qty=float(st.contracts))
            return
        if no_ask is not None and no_ask <= st.limit_px + 1e-9:
            _on_first_fill(st, side="no", fill_qty=float(st.contracts))
            return
    else:
        bid_fill = _order_fill_qty(st.bid_order_id)
        ask_fill = _order_fill_qty(st.ask_order_id)
        if bid_fill > 0 and ask_fill > 0:
            # Ambiguous simultaneous — prefer larger fill; do not invent.
            if bid_fill >= ask_fill:
                _on_first_fill(st, side="yes", fill_qty=bid_fill)
            else:
                _on_first_fill(st, side="no", fill_qty=ask_fill)
            return
        if bid_fill > 0:
            _on_first_fill(st, side="yes", fill_qty=bid_fill)
            return
        if ask_fill > 0:
            _on_first_fill(st, side="no", fill_qty=ask_fill)
            return

    # After fill probe: min_time > 0 → cancel both rests once TTC reaches floor.
    if should_cancel_unfilled_at_min_ttc(min_time=st.min_time, ttc=ttc):
        _cancel_unfilled_rests(st, reason=f"min_ttc ttc={ttc}")


def _place_at_open(target: OpenTarget) -> None:
    """Runs on arm thread: prefetch, wait for open_ts, fire dual rests, then cleanup."""
    global _armed_event, _armed_target, _last_event_ticker
    et = target.event_ticker
    _log(
        f"armed open_time place event={et} ticker={target.market_ticker} "
        f"open_ts={target.open_ts:.6f} in={target.open_ts - time.time():.3f}s"
    )

    # --- Prefetch (before open): all work we control that is not the send ---
    floor = _resolve_floor_strike(target.market_ticker, target.floor_strike)
    monitors = [m for m in list_active_maker_edge_monitor_rows() if m.get("auto_trade")]
    plans: list[_PreparedPlace] = []
    for mon in monitors:
        plan = _prepare_place(mon, target.market_ticker, et, floor)
        if plan is not None:
            plans.append(plan)
    # Cap to concurrency before open so hot path does not decide under the gun.
    if len(plans) > MAX_CONCURRENT_MARKETS:
        plans = plans[:MAX_CONCURRENT_MARKETS]
    warm_kalshi_http()
    # Sleep until ~1s before open, then re-warm so TLS is fresh after a long arm.
    while True:
        rem = target.open_ts - time.time()
        if rem <= _REWARM_BEFORE_OPEN_SEC:
            break
        time.sleep(min(rem - _REWARM_BEFORE_OPEN_SEC, 0.5))
    warm_kalshi_http()

    ok = wait_until_open_ts(target.open_ts)
    if not ok:
        _log(
            f"MISSED open_time event={et} ticker={target.market_ticker} "
            f"grace={LATE_PLACE_GRACE_SEC}s — skip late place"
        )
        with _lock:
            if _armed_event == et:
                _armed_event = None
                _armed_target = None
            _placed_events.add(et)
        return

    # --- Hot path: fire only (no DB, no foreign cancel, no lock around HTTP) ---
    t_fire = time.time()
    fire_lag_ms = (t_fire - target.open_ts) * 1000.0
    fired: list[
        Tuple[_PreparedPlace, Optional[DualRestState], Optional[PlaceResult], Optional[PlaceResult]]
    ] = []
    t_send_first: Optional[float] = None
    t_ack_last: Optional[float] = None
    for plan in plans:
        st, bid_res, ask_res = _fire_prepared_place(plan)
        fired.append((plan, st, bid_res, ask_res))
        for res in (bid_res, ask_res):
            if res is None:
                continue
            if t_send_first is None or res.t_send < t_send_first:
                t_send_first = res.t_send
            if t_ack_last is None or res.t_ack > t_ack_last:
                t_ack_last = res.t_ack

    with _lock:
        for plan, st, _, _ in fired:
            if st is not None:
                _active[plan.monitor_id] = st
        _placed_events.add(et)
        if _armed_event == et:
            _armed_event = None
            _armed_target = None
        _last_event_ticker = et

    # Foreign-cycle cleanup after new rests are on the wire / booked.
    try:
        _cleanup_foreign_cycle_rests(et)
    except Exception as exc:
        _log(f"foreign cleanup failed event={et}: {exc}")

    def _ms(v: Optional[float], nd: int = 2) -> str:
        return f"{v:.{nd}f}" if v is not None else "n/a"

    send_lag_ms = (
        (t_send_first - target.open_ts) * 1000.0 if t_send_first is not None else None
    )
    ack_lag_ms = (
        (t_ack_last - target.open_ts) * 1000.0 if t_ack_last is not None else None
    )
    prep_after_fire_ms = (
        (t_send_first - t_fire) * 1000.0 if t_send_first is not None else None
    )
    bid_rtt = ask_rtt = None
    for _, _, bid_res, ask_res in fired:
        if bid_res is not None:
            bid_rtt = bid_res.rtt_ms
        if ask_res is not None:
            ask_rtt = ask_res.rtt_ms
    placed_n = sum(1 for _, st, _, _ in fired if st is not None)
    # lag_ms kept for existing log parsers (= fire_lag; send is send_lag_ms).
    _log(
        f"open_time place done event={et} ticker={target.market_ticker} "
        f"lag_ms={fire_lag_ms:.2f} fire_lag_ms={fire_lag_ms:.2f} "
        f"send_lag_ms={_ms(send_lag_ms)} ack_lag_ms={_ms(ack_lag_ms)} "
        f"prep_after_fire_ms={_ms(prep_after_fire_ms)} "
        f"bid_rtt_ms={_ms(bid_rtt, 1)} ask_rtt_ms={_ms(ask_rtt, 1)} "
        f"floor={floor} plans={len(plans)} placed={placed_n}"
    )


def _place_for_target_now(target: OpenTarget, *, reason: str) -> None:
    """Immediate dual-rest place (no open_time wait). Used for live-cycle recovery."""
    global _last_event_ticker
    et = target.event_ticker
    with _lock:
        if et in _completed_events:
            return
        if any(s.event_ticker == et and not s.done for s in _active.values()):
            return
    floor = _resolve_floor_strike(target.market_ticker, target.floor_strike)
    monitors = [m for m in list_active_maker_edge_monitor_rows() if m.get("auto_trade")]
    plans: list[_PreparedPlace] = []
    for mon in monitors:
        mid = str(mon["monitor_id"])
        with _lock:
            if mid in _active and not _active[mid].done:
                continue
        plan = _prepare_place(mon, target.market_ticker, et, floor)
        if plan is not None:
            plans.append(plan)
        if len(plans) >= MAX_CONCURRENT_MARKETS:
            break
    warm_kalshi_http()
    placed = 0
    for plan in plans:
        st, _, _ = _fire_prepared_place(plan)
        if st is not None:
            with _lock:
                _active[plan.monitor_id] = st
            placed += 1
    with _lock:
        _placed_events.add(et)
        _last_event_ticker = et
    if placed:
        _log(
            f"{reason} place event={et} ticker={target.market_ticker} "
            f"n={placed} floor={floor}"
        )


def _ensure_armed_for_next_open() -> None:
    """Recovery-place live cycle if needed; arm waiter for the next open_time."""
    global _armed_event, _armed_target, _arm_thread, _last_discover_mono
    now_m = time.monotonic()
    with _lock:
        arm_alive = _arm_thread is not None and _arm_thread.is_alive()
        has_live_rest = any(not s.done for s in _active.values())
    # Live-cycle recovery: if we have no rests for the open market, place now.
    # (Does not wait for open_time — that market is already open.)
    # Skip if this process already attempted place for the event (_placed_events),
    # including failed attempts — avoids hammering Kalshi on persistent 4xx.
    # Fresh process restart clears _placed_events so mid-cycle recovery still works.
    if not has_live_rest:
        live = fetch_live_market()
        if live is not None and live.event_ticker not in _completed_events:
            with _lock:
                already_attempted = live.event_ticker in _placed_events
                already = any(
                    s.event_ticker == live.event_ticker and not s.done
                    for s in _active.values()
                )
            if not already_attempted and not already:
                _place_for_target_now(live, reason="live_recovery")

    with _lock:
        if arm_alive or (_arm_thread is not None and _arm_thread.is_alive()):
            return
        if now_m - _last_discover_mono < OPEN_DISCOVER_POLL_SEC and _armed_event:
            return
    _last_discover_mono = now_m
    target = fetch_next_open_target()
    if target is None:
        return
    with _lock:
        if target.event_ticker in _placed_events or target.event_ticker in _completed_events:
            return
        if any(s.event_ticker == target.event_ticker for s in _active.values()):
            _placed_events.add(target.event_ticker)
            return
        # If target is already live (open grace), place immediately rather than wait.
        now = time.time()
        if target.open_ts <= now:
            pass  # fall through to thread which wait_until will pass immediately
        _armed_event = target.event_ticker
        _armed_target = target
        th = threading.Thread(
            target=_place_at_open,
            args=(target,),
            name=f"me_open_{target.event_ticker}",
            daemon=True,
        )
        _arm_thread = th
        th.start()


def _tick() -> None:
    all_me = list_active_maker_edge_monitor_rows()
    _sync_monitor_statuses(all_me)
    _ensure_armed_for_next_open()
    ttc = _current_ttc_seconds()

    with _lock:
        for st in list(_active.values()):
            _check_fills(st, ttc=ttc)
        # Bound placed_events memory
        if len(_placed_events) > 64:
            # Keep most recent-ish by clearing when oversized; arming uses live API.
            _placed_events.clear()


def _loop() -> None:
    _log("main loop started")
    while True:
        try:
            _tick()
        except Exception as exc:
            _log(f"tick error: {exc}")
        _wake.wait(timeout=FAILSAFE_POLL_SEC)
        _wake.clear()


def _start_listeners() -> None:
    try:
        from backend.core.tradeflow_live_state_trigger import (
            start_tradeflow_live_state_listener,
        )

        def _on_ladder(symbol: str, market: str) -> None:
            if str(symbol).upper() == "BTC" and str(market).lower() == "15m":
                _wake.set()

        start_tradeflow_live_state_listener(
            on_ladder_update=_on_ladder,
            service="maker_edge_agent",
            symbol_market_filter=lambda s, m: str(s).upper() == "BTC"
            and str(m).lower() == "15m",
        )
    except Exception as exc:
        _log(f"live_state listener not started: {exc}")

    try:
        from backend.core.trading_redis_comms import (
            channel_tm_positions_updated,
            redis_client_optional,
        )

        def _positions_worker() -> None:
            r = redis_client_optional()
            if not r:
                return
            pubsub = r.pubsub()
            pubsub.subscribe(channel_tm_positions_updated())
            _log(f"subscribed {channel_tm_positions_updated()}")
            while True:
                try:
                    msg = pubsub.get_message(
                        ignore_subscribe_messages=True, timeout=1.0
                    )
                    if msg and msg.get("type") == "message":
                        _wake.set()
                except Exception:
                    time.sleep(0.5)

        threading.Thread(
            target=_positions_worker, name="me_positions_wake", daemon=True
        ).start()
    except Exception as exc:
        _log(f"positions_updated listener not started: {exc}")


def main() -> None:
    un = _user_no()
    _start_listeners()
    threading.Thread(target=_loop, name="me_main", daemon=True).start()
    try:
        port = get_port(f"maker_edge_agent_{un}")
    except Exception:
        port = 8050 if un == "0001" else 8051
    _log(f"health on port {port}")
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


if __name__ == "__main__":
    main()
