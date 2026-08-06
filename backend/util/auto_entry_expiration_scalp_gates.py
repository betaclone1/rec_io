"""
Offline / backtest mirror of Expiration Scalp entry + floor-exit gates.

**Production does not import this module.** Keep aligned manually with:

- Entry: ``auto_entry_supervisor.check_auto_entry_conditions_expiration_scalp``
- Exit: ``active_trade_supervisor.check_auto_stop_conditions_expiration_scalp``
  (stop-loss ask floor only; natural expiry is handled by the replay runner)

Does not handle cooldown, DB duplicate checks, spike alerts, or AES service health.
Callers supply TTC and market asks/probs for a single ticker (or ladder row).
"""

from __future__ import annotations

from typing import Any, Mapping, Optional


def side_aware_probability_15m(
    row: Mapping[str, Any],
    side: str,
) -> Optional[float]:
    """Mirror ``probability_from_strike_row_side_aware`` for market=15m."""
    su = (side or "").strip().upper()
    if su in ("YES", "Y"):
        su = "Y"
    elif su in ("NO", "N"):
        su = "N"
    else:
        return None

    def _f(key: str) -> Optional[float]:
        v = row.get(key)
        if v in (None, ""):
            return None
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    if su == "Y":
        v = _f("yes_prob_15m")
        if v is None:
            v = _f("probability_15m")
    else:
        v = _f("no_prob_15m")
        if v is None:
            v = _f("probability_15m")
    if v is None:
        v = _f("probability")
    return v


def classify_expiration_scalp_prob_movement(
    *,
    probability: float,
    movement_percentile: Optional[float],
    min_probability: float,
    max_probability: float,
    min_movement: float = 0.0,
    max_movement: float = 100.0,
) -> tuple[str, str]:
    """
    Joint probability + movement gate for Expiration Scalp.

    - Inside probability → ``full`` (movement ignored).
    - Outside probability but inside movement → ``half`` (½ position size).
    - Outside both (or outside prob with missing movement) → ``block``.
    """
    in_prob = float(min_probability) <= float(probability) <= float(max_probability)
    if in_prob:
        return "full", "in_probability_window"

    in_mov = False
    if movement_percentile is not None:
        try:
            mov = float(movement_percentile)
            in_mov = float(min_movement) <= mov <= float(max_movement)
        except (TypeError, ValueError):
            in_mov = False

    if in_mov:
        return "half", "out_of_prob_in_movement_half_size"
    return "block", "out_of_probability_and_movement"


def evaluate_expiration_scalp_entry(
    settings: Mapping[str, Any],
    *,
    ttc_seconds: int,
    side: str,
    ask_dollars: Optional[float],
    probability: Optional[float],
    movement_percentile: Optional[float] = None,
) -> tuple[Optional[dict[str, Any]], Optional[str]]:
    """
    Pure Exp Scalp entry gate for one side of one contract.

    Returns (strike_data_dict, None) on pass, or (None, reason) on reject.
    ``buy_price`` is the ladder ask (live ticket price before executor VWAP/min_fill).

    Prob+movement joint gate: see ``classify_expiration_scalp_prob_movement``.
    Passed dict may include ``half_size`` True for out-of-prob / in-movement rescues.
    """
    try:
        min_time = int(settings["min_time"])
        max_time = int(settings["max_time"])
        min_probability = float(settings["min_probability"])
        max_probability = float(settings.get("max_probability", 100))
        min_ask = float(settings.get("min_ask", 0.90))
        max_ask = float(settings.get("max_ask", 0.99))
        min_movement = float(settings.get("min_movement", 0.0))
        max_movement = float(settings.get("max_movement", 100.0))
    except (KeyError, TypeError, ValueError) as e:
        return None, f"bad_settings:{e}"

    if not (min_time <= int(ttc_seconds) <= max_time):
        return None, "ttc_outside_window"

    if ask_dollars is None:
        return None, "missing_ask"
    try:
        ask_price = float(ask_dollars)
    except (TypeError, ValueError):
        return None, "bad_ask"
    if ask_price < min_ask or ask_price > max_ask:
        return None, "ask_outside_band"

    if probability is None:
        return None, "missing_probability"
    try:
        prob = float(probability)
    except (TypeError, ValueError):
        return None, "bad_probability"

    size_mode, size_reason = classify_expiration_scalp_prob_movement(
        probability=prob,
        movement_percentile=movement_percentile,
        min_probability=min_probability,
        max_probability=max_probability,
        min_movement=min_movement,
        max_movement=max_movement,
    )
    if size_mode == "block":
        return None, size_reason

    side_l = (side or "").strip().lower()
    if side_l in ("y", "yes"):
        side_l = "yes"
    elif side_l in ("n", "no"):
        side_l = "no"
    else:
        return None, "bad_side"

    return (
        {
            "side": side_l,
            "buy_price": ask_price,
            "probability": prob,
            "ttc_seconds": int(ttc_seconds),
            "movement_percentile": float(movement_percentile)
            if movement_percentile is not None
            else None,
            "half_size": size_mode == "half",
            "size_mode": size_mode,
            "size_reason": size_reason,
        },
        None,
    )


def evaluate_expiration_scalp_floor_exit(
    settings: Mapping[str, Any],
    *,
    position_side: str,
    yes_ask: Optional[float],
    no_ask: Optional[float],
    confirm_ticks: int = 1,
    prior_confirm_count: int = 0,
) -> tuple[bool, int, Optional[str]]:
    """
    Floor-only Exp Scalp exit (no live Kalshi quote guard / probability divergence).

    Live ATS passes ttc=0/min_ttc=0 so the floor is always eligible on TTC.
    Trigger when opposite-side ask > (1 - stop_loss_price).

    Returns (should_exit, new_confirm_count, detail_or_None).
    """
    try:
        stop_floor = float(settings.get("stop_loss_price") or 0)
    except (TypeError, ValueError):
        return False, 0, None
    if stop_floor <= 0:
        return False, 0, None

    su = (position_side or "").strip().upper()
    if su in ("YES", "Y"):
        opp_ask = no_ask
    elif su in ("NO", "N"):
        opp_ask = yes_ask
    else:
        return False, 0, None

    if opp_ask is None:
        return False, 0, None

    threshold_ask = 1.0 - stop_floor
    if float(opp_ask) <= threshold_ask:
        return False, 0, None

    new_count = int(prior_confirm_count) + 1
    need = max(1, int(confirm_ticks))
    if new_count < need:
        return False, new_count, f"floor_confirming opp_ask={float(opp_ask):.4f} threshold={threshold_ask:.4f}"
    return (
        True,
        new_count,
        f"stop_loss_floor opp_ask={float(opp_ask):.4f} threshold={threshold_ask:.4f}",
    )
