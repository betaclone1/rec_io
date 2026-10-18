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
    cancel_order,
    extract_order_id,
    place_post_only_gtc,
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
    done: bool = False


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


def _cancel_unfilled_rests(st: DualRestState, *, reason: str) -> None:
    """Cancel both resting legs; mark cycle done with no fill (no TM book)."""
    if st.done:
        return
    if not st.paper:
        if st.bid_order_id:
            cancel_order(st.bid_order_id, subaccount=st.subaccount)
        if st.ask_order_id:
            cancel_order(st.ask_order_id, subaccount=st.subaccount)
    st.done = True
    _completed_events.add(st.event_ticker)
    _log(
        f"cancel unfilled monitor={st.monitor_id} ticker={st.ticker} "
        f"reason={reason} min_time={st.min_time}"
    )


def _order_fill_qty(order_id: Optional[str]) -> float:
    if not order_id:
        return 0.0
    try:
        from backend.core.live_state_kalshi_portfolio import get_order

        rec = get_order(_user_no(), order_id)
        if not rec:
            return 0.0
        return float(rec.get("fill_count_fp") or 0)
    except Exception:
        return 0.0


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


def _place_dual(
    monitor: Dict[str, Any],
    ticker: str,
    event_ticker: str,
    floor_strike: Optional[float],
) -> Optional[DualRestState]:
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
    st = DualRestState(
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
    )
    if paper:
        st.bid_order_id = f"paper_bid_{uuid.uuid4().hex[:12]}"
        st.ask_order_id = f"paper_ask_{uuid.uuid4().hex[:12]}"
        _log(
            f"PAPER dual rest monitor={mid} ticker={ticker} "
            f"BID+ASK @{limit_px:.4f} ct={contracts} sa={subaccount} "
            f"(open_time place)"
        )
        return st

    # Parallel place — open_time path must not serialize BID then ASK.
    with ThreadPoolExecutor(max_workers=2) as pool:
        fut_bid = pool.submit(
            place_post_only_gtc,
            ticker=ticker,
            side="bid",
            limit_dollars=limit_px,
            count=contracts,
            subaccount=subaccount,
        )
        fut_ask = pool.submit(
            place_post_only_gtc,
            ticker=ticker,
            side="ask",
            limit_dollars=limit_px,
            count=contracts,
            subaccount=subaccount,
        )
        bid_resp = fut_bid.result()
        ask_resp = fut_ask.result()
    bid_oid = extract_order_id(bid_resp)
    ask_oid = extract_order_id(ask_resp)
    if not bid_oid or not ask_oid:
        _log(
            f"place incomplete monitor={mid} bid={bid_oid} ask={ask_oid} — canceling orphans"
        )
        if bid_oid:
            cancel_order(bid_oid, subaccount=subaccount)
        if ask_oid:
            cancel_order(ask_oid, subaccount=subaccount)
        return None
    st.bid_order_id = bid_oid
    st.ask_order_id = ask_oid
    _log(
        f"LIVE dual rest monitor={mid} ticker={ticker} "
        f"BID={bid_oid} ASK={ask_oid} @{limit_px:.4f} ct={contracts} sa={subaccount} "
        f"(open_time place)"
    )
    return st


def _on_first_fill(st: DualRestState, *, side: str, fill_qty: float) -> None:
    if st.done or fill_qty <= 0:
        return
    st.filled_side = side
    st.fill_qty = float(fill_qty)
    # Cancel sibling first — ladder snapshot / TM book must not delay cancel.
    sibling_oid = st.ask_order_id if side == "yes" else st.bid_order_id
    if sibling_oid and not st.paper:
        cancel_order(sibling_oid, subaccount=st.subaccount)
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
    _log(
        f"first fill side={side} qty={fill_qty} monitor={st.monitor_id} "
        f"trade_id={tid} sibling canceled prob={prob} diff={diff}"
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


def _check_fills(st: DualRestState, *, ttc: Optional[int] = None) -> None:
    if st.done:
        _retry_book_if_needed(st)
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
    """Runs on arm thread: wait for open_ts, then place dual rests immediately."""
    global _armed_event, _armed_target, _last_event_ticker
    et = target.event_ticker
    _log(
        f"armed open_time place event={et} ticker={target.market_ticker} "
        f"open_ts={target.open_ts:.6f} in={target.open_ts - time.time():.3f}s"
    )
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

    place_wall = time.time()
    lag_ms = (place_wall - target.open_ts) * 1000.0
    floor = _resolve_floor_strike(target.market_ticker, target.floor_strike)
    monitors = [m for m in list_active_maker_edge_monitor_rows() if m.get("auto_trade")]
    with _lock:
        # Drop foreign-cycle rests
        for mid, st in list(_active.items()):
            if st.event_ticker != et:
                if not st.done and not st.paper:
                    if st.bid_order_id:
                        cancel_order(st.bid_order_id, subaccount=st.subaccount)
                    if st.ask_order_id:
                        cancel_order(st.ask_order_id, subaccount=st.subaccount)
                _active.pop(mid, None)
        active_count = sum(1 for s in _active.values() if not s.done)
        for mon in monitors:
            mid = str(mon["monitor_id"])
            if mid in _active:
                continue
            if active_count >= MAX_CONCURRENT_MARKETS:
                break
            st = _place_dual(mon, target.market_ticker, et, floor)
            if st:
                _active[mid] = st
                active_count += 1
        _placed_events.add(et)
        if _armed_event == et:
            _armed_event = None
            _armed_target = None
        _last_event_ticker = et
    _log(
        f"open_time place done event={et} ticker={target.market_ticker} "
        f"lag_ms={lag_ms:.2f} floor={floor}"
    )


def _place_for_target_now(target: OpenTarget, *, reason: str) -> None:
    """Immediate dual-rest place (no open_time wait). Used for live-cycle recovery."""
    global _last_event_ticker
    et = target.event_ticker
    floor = _resolve_floor_strike(target.market_ticker, target.floor_strike)
    monitors = [m for m in list_active_maker_edge_monitor_rows() if m.get("auto_trade")]
    with _lock:
        if et in _completed_events:
            return
        if any(s.event_ticker == et and not s.done for s in _active.values()):
            return
        active_count = sum(1 for s in _active.values() if not s.done)
        placed = 0
        for mon in monitors:
            mid = str(mon["monitor_id"])
            if mid in _active and not _active[mid].done:
                continue
            if active_count >= MAX_CONCURRENT_MARKETS:
                break
            st = _place_dual(mon, target.market_ticker, et, floor)
            if st:
                _active[mid] = st
                active_count += 1
                placed += 1
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
    if not has_live_rest:
        live = fetch_live_market()
        if live is not None and live.event_ticker not in _completed_events:
            with _lock:
                already = any(
                    s.event_ticker == live.event_ticker and not s.done
                    for s in _active.values()
                )
            if not already:
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
