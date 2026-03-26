"""Shared Kalshi REST/ticker field normalization for market watchdog scripts."""

from __future__ import annotations

import re
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

# Ticker JSON often decodes dollar fields as floats (e.g. 0.7 → wrong inferred precision).
# Normalize to fixed widths for WS table TEXT columns (Kalshi-style).
KALSHI_WS_TICKER_DOLLAR_PLACES = 4
KALSHI_WS_TICKER_FP_PLACES = 2


def format_15m_strike_from_api_floor_strike(floor_strike) -> str:
    if floor_strike is None:
        return ""
    try:
        d = Decimal(str(floor_strike))
    except Exception:
        return ""
    if d == d.to_integral_value():
        v = int(d)
        if abs(v) >= 1000:
            return f"${v:,}"
        return f"${v}"
    s = format(d.normalize(), "f")
    return f"${s}"


def strike_from_kalshi_15m_market_ticker(market_ticker: str) -> str | None:
    """
    Parse strike from contract ``market_ticker`` when REST omits ``floor_strike`` (common right
    after rollover). Kalshi encodes the price after ``-T`` (e.g. ``...-T95000.99``).

    Ignores ambiguous short integer tails (e.g. ``...-15``) so we do not invent fake strikes.
    """
    if not market_ticker or not isinstance(market_ticker, str):
        return None
    s = market_ticker.strip()
    if "-T" not in s:
        return None
    tail = s.rsplit("-T", 1)[-1].strip()
    if not tail:
        return None
    raw = tail.replace(",", "")
    if not re.fullmatch(r"-?[0-9]+(\.[0-9]+)?", raw):
        return None
    try:
        d = Decimal(raw)
    except Exception:
        return None
    if "." not in raw and d.copy_abs() < Decimal(100):
        return None
    out = format_15m_strike_from_api_floor_strike(raw)
    return out if out else None


def strike_from_kalshi_15m_rest_market(market: dict) -> str | None:
    """
    Same strike resolution as REST `market_watchdog.save_kalshi_15m_unified`:
    subtitle "... or above" fallback, else `floor_strike` via `format_15m_strike_from_api_floor_strike`.
    If still empty, derive from ``ticker`` / ``market_ticker`` when it contains ``-T{price}``.
    """
    subtitle = market.get("subtitle", "")
    strike = subtitle.split(" or above")[0].strip() if " or above" in subtitle else ""
    if market.get("floor_strike") is not None:
        strike = format_15m_strike_from_api_floor_strike(market.get("floor_strike"))
    strike = (strike or "").strip()
    if strike:
        return strike
    mt = market.get("ticker") or market.get("market_ticker") or ""
    return strike_from_kalshi_15m_market_ticker(mt)


def market_cents_from_dollars(dollars_val, legacy_cents):
    if legacy_cents is not None:
        return legacy_cents
    if dollars_val is not None and str(dollars_val).strip() != "":
        try:
            return int(round(float(dollars_val) * 100))
        except (TypeError, ValueError):
            pass
    return 0


def int_from_fixed_point(value, default=0):
    if value is None or value == "":
        return default
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return default


def normalize_kalshi_dollar_text(value, places: int = KALSHI_WS_TICKER_DOLLAR_PLACES) -> str | None:
    """Coerce API dollar field (str, int, float) to a fixed-decimal string (e.g. 4 dp: 0.7000)."""
    if value is None:
        return None
    s = str(value).strip()
    if s == "":
        return None
    try:
        d = Decimal(s)
    except (InvalidOperation, ValueError):
        return None
    q = Decimal(10) ** -places
    d = d.quantize(q, rounding=ROUND_HALF_UP)
    return format(d, f".{places}f")


def normalize_kalshi_fixed_point_text(value, places: int = KALSHI_WS_TICKER_FP_PLACES) -> str | None:
    """volume_fp / open_interest_fp: Kalshi docs use 2 decimal fixed-point strings."""
    if value is None:
        return None
    s = str(value).strip()
    if s == "":
        return None
    try:
        d = Decimal(s)
    except (InvalidOperation, ValueError):
        return None
    q = Decimal(10) ** -places
    d = d.quantize(q, rounding=ROUND_HALF_UP)
    return format(d, f".{places}f")


def _kalshi_dollar_decimal_places(*dollar_vals) -> int:
    """
    Fractional digit count from Kalshi-style dollar strings (e.g. 0.480 -> 3).
    Uses the max across provided sides so complements match the coarser input specificity.
    If none have a fractional part, default 3 (common in Kalshi ticker examples).
    """
    best = 0
    for v in dollar_vals:
        if v is None:
            continue
        s = str(v).strip()
        if not s or "." not in s:
            continue
        frac = s.split(".", 1)[1]
        best = max(best, len(frac))
    return max(best, 3) if best == 0 else best


def derive_no_side_dollars_from_yes(
    yes_bid_dollars,
    yes_ask_dollars,
    *,
    dollar_decimal_places: int | None = None,
):
    """
    Binary contract complement: no_bid ~= 1 - yes_ask, no_ask ~= 1 - yes_bid (Kalshi dollar strings).
    If ``dollar_decimal_places`` is set (e.g. ``KALSHI_WS_TICKER_DOLLAR_PLACES`` for WebSocket ticks),
    use that width so complements match normalized yes sides. Otherwise infer from string inputs
    (minimum 3 when unspecified).
    """
    places = (
        dollar_decimal_places
        if dollar_decimal_places is not None
        else _kalshi_dollar_decimal_places(yes_bid_dollars, yes_ask_dollars)
    )
    q = Decimal(10) ** -places
    _fmt = f".{places}f"
    one = Decimal("1")
    no_bid_s = None
    no_ask_s = None
    if yes_ask_dollars is not None and str(yes_ask_dollars).strip() != "":
        try:
            d = (one - Decimal(str(yes_ask_dollars))).quantize(q, rounding=ROUND_HALF_UP)
            no_bid_s = format(d, _fmt)
        except Exception:
            pass
    if yes_bid_dollars is not None and str(yes_bid_dollars).strip() != "":
        try:
            d = (one - Decimal(str(yes_bid_dollars))).quantize(q, rounding=ROUND_HALF_UP)
            no_ask_s = format(d, _fmt)
        except Exception:
            pass
    return no_bid_s, no_ask_s


def ticker_msg_to_row_values(
    msg: dict,
    *,
    symbol: str,
    event_ticker: str,
    exchange: str,
):
    """
    Map Kalshi WebSocket Market Ticker `msg` (see docs.kalshi.com/websockets/market-ticker)
    to values for `live_data.market_kalshi_ws_15m` (dollar-quote columns + volume_fp + open_interest_fp text).
    """
    sym = symbol.upper()
    br = exchange.lower().strip()
    market_val = "15m"
    market_ticker = msg.get("market_ticker") or ""
    if not market_ticker:
        raise ValueError("missing market_ticker")

    yes_bid_dollars = msg.get("yes_bid_dollars")
    yes_ask_dollars = msg.get("yes_ask_dollars")
    last_price_dollars = msg.get("price_dollars")

    yb = normalize_kalshi_dollar_text(yes_bid_dollars, KALSHI_WS_TICKER_DOLLAR_PLACES)
    ya = normalize_kalshi_dollar_text(yes_ask_dollars, KALSHI_WS_TICKER_DOLLAR_PLACES)
    no_bid_dollars, no_ask_dollars = derive_no_side_dollars_from_yes(
        yb, ya, dollar_decimal_places=KALSHI_WS_TICKER_DOLLAR_PLACES
    )
    last_out = normalize_kalshi_dollar_text(last_price_dollars, KALSHI_WS_TICKER_DOLLAR_PLACES)

    volume_fp = normalize_kalshi_fixed_point_text(
        msg.get("volume_fp"), KALSHI_WS_TICKER_FP_PLACES
    )
    open_interest_fp = normalize_kalshi_fixed_point_text(
        msg.get("open_interest_fp"), KALSHI_WS_TICKER_FP_PLACES
    )
    strike = strike_from_kalshi_15m_market_ticker(market_ticker)

    return (
        sym,
        br,
        event_ticker,
        market_ticker,
        market_val,
        strike,
        yb,
        ya,
        no_bid_dollars,
        no_ask_dollars,
        last_out,
        volume_fp,
        open_interest_fp,
    )
