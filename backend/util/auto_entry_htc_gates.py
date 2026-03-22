"""
Offline / backtest mirror of Hourly HTC strike gates from ``auto_entry_supervisor``.

**Production does not import this module.** When changing live entry logic, update
this file manually to stay aligned with the live paths:

- **Full Hourly HTC:** ``check_auto_entry_conditions_hourly_htc`` (probability,
  differential, volume, max_ask, ``strike_data``). Use ``gate_profile="full"``.
- **Simulated 15m (hourly monitor):** ``check_simulated_15m_entry_hourly_htc`` only
  checks TTC window + probability band + duplicate/cooldown (handled elsewhere live);
  it does **not** apply min_diff, volume, or max_ask. Use ``gate_profile="simulated_15m"``
  in backtests when reconciling trades recorded from that path.

Does not handle cooldown, DB duplicate checks, or TTC window (callers supply TTC).
"""

from __future__ import annotations

from typing import Any, Literal, Mapping, Optional, Tuple

HourlyHtcGateProfile = Literal["full", "simulated_15m"]


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
    prob_adj = float(settings.get("prob_adj", 5.00))
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

    ``gate_profile="simulated_15m"`` matches ``check_simulated_15m_entry_hourly_htc``:
    probability band only (plus spike-adjusted min_probability); skips differential,
    volume, and max_ask caps. TTC window is enforced by the caller.
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
    prob = strike.get("probability")
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
            diff = strike.get("yes_diff") if active_side == "yes" else strike.get("no_diff")
            floor = float(min_differential) - 0.5
            if diff is None or diff < floor:
                return None, f"diff<{floor:.2f} for min_diff={float(min_differential):.2f} (got {diff})"

        max_differential = settings.get("max_differential")
        if max_differential is not None:
            diff = strike.get("yes_diff") if active_side == "yes" else strike.get("no_diff")
            if diff is None or diff > float(max_differential):
                return None, f"diff>max_differential {float(max_differential):.2f} (got {diff})"

        min_volume = settings.get("min_volume", 1000)
        volume = strike.get("volume", 0)
        if volume is None or volume < min_volume:
            return None, f"volume<{min_volume} (got {volume})"

        max_ask = settings.get("max_ask", 0.9800)
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
    try:
        strike_label = f"${int(raw_strike):,}"
    except (TypeError, ValueError):
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
