from __future__ import annotations

from collections import defaultdict
from decimal import Decimal, ROUND_DOWN
from typing import Any, Dict, List, Optional, Sequence, Tuple

from backend.core.orderbook_strike_prices import project_taker_buy_from_levels

CENT_BANDS = (1, 2, 3, 5, 10, 15)
ROLL_WINDOWS_S = (1, 3, 5, 10, 30, 60)
DEFAULT_SIZES = (1, 5, 10, 25, 50, 100)
MOVE_CENTS = (1, 2, 5, 10)
PUBLIC_TRADE_WINDOWS_S = (1, 3, 5, 10, 30, 60)


def _f(v: Any) -> Optional[float]:
    if v in (None, ""):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def whole_cent_key(price: float) -> str:
    d = Decimal(str(price)).quantize(Decimal("0.01"), rounding=ROUND_DOWN)
    return f"{d:.2f}"


def aggregate_whole_cent(book: Dict[str, str]) -> Dict[str, float]:
    out: Dict[str, float] = defaultdict(float)
    for px, sz in book.items():
        p = _f(px)
        q = _f(sz)
        if p is None or q is None or q <= 0:
            continue
        out[whole_cent_key(p)] += q
    return dict(sorted(out.items(), key=lambda kv: float(kv[0]), reverse=True))


def complementary_asks(yes: Dict[str, str], no: Dict[str, str], side: str) -> List[Tuple[float, float]]:
    side_n = str(side).strip().lower()
    src = no if side_n in ("y", "yes") else yes
    asks: List[Tuple[float, float]] = []
    for px, qty in (src or {}).items():
        bid = _f(px)
        sz = _f(qty)
        if bid is None or sz is None or sz <= 0:
            continue
        ask = 1.0 - bid
        if ask <= 0 or ask >= 1:
            continue
        asks.append((ask, sz))
    asks.sort(key=lambda x: x[0])
    return asks


def depth_within_cents(
    asks: Sequence[Tuple[float, float]],
    *,
    best_ask: Optional[float],
    cents: int,
) -> float:
    if best_ask is None:
        return 0.0
    limit = best_ask + (cents / 100.0)
    return sum(sz for px, sz in asks if px <= limit + 1e-12)


def largest_shelf(asks: Sequence[Tuple[float, float]]) -> Tuple[Optional[float], Optional[float]]:
    if not asks:
        return None, None
    px, sz = max(asks, key=lambda x: x[1])
    return px, sz


def empty_whole_cent_levels(asks: Sequence[Tuple[float, float]], *, bands: int = 15) -> int:
    if not asks:
        return bands
    best = asks[0][0]
    present = {whole_cent_key(px) for px, _ in asks}
    empty = 0
    for i in range(bands):
        target = whole_cent_key(best + i / 100.0)
        if target not in present:
            empty += 1
    return empty


def qty_to_move_cents(asks: Sequence[Tuple[float, float]], *, cents: int) -> Optional[float]:
    if not asks:
        return None
    best = asks[0][0]
    target = best + cents / 100.0
    qty = 0.0
    for px, sz in asks:
        if px < target - 1e-12:
            qty += sz
        else:
            break
    return qty


def vwap_metrics(
    yes: Dict[str, str],
    no: Dict[str, str],
    side: str,
    size: float,
) -> Dict[str, Any]:
    proj = project_taker_buy_from_levels(yes, no, side, size, limit_price=None)
    asks = complementary_asks(yes, no, side)
    best = asks[0][0] if asks else None
    vwap = proj.get("initial_proj_price")
    filled = float(proj.get("filled_fp") or 0.0)
    slip = None
    if vwap is not None and best is not None:
        slip = float(vwap) - float(best)
    worst = None
    if asks and filled > 0:
        rem = filled
        for px, sz in asks:
            take = min(rem, sz)
            if take > 0:
                worst = px
            rem -= take
            if rem <= 0:
                break
    return {
        "size": size,
        "ok": bool(proj.get("ok")),
        "reason": proj.get("reason"),
        "vwap": vwap,
        "filled": filled,
        "available": proj.get("available_contracts"),
        "fees": proj.get("initial_proj_fees"),
        "best_ask": best,
        "slippage": slip,
        "worst_level": worst,
        "fill_coverage": (filled / size) if size else None,
    }


def liquidation_vwap(
    yes: Dict[str, str],
    no: Dict[str, str],
    side: str,
    size: float,
) -> Dict[str, Any]:
    side_n = str(side).strip().lower()
    book = yes if side_n in ("y", "yes") else no
    action = "sell_yes_into_bids" if side_n in ("y", "yes") else "sell_no_into_bids"
    bids = []
    for px, qty in (book or {}).items():
        p = _f(px)
        q = _f(qty)
        if p is None or q is None or q <= 0:
            continue
        bids.append((p, q))
    bids.sort(key=lambda x: -x[0])
    rem = float(size)
    filled = 0.0
    notional = 0.0
    worst = None
    for px, q in bids:
        if rem <= 0:
            break
        take = min(rem, q)
        notional += px * take
        filled += take
        worst = px
        rem -= take
    vwap = (notional / filled) if filled else None
    best = bids[0][0] if bids else None
    return {
        "size": size,
        "ok": filled + 1e-9 >= float(size),
        "vwap": vwap,
        "filled": filled,
        "best_bid": best,
        "slippage": (float(best) - float(vwap)) if (vwap is not None and best is not None) else None,
        "worst_level": worst,
        "fill_coverage": (filled / size) if size else None,
        "side_action": action,
    }


def book_liquidity_snapshot(
    yes: Dict[str, str],
    no: Dict[str, str],
    *,
    side: str = "yes",
    sizes: Sequence[float] = DEFAULT_SIZES,
) -> Dict[str, Any]:
    asks = complementary_asks(yes, no, side)
    best = asks[0][0] if asks else None
    shelf_px, shelf_sz = largest_shelf(asks)
    total = sum(sz for _, sz in asks)
    conc = (shelf_sz / total) if (shelf_sz and total) else None
    return {
        "side": side,
        "best_ask": best,
        "cum_depth_cents": {f"c{c}": depth_within_cents(asks, best_ask=best, cents=c) for c in CENT_BANDS},
        "largest_shelf_price": shelf_px,
        "largest_shelf_size": shelf_sz,
        "depth_concentration": conc,
        "empty_whole_cent_levels_15": empty_whole_cent_levels(asks, bands=15),
        "qty_to_move_cents": {f"c{c}": qty_to_move_cents(asks, cents=c) for c in MOVE_CENTS},
        "entry_vwap_by_size": {str(s): vwap_metrics(yes, no, side, float(s)) for s in sizes},
        "liquidation_vwap_by_size": {str(s): liquidation_vwap(yes, no, side, float(s)) for s in sizes},
        "whole_cent_ask_ladder": aggregate_whole_cent({str(px): str(sz) for px, sz in asks}),
        "raw_ask_ladder": [{"price": px, "size": sz} for px, sz in asks[:80]],
        "raw_level_count": len(asks),
    }


def normalize_yes_price_dollars(t: Dict[str, Any]) -> Optional[float]:
    """Return YES price in dollars. Accept dollars or whole cents."""
    for key in ("yes_price_dollars", "yes_price"):
        v = _f(t.get(key))
        if v is None:
            continue
        if v > 1.0 + 1e-9:
            return v / 100.0
        return v
    return None


def map_taker_signed_contracts(t: Dict[str, Any], count: float) -> Optional[float]:
    """
    +count if taker lifts YES, -count if taker lifts NO.
    None if not determinable.
    """
    taker = t.get("taker_side")
    outcome = t.get("taker_outcome_side")
    raw = taker if taker not in (None, "") else outcome
    if raw in (None, ""):
        return None
    s = str(raw).strip().lower()
    if s in ("yes", "y", "buy"):
        return float(count)
    if s in ("no", "n", "sell"):
        return -float(count)
    return None


def public_trade_window_stats(
    trades: List[Dict[str, Any]],
    *,
    center_ts: float,
    window_s: float,
    side_hint: Optional[str] = None,
    mode: str = "trailing",
) -> Dict[str, Any]:
    """
    Aggregate public prints relative to an observation timestamp.

    Decision-time default (``mode="trailing"``): strictly
    ``[observation_ts - window_s, observation_ts]`` — never future prints.

    Optional ``mode="post"``: ``(observation_ts, observation_ts + window_s]`` for
    explicitly named post-event/collapse context only (not entry features).
    """
    from backend.core.cycle_recon.time_util import parse_utc

    obs = float(center_ts)
    mode_l = str(mode or "trailing").strip().lower()
    if mode_l == "post":
        lo = obs
        hi = obs + float(window_s)

        def _in_win(ts: float) -> bool:
            return lo < ts <= hi
    else:
        lo = obs - float(window_s)
        hi = obs

        def _in_win(ts: float) -> bool:
            return lo <= ts <= hi

    rows = []
    for t in trades:
        ts = t.get("_ts")
        if ts is None:
            ct = t.get("created_time") or t.get("utc_timecode")
            if not ct:
                continue
            try:
                ts = parse_utc(ct).timestamp()
            except Exception:
                continue
        ts_f = float(ts)
        if _in_win(ts_f):
            rows.append((ts_f, t))
    rows.sort(key=lambda x: x[0])
    empty = {
        "window_s": window_s,
        "mode": "post" if mode_l == "post" else "trailing",
        "count": 0,
        "contracts": 0.0,
        "notional_yes_dollars": None,
        "vwap_yes_dollars": None,
        "largest_print": None,
        "price_levels_crossed": 0,
        "time_since_trade_s": None,
        "aggressor_flow": "UNKNOWN",
        "signed_flow": "UNKNOWN",
        "signed_flow_contracts": None,
        "yes_price_unit": "dollars",
        "window_start_ts": lo,
        "window_end_ts": hi,
    }
    if not rows:
        return empty

    if mode_l != "post":
        for ts_f, _ in rows:
            if ts_f > obs + 1e-9:
                raise RuntimeError(
                    f"public trade leakage: trade_ts={ts_f} > observation_ts={obs}"
                )

    contracts = 0.0
    notional = 0.0
    prices: List[float] = []
    largest = 0.0
    signed = 0.0
    signed_known = 0
    for ts, t in rows:
        cnt = _f(t.get("count") or t.get("count_fp")) or 0.0
        ypx = normalize_yes_price_dollars(t)
        contracts += cnt
        if ypx is not None:
            notional += ypx * cnt
            prices.append(ypx)
        largest = max(largest, cnt)
        mapped = map_taker_signed_contracts(t, cnt)
        if mapped is not None:
            signed_known += 1
            signed += mapped
    vwap = (notional / contracts) if contracts else None
    levels = len(set(round(p, 4) for p in prices))
    last_ts = rows[-1][0]
    return {
        "window_s": window_s,
        "mode": "post" if mode_l == "post" else "trailing",
        "count": len(rows),
        "contracts": contracts,
        "notional_yes_dollars": notional if contracts else None,
        "vwap_yes_dollars": vwap,
        "largest_print": largest,
        "price_levels_crossed": levels,
        "time_since_trade_s": obs - last_ts if mode_l != "post" else last_ts - obs,
        "aggressor_flow": (
            "KNOWN" if signed_known == len(rows) and rows else ("PARTIAL" if signed_known else "UNKNOWN")
        ),
        "signed_flow": signed if signed_known else "UNKNOWN",
        "signed_flow_contracts": signed if signed_known else None,
        "yes_price_unit": "dollars",
        "window_start_ts": lo,
        "window_end_ts": hi,
    }


def strike_buffer(
    spot: Optional[float],
    floor_strike: Optional[float],
) -> Dict[str, Optional[float]]:
    if spot is None or floor_strike is None:
        return {"buffer_dollars": None, "buffer_pct": None}
    buf = float(spot) - float(floor_strike)
    pct = (buf / float(floor_strike) * 100.0) if floor_strike else None
    return {"buffer_dollars": buf, "buffer_pct": pct}
