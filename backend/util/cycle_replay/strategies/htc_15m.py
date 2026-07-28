"""15m HTC (and Hourly HTC on a single-ticker package) cycle-replay adapter."""

from __future__ import annotations

from typing import Any, Mapping, Optional

from backend.core.cycle_package import CyclePackage, CycleTick
from backend.util.auto_entry_expiration_scalp_gates import evaluate_expiration_scalp_floor_exit
from backend.util.auto_entry_htc_gates import (
    evaluate_hourly_htc_strike_entry,
    money_line_diffs_and_active_side,
)
from backend.util.cycle_replay.trade_shape import normalize_trade_side
from backend.util.cycle_replay.types import EntryEvent, ExitEvent, ReplayPosition


def _volume_from_package(pkg: CyclePackage) -> float:
    raw = (pkg.market_meta or {}).get("volume_fp")
    if raw in (None, ""):
        raw = (pkg.meta or {}).get("volume_fp")
    try:
        return float(raw)
    except (TypeError, ValueError):
        return 0.0


def _side_prob(tick: CycleTick, side: str) -> Optional[float]:
    su = str(side).strip().lower()
    if su in ("y", "yes"):
        v = tick.yes_prob_15m if tick.yes_prob_15m is not None else tick.probability_15m
    else:
        v = tick.no_prob_15m if tick.no_prob_15m is not None else tick.probability_15m
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


class Htc15mAdapter:
    """
    Single-ticker 15m HTC replay.

    Uses package ``floor_strike`` as the strike for this market ticker, rebuilds
    active_side / diffs from spot + asks (same geometry as live strike table),
    then ``evaluate_hourly_htc_strike_entry`` with ``gate_profile="full"``.
    Floor exit matches ATS stop-loss floor (opp ask > 1 - stop_loss_price).
    """

    name = "15m HTC"

    def would_enter(
        self,
        tick: CycleTick,
        pkg: CyclePackage,
        settings: Mapping[str, Any],
        *,
        already_in_position: bool,
    ) -> Optional[EntryEvent]:
        if already_in_position:
            return None

        min_time = int(settings.get("min_time") or 0)
        max_time = int(settings.get("max_time") or 10**9)
        ttc = int(tick.ttc_seconds)
        if ttc < min_time or ttc > max_time:
            return None

        floor = tick.floor_strike if tick.floor_strike is not None else pkg.floor_strike
        if floor is None or tick.spot is None:
            return None
        if tick.yes_ask is None or tick.no_ask is None:
            return None

        try:
            strike_f = float(floor)
            spot_f = float(tick.spot)
        except (TypeError, ValueError):
            return None

        # Prob for diff geometry: use YES-side 15m prob when available (live ladder).
        prob_yes = _side_prob(tick, "yes")
        if prob_yes is None:
            return None

        geo = money_line_diffs_and_active_side(
            strike_f,
            spot_f,
            prob_yes,
            tick.yes_ask,
            tick.no_ask,
        )
        if geo is None:
            return None
        yes_diff, no_diff, active_side = geo

        side_prob = _side_prob(tick, active_side)
        if side_prob is None:
            return None

        strike_row = {
            "strike": strike_f,
            "ticker": pkg.market_ticker,
            "probability": side_prob,
            "yes_ask_dollars": tick.yes_ask,
            "no_ask_dollars": tick.no_ask,
            "yes_diff": yes_diff,
            "no_diff": no_diff,
            "active_side": active_side,
            "volume": _volume_from_package(pkg),
        }
        spike = bool(settings.get("spike_alert_active", False))
        payload, reason = evaluate_hourly_htc_strike_entry(
            settings,
            strike_row,
            spike_alert_active=spike,
            gate_profile="full",
        )
        if payload is None:
            return None

        return EntryEvent(
            timestamp=tick.timestamp,
            side=normalize_trade_side(payload["side"]),
            ticket_ask=float(payload["buy_price"]),
            buy_price=float(payload["buy_price"]),
            probability=float(payload["probability"]),
            ttc_seconds=ttc,
            detail={
                "reason": "htc_gates_passed",
                "ticker": pkg.market_ticker,
                "strike": payload.get("strike"),
                "diff": payload.get("diff"),
                "active_side": active_side,
                "spot": tick.spot,
                "gate_skip": reason,
            },
        )

    def would_exit(
        self,
        tick: CycleTick,
        pkg: CyclePackage,
        settings: Mapping[str, Any],
        position: ReplayPosition,
        *,
        floor_confirm_count: int,
    ) -> tuple[Optional[ExitEvent], int]:
        if not settings.get("flip_sell_floor", True):
            return None, floor_confirm_count

        should, new_count, detail = evaluate_expiration_scalp_floor_exit(
            settings,
            position_side=position.side,
            yes_ask=tick.yes_ask,
            no_ask=tick.no_ask,
            confirm_ticks=int(settings.get("floor_confirm_ticks", 1) or 1),
            prior_confirm_count=floor_confirm_count,
        )
        if not should:
            return None, new_count

        su = normalize_trade_side(position.side)
        opp = tick.no_ask if su == "Y" else tick.yes_ask
        sell = (1.0 - float(opp)) if opp is not None else None
        win_loss = None
        if sell is not None and position.entry.buy_price is not None:
            win_loss = "W" if float(sell) > float(position.entry.buy_price) else "L"
        return (
            ExitEvent(
                timestamp=tick.timestamp,
                reason="stop_loss_floor",
                close_method="auto_stop_loss_floor",
                status="closed",
                sell_price=sell,
                market_result=pkg.market_result,
                win_loss=win_loss,
                detail={"msg": detail, "ttc_seconds": tick.ttc_seconds},
            ),
            new_count,
        )
