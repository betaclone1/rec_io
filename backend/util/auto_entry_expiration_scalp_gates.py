"""
Expiration Scalp entry + floor-exit gates (offline mirror + shared helpers).

Keep aligned with:

- Entry: ``auto_entry_supervisor.check_auto_entry_conditions_expiration_scalp``
- Exit: ``active_trade_supervisor.check_auto_stop_conditions_expiration_scalp``
  (stop-loss ask floor only; natural expiry is handled by the replay runner)

Does not handle cooldown, DB duplicate checks, spike alerts, or AES service health.
Callers supply TTC and market asks/probs for a single ticker (or ladder row).

Entry verification dwell (``update_expiration_scalp_entry_verification``) is used by
production AES when ``entry_verification_period_enabled`` is set on the monitor.
"""

from __future__ import annotations

import os
from typing import Any, Mapping, Optional, Tuple


def ask_dollars_to_cent(ask: Any) -> Optional[str]:
    """Round ask to 1¢, same grain as tradeflow lane fingerprints."""
    try:
        return f"{round(float(ask), 2):.2f}"
    except (TypeError, ValueError):
        return None


def exp_scalp_flicker_gate_enabled(*, cutout: bool) -> bool:
    """Default on for BTC 15m Exp Scalp cutout; off elsewhere. Env overrides."""
    raw = os.getenv("EXP_SCALP_FLICKER_GATE", "").strip().lower()
    if raw in ("0", "false", "off", "no"):
        return False
    if raw in ("1", "true", "on", "yes"):
        return True
    return bool(cutout)


def exp_scalp_flicker_step_cents() -> int:
    """0 = disabled (default). Set EXP_SCALP_FLICKER_STEP_CENTS>=1 to restore drop-step."""
    raw = os.getenv("EXP_SCALP_FLICKER_STEP_CENTS", "0").strip()
    if raw == "":
        return 0
    try:
        return max(0, min(int(raw), 20))
    except (TypeError, ValueError):
        return 0


def exp_scalp_flicker_live_band_enabled() -> bool:
    v = os.getenv("EXP_SCALP_FLICKER_LIVE_BAND", "1").strip().lower()
    return v not in ("0", "false", "off", "no")


def exp_scalp_busy_book_enabled(*, cutout: bool) -> bool:
    """Two-way chop pauses verify. Default on for cutout. Env overrides."""
    raw = os.getenv("EXP_SCALP_BUSY_BOOK", "").strip().lower()
    if raw in ("0", "false", "off", "no"):
        return False
    if raw in ("1", "true", "on", "yes"):
        return True
    return bool(cutout)


def expiration_scalp_busy_book_gate(
    *,
    prior_ask_cent: Optional[str],
    prior_dir: Optional[int],
    ask: float,
) -> Tuple[Optional[str], Optional[int]]:
    """
    Pause verify when the in-band ask reverses by ≥1¢.

    One-way grind (only ups, or only downs) does not reset. Flat prints do not.
    Returns ``(reason_or_None, new_dir)`` where dir is ``1`` up, ``-1`` down, or
    prior dir if unchanged.
    """
    cur = ask_dollars_to_cent(ask)
    if cur is None:
        return None, prior_dir
    if not prior_ask_cent:
        return None, None
    try:
        delta = int(round((float(cur) - float(prior_ask_cent)) * 100.0))
    except (TypeError, ValueError):
        return None, prior_dir
    if delta == 0:
        return None, prior_dir
    new_dir = 1 if delta > 0 else -1
    try:
        old_dir = int(prior_dir) if prior_dir is not None else 0
    except (TypeError, ValueError):
        old_dir = 0
    if old_dir in (1, -1) and new_dir == -old_dir:
        return "busy_book_reversal", new_dir
    return None, new_dir


def expiration_scalp_flicker_gate(
    *,
    prior_ask_cent: Optional[str],
    snapshot_ask: float,
    min_ask: float,
    max_ask: float,
    live_ask: Optional[float] = None,
    step_cents: int = 0,
) -> Tuple[Optional[str], Optional[str]]:
    """
    Stability veto during Exp Scalp verify. Snapshot still owns fire.

    Default (prod-mimic): abort if **live** ask is outside the monitor band while
    the snapshot is still in-band. Missing/stale ``live_ask`` skips the veto.

    Optional drop-step (off unless ``step_cents >= 1``): reset dwell when snapshot
    ask dropped vs last verify tick. Not prod behavior.
    """
    if live_ask is not None:
        try:
            live_f = float(live_ask)
        except (TypeError, ValueError):
            live_f = None
        if live_f is not None and (live_f < float(min_ask) or live_f > float(max_ask)):
            return "abort", "flicker_live_outside_band"

    try:
        need = int(step_cents)
    except (TypeError, ValueError):
        need = 0
    if need < 1:
        return None, None

    cur = ask_dollars_to_cent(snapshot_ask)
    if cur is None:
        return None, None
    if not prior_ask_cent:
        return None, None
    try:
        drop_cents = int(round((float(prior_ask_cent) - float(cur)) * 100.0))
    except (TypeError, ValueError):
        return None, None
    if drop_cents >= need:
        return "reset", "flicker_ask_step"
    return None, None


def update_expiration_scalp_entry_verification(
    state: Optional[Mapping[str, Any]],
    *,
    eligible: bool,
    now_ts: float,
    enabled: bool,
    period_seconds: int,
) -> Tuple[Optional[dict], bool, float]:
    """
    Contiguous eligibility dwell before Exp Scalp entry.

    Returns ``(new_state, may_enter, dwell_seconds)``.

    - Disabled: ``may_enter`` follows ``eligible``; state cleared.
    - Enabled with ``period_seconds <= 0``: first eligible tick may enter.
    - Enabled: accumulate continuous eligibility; any ineligible tick resets.
    """
    if not enabled:
        return None, bool(eligible), 0.0
    try:
        need = max(0, int(period_seconds))
    except (TypeError, ValueError):
        need = 0
    if not eligible:
        return None, False, 0.0
    started = None
    if state is not None:
        try:
            started = float(state.get("started_at"))
        except (TypeError, ValueError, AttributeError):
            started = None
    if started is None:
        started = float(now_ts)
    dwell = max(0.0, float(now_ts) - started)
    new_state = {"started_at": started}
    if dwell >= float(need):
        return new_state, True, dwell
    return new_state, False, dwell


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


def parse_min_buffer_pct(settings: Mapping[str, Any]) -> float:
    """Monitor ``min_buffer_pct``; missing/invalid/≤0 → 0 (gate disabled)."""
    raw = settings.get("min_buffer_pct") if settings is not None else None
    if raw is None or raw == "":
        return 0.0
    try:
        v = float(raw)
    except (TypeError, ValueError):
        return 0.0
    if v <= 0:
        return 0.0
    return v


def _buffer_pct_meets_floor(
    buffer_pct: Optional[float],
    floor: float,
    *,
    missing_reason: str,
    bad_reason: str,
    below_reason: str,
) -> Optional[str]:
    if buffer_pct is None:
        return missing_reason
    try:
        bp = float(buffer_pct)
    except (TypeError, ValueError):
        return bad_reason
    if bp < floor:
        return below_reason
    return None


def expiration_scalp_min_buffer_pct_gate(
    *,
    buffer_pct: Optional[float],
    min_buffer_pct: float,
    avg_60s_buffer_pct: Optional[float] = None,
) -> Optional[str]:
    """
    Reject when ladder spot or 60s-avg buffer_pct is below the configured floor.

    ``min_buffer_pct <= 0`` disables. Same units as hot-path ``buffer_pct`` /
    ``60s_avg_buffer_pct`` (percent of reference price). Missing/bad values fail
    closed when gate is on. Both legs must pass when enabled.
    """
    floor = float(min_buffer_pct or 0.0)
    if floor <= 0:
        return None
    for bp, missing, bad, below in (
        (
            buffer_pct,
            "missing_buffer_pct",
            "bad_buffer_pct",
            "buffer_pct_below_min",
        ),
        (
            avg_60s_buffer_pct,
            "missing_60s_avg_buffer_pct",
            "bad_60s_avg_buffer_pct",
            "60s_avg_buffer_pct_below_min",
        ),
    ):
        reject = _buffer_pct_meets_floor(
            bp,
            floor,
            missing_reason=missing,
            bad_reason=bad,
            below_reason=below,
        )
        if reject:
            return reject
    return None


def evaluate_expiration_scalp_entry(
    settings: Mapping[str, Any],
    *,
    ttc_seconds: int,
    side: str,
    ask_dollars: Optional[float],
    probability: Optional[float],
    movement_percentile: Optional[float] = None,
    buffer_pct: Optional[float] = None,
    avg_60s_buffer_pct: Optional[float] = None,
    high_water_scalp: bool = False,
) -> tuple[Optional[dict[str, Any]], Optional[str]]:
    """
    Pure Exp Scalp entry gate for one side of one contract.

    Returns (strike_data_dict, None) on pass, or (None, reason) on reject.
    ``buy_price`` is the ladder ask for Expiration Scalp, or the configured
    price target for High Water Scalp (limit IOC at that price).

    Prob+movement joint gate: see ``classify_expiration_scalp_prob_movement``.
    ``min_buffer_pct`` (when > 0) requires ladder ``buffer_pct`` and
    ``60s_avg_buffer_pct`` ≥ floor.
    Passed dict may include ``half_size`` True for out-of-prob / in-movement rescues.
    """
    try:
        min_time = int(settings["min_time"])
        max_time = int(settings["max_time"])
        min_probability = float(settings["min_probability"])
        max_probability = float(settings["max_probability"])
        min_ask = float(settings["min_ask"])
        max_ask = float(settings["max_ask"])
        min_movement = float(settings["min_movement"])
        max_movement = float(settings["max_movement"])
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
    if high_water_scalp:
        from backend.core.high_water_scalp import ask_hits_price_target, parse_limit_close_price

        target = parse_limit_close_price(min_ask)
        if target is None:
            return None, "missing_price_target"
        if not ask_hits_price_target(ask_price, target):
            return None, "ask_misses_price_target"
        buy_price = target
    else:
        if ask_price < min_ask or ask_price > max_ask:
            return None, "ask_outside_band"
        buy_price = ask_price

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

    min_buf = parse_min_buffer_pct(settings)
    buf_reject = expiration_scalp_min_buffer_pct_gate(
        buffer_pct=buffer_pct,
        avg_60s_buffer_pct=avg_60s_buffer_pct,
        min_buffer_pct=min_buf,
    )
    if buf_reject:
        return None, buf_reject

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
            "buy_price": buy_price,
            "entry_limit_price": buy_price if high_water_scalp else None,
            "probability": prob,
            "ttc_seconds": int(ttc_seconds),
            "movement_percentile": float(movement_percentile)
            if movement_percentile is not None
            else None,
            "buffer_pct": float(buffer_pct) if buffer_pct is not None else None,
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
