"""High Water Scalp: strategy identity, close-price math, paper GTC fill simulation.

Entry is a single active-side price target (``min_ask``): fire when the
ladder ask prints that cent, then send a limit IOC at that price. TTC,
probability, movement, and verification dwell still follow Expiration Scalp.
Close rests a GTC opposite-leg buy at ``1 - limit_close_price``
(e.g. 0.99 owned-side → 0.01 opposite). Optional floor auto-stop dwell uses
``stop_verification_period_*`` (not entry ``entry_verification_period_*``).
Paper trades cannot rest on Kalshi; ``simulate_paper_resting_gtc`` walks the
live Redis book the same way a GTC would lift opposite asks at/through that limit.
Paper GTC fills are maker rests: close fee is ``0`` (Kalshi does not charge maker
on these orders). Stop-flatten remaining is still a taker close.
"""

from __future__ import annotations

from typing import Any, Optional

STRATEGY_NAME = "High Water Scalp"
STRATEGY_NAME_TEST_1 = "High Water Test 1"


def _strategy_base_name(strategy: Optional[str]) -> str:
    raw = str(strategy or "").strip()
    if raw.startswith("Reverse "):
        raw = raw[len("Reverse ") :].strip()
    return raw


def is_high_water_scalp(strategy: Optional[str]) -> bool:
    return _strategy_base_name(strategy) == STRATEGY_NAME


def is_high_water_test_1(strategy: Optional[str]) -> bool:
    return _strategy_base_name(strategy) == STRATEGY_NAME_TEST_1


def is_high_water_family(strategy: Optional[str]) -> bool:
    base = _strategy_base_name(strategy)
    return base in (STRATEGY_NAME, STRATEGY_NAME_TEST_1)


def is_expiration_scalp_entry_strategy(strategy: Optional[str]) -> bool:
    """Expiration Scalp or High Water family (same AES entry path)."""
    return _strategy_base_name(strategy) in (
        "Expiration Scalp",
        STRATEGY_NAME,
        STRATEGY_NAME_TEST_1,
    )


def ask_hits_price_target(ask: Any, target: float) -> bool:
    """True when ask equals the entry target at 1-cent grain. Never invent."""
    try:
        a = round(float(ask), 2)
        t = round(float(target), 2)
    except (TypeError, ValueError):
        return False
    if a <= 0.0 or a >= 1.0 or t <= 0.0 or t >= 1.0:
        return False
    return f"{a:.2f}" == f"{t:.2f}"


def parse_limit_close_price(raw: Any) -> Optional[float]:
    """Owned-side dollars in (0, 1). None if missing or invalid. Never invent."""
    if raw is None or raw == "":
        return None
    try:
        px = float(raw)
    except (TypeError, ValueError):
        return None
    if px <= 0.0 or px >= 1.0:
        return None
    return round(px, 4)


def parse_limit_close_offset(raw: Any) -> Optional[float]:
    """Owned-side offset from fill in (0, 1). None if missing or invalid. Never invent."""
    if raw is None or raw == "":
        return None
    try:
        off = float(raw)
    except (TypeError, ValueError):
        return None
    if off <= 0.0 or off >= 1.0:
        return None
    return round(off, 4)


def owned_close_target_from_offset(buy_price: Any, offset: Any) -> Optional[float]:
    """High Water Test 1: owned-side GTC target = fill + offset, capped below 1.0."""
    off = parse_limit_close_offset(offset)
    try:
        bp = float(buy_price)
    except (TypeError, ValueError):
        return None
    if off is None or bp <= 0.0 or bp >= 1.0:
        return None
    target = round(bp + off, 4)
    if target <= 0.0 or target >= 1.0:
        return None
    return target


def resolve_owned_close_target(
    strategy: Optional[str],
    buy_price: Any,
    limit_close_price: Any,
    limit_close_offset: Any,
) -> Optional[float]:
    """Resolve owned-side GTC target for High Water family strategies."""
    if is_high_water_test_1(strategy):
        return owned_close_target_from_offset(buy_price, limit_close_offset)
    if is_high_water_scalp(strategy):
        return parse_limit_close_price(limit_close_price)
    return None


def parse_stop_floor_price(raw: Any) -> Optional[float]:
    """Owned-side stop floor in (0, 1). None if missing, invalid, or disabled (0)."""
    if raw is None or raw == "":
        return None
    try:
        px = float(raw)
    except (TypeError, ValueError):
        return None
    if px <= 0.0 or px >= 1.0:
        return None
    return round(px, 4)


def parse_stop_loss_offset(raw: Any) -> Optional[float]:
    """Owned-side distance below fill in (0, 1). None if missing or invalid."""
    return parse_limit_close_offset(raw)


def owned_stop_floor_from_offset(buy_price: Any, offset: Any) -> Optional[float]:
    """High Water Test 1: owned-side stop floor = fill - offset."""
    off = parse_stop_loss_offset(offset)
    try:
        bp = float(buy_price)
    except (TypeError, ValueError):
        return None
    if off is None or bp <= 0.0 or bp >= 1.0:
        return None
    floor = round(bp - off, 4)
    if floor <= 0.0 or floor >= 1.0:
        return None
    return floor


def resolve_owned_stop_floor(
    strategy: Optional[str],
    buy_price: Any,
    stop_loss_price: Any,
    stop_loss_offset: Any,
) -> Optional[float]:
    """Resolve owned-side auto-stop floor for High Water family strategies."""
    if is_high_water_test_1(strategy):
        return owned_stop_floor_from_offset(buy_price, stop_loss_offset)
    if is_high_water_scalp(strategy):
        return parse_stop_floor_price(stop_loss_price)
    return None


def complement_limit_price(limit_close_price: float) -> float:
    """Opposite-leg GTC buy price for an owned-side close target."""
    return round(1.0 - float(limit_close_price), 4)


def floor_is_past(current_close_price: Any, stop_floor: Any) -> bool:
    """True when opposite ask (current_close_price) is strictly above (1 - stop_floor)."""
    try:
        sf = float(stop_floor)
        opp = float(current_close_price)
    except (TypeError, ValueError):
        return False
    if sf <= 0.0:
        return False
    return opp > (1.0 - sf)


def floor_stop_verify_allows_fire(
    past: bool,
    enabled: bool,
    seconds: Any,
    now: float,
    pending_until: Optional[float],
) -> tuple[bool, Optional[float]]:
    """HWS floor auto-stop dwell. Returns (may_fire, new_pending_until).

    When the floor is not past, pending is cleared. Disabled or seconds <= 0
    fires immediately. Otherwise arm ``now + seconds`` and fire only after that.
    """
    if not past:
        return False, None
    if not enabled:
        return True, None
    try:
        sec = int(seconds)
    except (TypeError, ValueError):
        sec = 0
    if sec <= 0:
        return True, None
    if pending_until is None:
        return False, float(now) + float(sec)
    if float(now) + 1e-9 < float(pending_until):
        return False, float(pending_until)
    return True, None


def remaining_contracts(position: Any, close_filled_count: Any) -> float:
    try:
        pos = float(position or 0.0)
    except (TypeError, ValueError):
        pos = 0.0
    try:
        filled = float(close_filled_count or 0.0)
    except (TypeError, ValueError):
        filled = 0.0
    rem = round(pos - filled, 2)
    return rem if rem > 0 else 0.0


def two_leg_close_totals(
    *,
    buy_price: Any,
    position: Any,
    filled_qty: Any,
    filled_sell: Any,
    remainder_sell: Any,
    total_fees: Any,
) -> Optional[dict[str, float]]:
    """PnL / blended sell for a live HWS row closed in two legs.

    ``filled_sell`` is the VWAP of already-closed contracts (GTC or prior close).
    ``remainder_sell`` is the leftover: expiry 0/1 or stop-flatten VWAP.
    Never invents a fill price — callers must pass real venue values.
    """
    try:
        pos = float(position)
        buy = float(buy_price)
        filled = float(filled_qty)
        gtc_sell = float(filled_sell)
        rem_sell = float(remainder_sell)
        fees = float(total_fees or 0.0)
    except (TypeError, ValueError):
        return None
    if pos <= 0:
        return None
    filled = min(max(filled, 0.0), pos)
    rem = round(pos - filled, 2)
    if rem < 0:
        rem = 0.0
    buy_value = buy * pos
    sell_value = (gtc_sell * filled) + (rem_sell * rem)
    blended_sell = sell_value / pos
    pnl = round(sell_value - buy_value - fees, 6)
    return {
        "blended_sell": blended_sell,
        "pnl": pnl,
        "buy_value": buy_value,
        "sell_value": sell_value,
        "filled_qty": filled,
        "remainder_qty": rem,
    }


def normalize_yes_no(side: Optional[str]) -> Optional[str]:
    raw = str(side or "").strip().lower()
    if raw in ("yes", "y"):
        return "yes"
    if raw in ("no", "n"):
        return "no"
    return None


def opposite_yes_no(owned_side: Optional[str]) -> Optional[str]:
    owned = normalize_yes_no(owned_side)
    if owned == "yes":
        return "no"
    if owned == "no":
        return "yes"
    return None


def owned_sell_from_opposite_vwap(opp_vwap: float) -> float:
    return round(1.0 - float(opp_vwap), 8)


def paper_resting_fill_increment(available: float, last_available: float) -> float:
    """Newly visible size at/through the GTC. Paper does not consume the live book.

    First time the book is marketable (prev <= 0): take displayed size.
    While still marketable: take only the increase vs last seen size.
    available <= 0: no fill (caller resets last_available).
    """
    try:
        avail = max(0.0, float(available or 0.0))
    except (TypeError, ValueError):
        avail = 0.0
    try:
        prev = max(0.0, float(last_available or 0.0))
    except (TypeError, ValueError):
        prev = 0.0
    if avail <= 0:
        return 0.0
    if prev <= 0:
        return round(avail, 2)
    return round(max(0.0, avail - prev), 2)


def simulate_paper_resting_gtc(
    yes_levels: dict,
    no_levels: dict,
    owned_side: Optional[str],
    limit_close_price: float,
    remaining: float,
    last_available: float,
) -> dict[str, Any]:
    """Walk opposite asks <= 1 - limit_close_price. Never invent a fill price.

    Returns ok, reason, available, fill_qty, opp_vwap, owned_sell_vwap, close_fee.
    ``close_fee`` is 0 on a fill (paper GTC is a maker rest).
    available is None only when the walk itself cannot run (bad inputs).
    """
    from backend.core.orderbook_strike_prices import project_taker_buy_from_levels

    out: dict[str, Any] = {
        "ok": False,
        "reason": "projection_failed",
        "available": None,
        "fill_qty": 0.0,
        "opp_vwap": None,
        "owned_sell_vwap": None,
        "close_fee": None,
        "reset_last": False,
    }
    opp = opposite_yes_no(owned_side)
    lcp = parse_limit_close_price(limit_close_price)
    try:
        rem = float(remaining or 0.0)
    except (TypeError, ValueError):
        rem = 0.0
    if not opp or lcp is None or rem <= 0:
        out["reason"] = "missing_projection_inputs"
        return out

    opp_limit = complement_limit_price(lcp)
    probe = project_taker_buy_from_levels(
        yes_levels, no_levels, opp, rem, limit_price=opp_limit
    )
    try:
        available = float(probe.get("available_contracts") or 0.0)
    except (TypeError, ValueError):
        available = 0.0
    out["available"] = round(available, 2)
    if available <= 0:
        out["ok"] = True
        out["reason"] = "not_marketable"
        out["reset_last"] = True
        return out

    increment = paper_resting_fill_increment(available, last_available)
    fill_qty = round(min(rem, increment), 2)
    if fill_qty <= 0:
        out["ok"] = True
        out["reason"] = "no_new_size"
        return out

    walk = project_taker_buy_from_levels(
        yes_levels, no_levels, opp, fill_qty, limit_price=opp_limit
    )
    try:
        filled = float(walk.get("filled_fp") if walk.get("filled_fp") is not None else walk.get("filled") or 0.0)
    except (TypeError, ValueError):
        filled = 0.0
    opp_vwap = walk.get("initial_proj_price")
    if filled <= 0 or opp_vwap is None:
        out["reason"] = walk.get("reason") or "no_fill_at_limit"
        return out

    out["ok"] = True
    out["reason"] = "fill"
    out["fill_qty"] = round(filled, 2)
    out["opp_vwap"] = float(opp_vwap)
    out["owned_sell_vwap"] = owned_sell_from_opposite_vwap(float(opp_vwap))
    out["close_fee"] = 0.0
    return out
