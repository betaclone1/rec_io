"""
Offline / backtest mirror of Hourly HTC strike gates from ``auto_entry_supervisor``.

**Production does not import this module.** When changing live entry logic, update
this file manually to stay aligned with the live paths:

- **Full Hourly HTC:** ``check_auto_entry_conditions_hourly_htc`` (probability,
  differential, volume, max_ask, ``strike_data``). Use ``gate_profile="full"``.
- **Simulated model-probe (hourly or 15m monitor):** ``check_simulated_15m_entry_hourly_htc``
  uses the same ladder snapshot as AES for that monitor's market: hourly rows use ``ttc_15m``
  for quarter TTC; 15m rows use native 15m ``ttc``. Side-aware 15m probability on the traded
  side; probability band includes spike ``prob_adj`` on ``min_probability`` (like full Hourly HTC).
  No min_diff, volume, max_ask, or Rising Devil range. Use ``gate_profile="simulated_15m"``
  in backtests when reconciling trades recorded from that path.

Does not handle cooldown, DB duplicate checks, or TTC window (callers supply TTC).

**Backtest spans:** optional ``probability_min`` / ``probability_max`` (and ``yes_diff_*`` /
``no_diff_*`` pairs) treat gates as **feasible** vs the strategy band: probability uses interval
overlap with ``[min_probability, max_probability]``; min differential uses ``diff_band_hi >= floor``;
max differential uses ``diff_band_hi <= max_differential``. Live strike rows use point values only.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, Literal, Mapping, Optional, Tuple

HourlyHtcGateProfile = Literal["full", "simulated_15m"]

_HIGH_PRECISION_STRIKE_SYMBOLS = frozenset({"SOL", "XRP", "DOGE"})


def _symbol_from_ticker_hint(ticker: Optional[str]) -> Optional[str]:
    if not ticker:
        return None
    t = str(ticker).upper()
    if "DOGE" in t:
        return "DOGE"
    if "XRP" in t:
        return "XRP"
    if "SOL" in t:
        return "SOL"
    if "BTC" in t:
        return "BTC"
    if "ETH" in t:
        return "ETH"
    return None


def format_strike_label(raw_strike: Any, ticker: Optional[str]) -> Optional[str]:
    if raw_strike is None:
        return None
    sym = (_symbol_from_ticker_hint(ticker) or "").upper()
    try:
        d = Decimal(str(raw_strike))
    except (InvalidOperation, TypeError, ValueError):
        s = str(raw_strike).strip()
        return f"${s}" if s else None
    if sym in _HIGH_PRECISION_STRIKE_SYMBOLS:
        q = d.quantize(Decimal("0.00001"), rounding=ROUND_HALF_UP)
        text = format(q, "f").rstrip("0").rstrip(".")
        return f"${text}"
    return f"${int(d.quantize(Decimal('1'), rounding=ROUND_HALF_UP)):,}"


def money_line_diffs_and_active_side(
    strike: float,
    current_price: float,
    probability: float,
    yes_ask_dollars: Any,
    no_ask_dollars: Any,
) -> Optional[Tuple[float, float, str]]:
    """
    Same geometry as ``strike_table_generator`` when writing yes_diff / no_diff / active_side.
    ``probability`` and ask prices are on the 0–100 cent scale for diffs; asks come from dollars.
    Returns (yes_diff, no_diff, active_side) or None if dollar asks are missing.
    """
    if not yes_ask_dollars or not no_ask_dollars:
        return None
    try:
        yes_ask_cents = float(yes_ask_dollars) * 100
        no_ask_cents = float(no_ask_dollars) * 100
    except (TypeError, ValueError):
        return None
    if strike < current_price:
        yes_diff = probability - yes_ask_cents
        no_diff = 100 - probability - no_ask_cents
        active_side = "yes"
    else:
        yes_diff = 100 - probability - yes_ask_cents
        no_diff = probability - no_ask_cents
        active_side = "no"
    return (yes_diff, no_diff, active_side)


def effective_min_probability_hourly_htc(
    settings: Mapping[str, Any],
    *,
    spike_alert_active: bool,
) -> Tuple[float, float, float]:
    """
    Returns (min_probability_effective, base_min_probability, prob_adj).
    When spike cooldown is active, min is base + prob_adj (matches supervisor).
    """
    base = float(settings["min_probability"])
    raw_adj = settings.get("prob_adj")
    if raw_adj is None:
        # No invent: missing adj means no spike bump (base only).
        prob_adj = 0.0
        if spike_alert_active:
            return (base, base, prob_adj)
        return (base, base, prob_adj)
    prob_adj = float(raw_adj)
    if spike_alert_active:
        return (base + prob_adj, base, prob_adj)
    return (base, base, prob_adj)


def evaluate_hourly_htc_strike_entry(
    settings: Mapping[str, Any],
    strike: Mapping[str, Any],
    *,
    spike_alert_active: bool = False,
    gate_profile: HourlyHtcGateProfile = "full",
) -> tuple[Optional[dict[str, Any]], Optional[str]]:
    """
    Single source of truth for Hourly HTC gates. Returns ``(payload, None)`` if all
    gates pass, else ``(None, short reason)`` for the first failing check.

    ``gate_profile="simulated_15m"`` matches ``check_simulated_15m_entry_hourly_htc`` (hourly
    and 15m monitors): probability band only (plus spike-adjusted min_probability); skips
    differential, volume, max_ask, and Rising Devil range. TTC window is enforced by the caller.

    When the strike dict includes ``probability_min`` and ``probability_max`` (backtest rows),
    the probability gate allows entry if those bounds overlap the configured min/max range
    instead of requiring the point ``probability`` alone.
    """
    if gate_profile not in ("full", "simulated_15m"):
        return None, f"invalid gate_profile={gate_profile!r}"
    active_side = strike.get("active_side")
    if not active_side:
        return None, "no_active_side"

    min_probability, _, _ = effective_min_probability_hourly_htc(
        settings, spike_alert_active=spike_alert_active
    )
    max_probability = float(settings["max_probability"])
    min_differential = settings.get("min_differential")

    def _float_opt(v: Any) -> Optional[float]:
        if v is None:
            return None
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    p_lo = _float_opt(strike.get("probability_min"))
    p_hi = _float_opt(strike.get("probability_max"))
    prob_raw = strike.get("probability")
    prob: Optional[float] = _float_opt(prob_raw) if prob_raw is not None else None

    if p_lo is not None and p_hi is not None:
        if p_lo > p_hi:
            p_lo, p_hi = p_hi, p_lo
        # Interval overlap with [min_probability, max_probability] (model vs audit band).
        if p_hi < min_probability or p_lo > max_probability:
            return None, (
                f"prob_band[{p_lo:.2f},{p_hi:.2f}] disjoint from "
                f"[{min_probability:.2f},{max_probability:.2f}]"
            )
        if prob is None:
            prob = (p_lo + p_hi) / 2.0
    else:
        if prob is None:
            return None, "probability_missing"
        if prob < min_probability:
            return None, f"prob<{min_probability:.2f} (got {prob:.2f})"
        if prob > max_probability:
            return None, f"prob>{max_probability:.2f} (got {prob:.2f})"

    yes_ask_dollars = strike.get("yes_ask_dollars")
    no_ask_dollars = strike.get("no_ask_dollars")

    if gate_profile == "full":
        if min_differential is not None:
            floor = float(min_differential) - 0.5
            if active_side == "yes":
                d_lo = _float_opt(strike.get("yes_diff_min"))
                d_hi = _float_opt(strike.get("yes_diff_max"))
                diff_point = strike.get("yes_diff")
            else:
                d_lo = _float_opt(strike.get("no_diff_min"))
                d_hi = _float_opt(strike.get("no_diff_max"))
                diff_point = strike.get("no_diff")
            if d_lo is not None and d_hi is not None:
                if d_lo > d_hi:
                    d_lo, d_hi = d_hi, d_lo
                # Feasible if the band reaches at least ``floor`` (same geometry as point diff).
                if d_hi < floor:
                    return None, (
                        f"diff_band_hi {d_hi:.2f}<{floor:.2f} for min_diff={float(min_differential):.2f} "
                        f"(band {d_lo:.2f}-{d_hi:.2f})"
                    )
            else:
                diff = diff_point
                if diff is None or diff < floor:
                    return None, f"diff<{floor:.2f} for min_diff={float(min_differential):.2f} (got {diff})"

        max_differential = settings.get("max_differential")
        if max_differential is not None:
            md = float(max_differential)
            if active_side == "yes":
                d_lo = _float_opt(strike.get("yes_diff_min"))
                d_hi = _float_opt(strike.get("yes_diff_max"))
                diff_point = strike.get("yes_diff")
            else:
                d_lo = _float_opt(strike.get("no_diff_min"))
                d_hi = _float_opt(strike.get("no_diff_max"))
                diff_point = strike.get("no_diff")
            if d_lo is not None and d_hi is not None:
                if d_lo > d_hi:
                    d_lo, d_hi = d_hi, d_lo
                if d_hi > md:
                    return None, (
                        f"diff_band_hi {d_hi:.2f}>{md:.2f} (max_differential; band {d_lo:.2f}-{d_hi:.2f})"
                    )
            else:
                diff = diff_point
                if diff is None or diff > md:
                    return None, f"diff>max_differential {md:.2f} (got {diff})"

        min_volume = settings.get("min_volume")
        if min_volume is None:
            return None, "missing_min_volume"
        volume = strike.get("volume", 0)
        if volume is None or volume < min_volume:
            return None, f"volume<{min_volume} (got {volume})"

        max_ask = settings.get("max_ask")
        if max_ask is None:
            return None, "missing_max_ask"
        if not yes_ask_dollars or not no_ask_dollars:
            return None, "missing_yes_or_no_ask_dollars"
        try:
            yes_ask_cents = float(yes_ask_dollars) * 100
            no_ask_cents = float(no_ask_dollars) * 100
        except (TypeError, ValueError):
            return None, "ask_dollars_parse_error"
        max_ask_price = max(yes_ask_cents, no_ask_cents)
        max_ask_cents = max_ask * 100 if max_ask < 1 else max_ask
        if max_ask_price > max_ask_cents:
            return None, f"max_ask {max_ask_price:.1f}c>{max_ask_cents:.1f}c cap"
    else:
        if active_side == "yes" and not yes_ask_dollars:
            return None, "missing_yes_ask_dollars"
        if active_side == "no" and not no_ask_dollars:
            return None, "missing_no_ask_dollars"

    if active_side == "yes":
        side = "yes"
        if not yes_ask_dollars:
            return None, "missing_yes_ask_dollars"
        try:
            buy_price = float(yes_ask_dollars)
        except (TypeError, ValueError):
            return None, "yes_buy_price_parse_error"
    elif active_side == "no":
        side = "no"
        if not no_ask_dollars:
            return None, "missing_no_ask_dollars"
        try:
            buy_price = float(no_ask_dollars)
        except (TypeError, ValueError):
            return None, "no_buy_price_parse_error"
    else:
        return None, "active_side_not_yes_no"

    diff = strike.get("yes_diff") if active_side == "yes" else strike.get("no_diff")
    raw_strike = strike.get("strike")
    if raw_strike is None:
        return None, "strike_missing"
    strike_label = format_strike_label(raw_strike, strike.get("ticker"))
    if not strike_label:
        return None, "strike_label_error"

    return (
        {
            "strike": strike_label,
            "side": side,
            "ticker": strike.get("ticker"),
            "buy_price": buy_price,
            "probability": prob,
            "diff": diff,
        },
        None,
    )


def try_hourly_htc_strike_entry_payload(
    settings: Mapping[str, Any],
    strike: Mapping[str, Any],
    *,
    spike_alert_active: bool = False,
    gate_profile: HourlyHtcGateProfile = "full",
) -> Optional[dict[str, Any]]:
    """
    If this strike passes Hourly HTC entry gates, return ``strike_data`` for
    ``trigger_auto_entry_trade``; otherwise None.

    Expects the same per-strike dict shape as ``get_master_strike_table_data``:
    strike, probability, yes/no ask dollars, diffs, active_side, volume, ticker.
    """
    payload, _reason = evaluate_hourly_htc_strike_entry(
        settings, strike, spike_alert_active=spike_alert_active, gate_profile=gate_profile
    )
    return payload
