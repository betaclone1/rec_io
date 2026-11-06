"""
Upper Tail agent — one GTC limit when the target rail is reached.

Outside trade_executor. During the monitor time window:
  - crypto (``full``) — active ``upper_tail_rail_trigger`` from OB publish
    (watchdog emits on rising-edge rail cross; this agent only places)
  - commodity / lean ``market`` — public trades tape print ≥ target (timer loop)
Places a single GTC at the target on that side (``post_only`` off). Venue fill
confirmation books into trade_manager. Paper monitors book when the trigger
qualifies (no venue order).

Housekeeping (monitors, markets, fills, arm registry) is a slow timer loop.
Crypto does **not** re-qualify Redis touch on that timer — no backup place path.
Crypto does not subscribe to every orderbook delta.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import requests
import uvicorn
from fastapi import FastAPI

from backend.core.aes_btc15m_lower_tail_cutout import resolve_monitor_limit_dollars
from backend.core.kalshi_event_market_fetch import fetch_market_payload
from backend.core.lower_tail_kalshi import (
    build_place_body,
    cancel_order,
    encode_place_body,
    extract_order_id,
    place_limit_gtc,
    v2_price_for_limit_side,
    warm_kalshi_http,
)
from backend.core.lower_tail_open import (
    fetch_series_15m_markets,
    select_live_targets_by_symbol,
)
from backend.core.kalshi_public_trade_redis import load_public_trade_prints
from backend.core.orderbook_strike_prices import resolve_orderbook_touch_with_meta
from backend.core.port_config import default_pool_user_number, get_port
from backend.core.upper_tail import (
    STRATEGY_NAME,
    TRIGGER_ORDERBOOK,
    TRIGGER_TAPE,
    floor_strike_from_market,
    list_active_upper_tail_monitor_rows,
    upper_tail_series_tickers,
    upper_tail_side_from_orderbook,
    upper_tail_side_from_print,
    upper_tail_trigger_mode,
    ttc_in_entry_window,
)
from backend.core.upper_tail_orderbook_watch import set_upper_tail_orderbook_arm
from backend.core.time_eastern import now_est
from backend.trading_mode import effective_paper_trade

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] upper_tail_agent: %(message)s",
)
log = logging.getLogger("upper_tail_agent")

POLL_SEC = float(os.getenv("UPPER_TAIL_POLL_SEC", "1.0"))
LIVE_MARKETS_CACHE_SEC = float(os.getenv("UPPER_TAIL_LIVE_MARKETS_CACHE_SEC", "15"))
PLACE_FAIL_COOLDOWN_SEC = float(os.getenv("UPPER_TAIL_PLACE_FAIL_COOLDOWN_SEC", "2.0"))

app = FastAPI(title="Upper Tail Agent")
_lock = threading.Lock()
_arm_lock = threading.Lock()
_started_at = time.time()
_prev_auto_trade_status: Dict[str, str] = {}
# ticker → monitor_ids armed for crypto rail fire (timer rebuilds).
_armed_by_ticker: Dict[str, List[str]] = {}
_last_http_warm_mono = 0.0
_HTTP_WARM_SEC = float(os.getenv("UPPER_TAIL_HTTP_WARM_SEC", "30"))
_live_markets_cache: list = []
_live_markets_cache_mono = 0.0


def _user_no() -> str:
    return default_pool_user_number()


def _log(msg: str) -> None:
    log.info("[%s] %s", _user_no(), msg)


@dataclass
class _PreparedBodies:
    """Prebuilt Kalshi bodies for both sides (side chosen at fire)."""

    bid_price: str
    ask_price: str
    bid_body: bytes
    ask_body: bytes


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
    placing: bool = False
    done: bool = False
    trade_id: Optional[int] = None
    fill_sync_done: bool = False
    floor_fetch_mono: float = 0.0
    floor_miss_logged: bool = False
    trigger_mode: Optional[str] = None
    prepared: Optional[_PreparedBodies] = None
    place_cooldown_until: float = 0.0
    fire_lock: threading.Lock = field(default_factory=threading.Lock)


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


@dataclass(frozen=True)
class _TriggerHit:
    """First local observation that the rail qualifies (not venue first-touch)."""

    side: str
    mode: str
    t_detect: float
    source_age_ms: Optional[float] = None
    source_ts_ms: Optional[float] = None
    detail: str = ""


def _ms(v: Optional[float], nd: int = 1) -> str:
    if v is None:
        return "na"
    return f"{float(v):.{nd}f}"


def _event_ts_to_unix_ms(raw: Any) -> Optional[float]:
    """Parse tape ``ts`` / ``received_at`` into unix milliseconds."""
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        v = float(raw)
        if v <= 0:
            return None
        # Heuristic: seconds vs milliseconds.
        return v * 1000.0 if v < 1e12 else v
    s = str(raw).strip()
    if not s:
        return None
    try:
        v = float(s)
        if v <= 0:
            return None
        return v * 1000.0 if v < 1e12 else v
    except (TypeError, ValueError):
        pass
    try:
        from datetime import datetime, timezone

        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp() * 1000.0
    except (TypeError, ValueError):
        return None


def _log_trigger(
    cy: _Cycle, hit: _TriggerHit, *, ttc: float, path: str = "slow"
) -> None:
    _log(
        f"TRIGGER monitor={cy.monitor_id} mode={hit.mode} side={hit.side} "
        f"ticker={cy.ticker} path={path} source_age_ms={_ms(hit.source_age_ms)} "
        f"source_ts_ms={_ms(hit.source_ts_ms, 0)} ttc={ttc:.1f}"
        + (f" {hit.detail}" if hit.detail else "")
    )


def _prepare_place_bodies(cy: _Cycle) -> Optional[_PreparedBodies]:
    """Encode bid+ask GTC bodies for hot-path place (fresh client_order_ids)."""
    try:
        bid_price = v2_price_for_limit_side(side="bid", limit_dollars=cy.limit_px)
        ask_price = v2_price_for_limit_side(side="ask", limit_dollars=cy.limit_px)
    except ValueError as exc:
        _log(f"prepare skip monitor={cy.monitor_id}: {exc}")
        return None
    bid_body = encode_place_body(
        build_place_body(
            ticker=cy.ticker,
            side="bid",
            price=bid_price,
            count=cy.contracts,
            subaccount=cy.subaccount,
            post_only=False,
            self_trade_prevention_type="taker_at_cross",
        )
    )
    ask_body = encode_place_body(
        build_place_body(
            ticker=cy.ticker,
            side="ask",
            price=ask_price,
            count=cy.contracts,
            subaccount=cy.subaccount,
            post_only=False,
            self_trade_prevention_type="taker_at_cross",
        )
    )
    return _PreparedBodies(
        bid_price=bid_price,
        ask_price=ask_price,
        bid_body=bid_body,
        ask_body=ask_body,
    )


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


def _place_live(cy: _Cycle, hit: _TriggerHit, *, path: str = "slow") -> bool:
    side = hit.side
    book_side = "bid" if side == "yes" else "ask"
    prep = cy.prepared
    prebuilt_price = None
    prebuilt_body = None
    if prep is not None:
        if side == "yes":
            prebuilt_price, prebuilt_body = prep.bid_price, prep.bid_body
        else:
            prebuilt_price, prebuilt_body = prep.ask_price, prep.ask_body
    else:
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
        prebuilt_price=prebuilt_price,
        prebuilt_body_bytes=prebuilt_body,
    )
    oid = extract_order_id(res.api_json if res else None)
    if not oid:
        detect_to_fail_ms = (
            (time.time() - hit.t_detect) * 1000.0 if hit.t_detect else None
        )
        cy.place_cooldown_until = time.time() + PLACE_FAIL_COOLDOWN_SEC
        cy.prepared = _prepare_place_bodies(cy)
        _log(
            f"place failed monitor={cy.monitor_id} side={side} ticker={cy.ticker} "
            f"mode={hit.mode} path={path} detect_to_fail_ms={_ms(detect_to_fail_ms)} "
            f"source_age_ms={_ms(hit.source_age_ms)}"
        )
        return False
    cy.side = side
    cy.order_id = oid
    cy.placed = True
    body = res.api_json if isinstance(res.api_json, dict) else {}
    try:
        fill_on_ack = float(body.get("fill_count") or 0)
    except (TypeError, ValueError):
        fill_on_ack = 0.0
    try:
        kalshi_ts_ms = (
            float(body["ts_ms"]) if body.get("ts_ms") is not None else None
        )
    except (TypeError, ValueError):
        kalshi_ts_ms = None
    detect_to_send_ms = (res.t_send - hit.t_detect) * 1000.0
    detect_to_ack_ms = (res.t_ack - hit.t_detect) * 1000.0
    _log(
        f"GTC monitor={cy.monitor_id} ticker={cy.ticker} side={side} "
        f"oid={oid} @{cy.limit_px:.4f} ct={cy.contracts} sa={cy.subaccount} "
        f"mode={hit.mode} path={path} source_age_ms={_ms(hit.source_age_ms)} "
        f"detect_to_send_ms={_ms(detect_to_send_ms)} "
        f"stream_to_send_ms={_ms(detect_to_send_ms)} "
        f"rtt_ms={_ms(res.rtt_ms)} detect_to_ack_ms={_ms(detect_to_ack_ms)} "
        f"fill_on_ack={fill_on_ack:.2f} kalshi_ts_ms={_ms(kalshi_ts_ms, 0)}"
    )
    return True


def _fire_paper(cy: _Cycle, hit: _TriggerHit, *, path: str, ttc: float) -> None:
    _log_trigger(cy, hit, ttc=ttc, path=path)
    cy.side = hit.side
    cy.order_id = f"paper_{hit.side}_{cy.monitor_id}"
    _on_fill(cy, side=hit.side, qty=float(cy.contracts))
    if cy.done:
        cy.placed = True
        cy.fill_sync_done = True


def _try_fire_cycle(
    cy: _Cycle,
    hit: _TriggerHit,
    *,
    path: str,
    ttc: float,
) -> bool:
    """Once-only fire under per-cycle lock. Returns True if this call owns the fire."""
    with cy.fire_lock:
        if cy.placed or cy.placing or cy.done:
            return False
        now = time.time()
        if now < cy.place_cooldown_until:
            return False
        if not ttc_in_entry_window(
            ttc=ttc, min_time=cy.min_time, max_time=cy.max_time
        ):
            return False
        cy.placing = True
    try:
        if cy.paper:
            _fire_paper(cy, hit, path=path, ttc=ttc)
            return True
        _log_trigger(cy, hit, ttc=ttc, path=path)
        ok = _place_live(cy, hit, path=path)
        return ok
    finally:
        with cy.fire_lock:
            cy.placing = False


def _hit_from_touch(
    cy: _Cycle,
    touch: Dict[str, str],
    *,
    t_detect: float,
    source_age_ms: Optional[float],
    source_ts_ms: Optional[float],
) -> Optional[_TriggerHit]:
    side = upper_tail_side_from_orderbook(
        yes_ask=_parse_px(touch.get("yes_ask_dollars")),
        no_ask=_parse_px(touch.get("no_ask_dollars")),
        yes_bid=_parse_px(touch.get("yes_bid_dollars")),
        no_bid=_parse_px(touch.get("no_bid_dollars")),
        limit_px=cy.limit_px,
    )
    if not side:
        return None
    return _TriggerHit(
        side=side,
        mode=TRIGGER_ORDERBOOK,
        t_detect=t_detect,
        source_age_ms=source_age_ms,
        source_ts_ms=source_ts_ms,
        detail=(
            f"yb={touch.get('yes_bid_dollars')} ya={touch.get('yes_ask_dollars')} "
            f"nb={touch.get('no_bid_dollars')} na={touch.get('no_ask_dollars')}"
        ),
    )


def _on_rail_trigger(payload: Dict[str, Any]) -> None:
    """Active trigger from OB publish: place once for armed monitors on this ticker."""
    t0 = time.time()
    mt = str(payload.get("market_ticker") or "").strip()
    if not mt:
        return
    with _arm_lock:
        mids = list(_armed_by_ticker.get(mt) or ())
    if not mids:
        return
    touch = payload.get("touch")
    if not isinstance(touch, dict) or not touch:
        return
    venue_ms = payload.get("venue_ts_ms")
    ts_ms = payload.get("ts_ms")
    emitted_ms = payload.get("emitted_ms")
    src_ms = None
    for candidate in (venue_ms, ts_ms):
        if candidate is not None:
            try:
                src_ms = float(candidate)
                break
            except (TypeError, ValueError):
                continue
    age_ms = None
    if src_ms is not None and emitted_ms is not None:
        try:
            age_ms = max(0.0, float(emitted_ms) - src_ms)
        except (TypeError, ValueError):
            age_ms = None
    elif src_ms is not None:
        age_ms = max(0.0, t0 * 1000.0 - src_ms)

    for mid in mids:
        cy = _cycles.get(mid)
        if cy is None or cy.ticker != mt:
            continue
        if cy.placed or cy.done or cy.placing:
            continue
        hit = _hit_from_touch(
            cy,
            touch,
            t_detect=t0,
            source_age_ms=age_ms,
            source_ts_ms=src_ms,
        )
        if not hit:
            continue
        ttc = cy.close_ts - t0
        _try_fire_cycle(cy, hit, path="rail", ttc=ttc)


def _rebuild_armed_index(now: float) -> None:
    """Timer-only: index crypto cycles for rail-trigger arm registry."""
    by_ticker: Dict[str, List[str]] = {}
    arms: Dict[str, float] = {}
    for mid, cy in list(_cycles.items()):
        if cy.placed or cy.done or cy.placing:
            continue
        mode = cy.trigger_mode or upper_tail_trigger_mode(cy.symbol)
        cy.trigger_mode = mode
        if mode != TRIGGER_ORDERBOOK:
            continue
        ttc = cy.close_ts - now
        if not ttc_in_entry_window(
            ttc=ttc, min_time=cy.min_time, max_time=cy.max_time
        ):
            continue
        if cy.prepared is None and not cy.paper:
            cy.prepared = _prepare_place_bodies(cy)
        by_ticker.setdefault(cy.ticker, []).append(mid)
        prev = arms.get(cy.ticker)
        if prev is None or float(cy.limit_px) < prev:
            arms[cy.ticker] = float(cy.limit_px)
    with _arm_lock:
        global _armed_by_ticker
        _armed_by_ticker = by_ticker
    set_upper_tail_orderbook_arm(arms)


def _qualifying_side_from_tape(cy: _Cycle) -> Optional[_TriggerHit]:
    """Newest-first public prints until one side hits the rail."""
    for rec in load_public_trade_prints(cy.ticker):
        side = upper_tail_side_from_print(
            yes_price=_parse_px(rec.get("yes_price_dollars")),
            no_price=_parse_px(rec.get("no_price_dollars")),
            limit_px=cy.limit_px,
        )
        if not side:
            continue
        t_detect = time.time()
        src_ms = _event_ts_to_unix_ms(rec.get("ts"))
        if src_ms is None:
            src_ms = _event_ts_to_unix_ms(rec.get("received_at"))
        age_ms = (t_detect * 1000.0 - src_ms) if src_ms is not None else None
        if age_ms is not None and age_ms < 0:
            age_ms = 0.0
        yp = rec.get("yes_price_dollars")
        np_ = rec.get("no_price_dollars")
        return _TriggerHit(
            side=side,
            mode=TRIGGER_TAPE,
            t_detect=t_detect,
            source_age_ms=age_ms,
            source_ts_ms=src_ms,
            detail=f"print_yes={yp} print_no={np_}",
        )
    return None


def _qualifying_side_from_orderbook(cy: _Cycle) -> Optional[_TriggerHit]:
    touch, reason, meta = resolve_orderbook_touch_with_meta(cy.ticker)
    if not touch or reason != "ok":
        return None
    side = upper_tail_side_from_orderbook(
        yes_ask=_parse_px(touch.get("yes_ask_dollars")),
        no_ask=_parse_px(touch.get("no_ask_dollars")),
        yes_bid=_parse_px(touch.get("yes_bid_dollars")),
        no_bid=_parse_px(touch.get("no_bid_dollars")),
        limit_px=cy.limit_px,
    )
    if not side:
        return None
    t_detect = time.time()
    src_ms = None
    for candidate in (meta.venue_ts_ms, meta.ts_ms, meta.redis_written_ms):
        if candidate is not None:
            src_ms = float(candidate)
            break
    age_ms = None
    if src_ms is not None:
        age_ms = max(0.0, t_detect * 1000.0 - src_ms)
    return _TriggerHit(
        side=side,
        mode=TRIGGER_ORDERBOOK,
        t_detect=t_detect,
        source_age_ms=age_ms,
        source_ts_ms=src_ms,
        detail=(
            f"yb={touch.get('yes_bid_dollars')} ya={touch.get('yes_ask_dollars')} "
            f"nb={touch.get('no_bid_dollars')} na={touch.get('no_ask_dollars')}"
        ),
    )


def _qualifying_side_tape_only(cy: _Cycle, *, now: float) -> Optional[_TriggerHit]:
    """Timer-loop tape qualify (commodity/lean). Crypto OB fires on the stream."""
    now_ttc = cy.close_ts - now
    if not ttc_in_entry_window(ttc=now_ttc, min_time=cy.min_time, max_time=cy.max_time):
        return None
    mode = cy.trigger_mode or upper_tail_trigger_mode(cy.symbol)
    cy.trigger_mode = mode
    if mode == TRIGGER_TAPE:
        return _qualifying_side_from_tape(cy)
    return None


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


def _live_markets(*, force: bool = False) -> list:
    """Cached series market list — avoid REST thrash on every housekeeping tick."""
    global _live_markets_cache, _live_markets_cache_mono
    now = time.monotonic()
    if (
        not force
        and _live_markets_cache
        and (now - _live_markets_cache_mono) < LIVE_MARKETS_CACHE_SEC
    ):
        return _live_markets_cache
    out: list = []
    for series in upper_tail_series_tickers():
        out.extend(fetch_series_15m_markets(series))
    _live_markets_cache = out
    _live_markets_cache_mono = now
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
                trigger_mode=upper_tail_trigger_mode(sym),
            )
            _cycles[mid] = cy

        cy.trigger_mode = cy.trigger_mode or upper_tail_trigger_mode(sym)
        # Keep limit/contracts/paper in sync from monitor row.
        new_limit = float(limit_px)
        new_sa = int(mon.get("subaccount") or 1)
        if (
            cy.limit_px != new_limit
            or cy.contracts != contracts
            or cy.subaccount != new_sa
            or cy.ticker != tgt.market_ticker
        ):
            cy.prepared = None
        cy.limit_px = new_limit
        cy.contracts = contracts
        cy.paper = paper
        cy.subaccount = new_sa
        cy.ticker = tgt.market_ticker
        cy.close_ts = float(tgt.close_ts)

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
        if cy.done or cy.placed or cy.placing or not in_window:
            continue
        # Crypto orderbook: place only on rail_trigger. Timer never re-qualifies OB.
        if cy.trigger_mode == TRIGGER_ORDERBOOK:
            continue
        hit = _qualifying_side_tape_only(cy, now=now)
        if not hit:
            continue
        _try_fire_cycle(cy, hit, path="slow", ttc=now_ttc)

    for mid, cy in list(_cycles.items()):
        if mid not in active_ids:
            _drop_cycle(mid, cy, reason="monitor_inactive")

    _rebuild_armed_index(now)
    global _last_http_warm_mono
    if time.monotonic() - _last_http_warm_mono >= _HTTP_WARM_SEC:
        _last_http_warm_mono = time.monotonic()
        try:
            warm_kalshi_http()
        except Exception as exc:
            _log(f"http warm failed: {exc}")


def _loop() -> None:
    _log(f"timer housekeeping loop started (poll={POLL_SEC}s)")
    while True:
        try:
            _tick()
        except Exception as exc:
            _log(f"tick error: {exc}")
        # Hard rate limit. Do not Event-wake on tape/OB — that busy-loops under load.
        # Crypto places only on rail_trigger; tape/commodity qualifies on this poll.
        time.sleep(POLL_SEC)


def _start_listeners() -> None:
    # Crypto: active rail-cross trigger from OB publish path (not every delta).
    try:
        from backend.core.upper_tail_rail_trigger import start_rail_trigger_listener

        ok = start_rail_trigger_listener(
            _on_rail_trigger,
            thread_name="upper_tail_rail_trigger",
        )
        if ok:
            _log("subscribed upper_tail rail_trigger (active OB rail cross)")
        else:
            _log("rail_trigger listener not started: redis unavailable")
    except Exception as exc:
        _log(f"rail_trigger listener not started: {exc}")


@app.get("/health")
def health() -> Dict[str, Any]:
    with _lock:
        n = len(_cycles)
    with _arm_lock:
        armed_n = sum(len(v) for v in _armed_by_ticker.values())
        armed_tickers = len(_armed_by_ticker)
    return {
        "status": "ok",
        "service": "upper_tail_agent",
        "user_no": _user_no(),
        "cycles": n,
        "armed_cycles": armed_n,
        "armed_tickers": armed_tickers,
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
