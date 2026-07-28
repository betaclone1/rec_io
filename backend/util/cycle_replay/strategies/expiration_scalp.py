from __future__ import annotations

from typing import Any, Mapping, Optional

from backend.core.cycle_package import CyclePackage, CycleTick
from backend.util.auto_entry_expiration_scalp_gates import (
    evaluate_expiration_scalp_entry,
    evaluate_expiration_scalp_floor_exit,
    side_aware_probability_15m,
)
from backend.util.cycle_replay.trade_shape import normalize_trade_side
from backend.util.cycle_replay.types import EntryEvent, ExitEvent, ReplayPosition


class ExpirationScalpAdapter:
    """
    Single-ticker Expiration Scalp replay.

    Scans yes then no (same order as live AES). First passing side wins for that tick.
    Natural expiry is decided by the runner when the package clock hits close.
    """

    name = "Expiration Scalp"

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

        row = {
            "probability_15m": tick.probability_15m,
            "yes_prob_15m": tick.yes_prob_15m,
            "no_prob_15m": tick.no_prob_15m,
        }
        for side, ask in (("yes", tick.yes_ask), ("no", tick.no_ask)):
            prob = side_aware_probability_15m(row, side)
            passed, reason = evaluate_expiration_scalp_entry(
                settings,
                ttc_seconds=tick.ttc_seconds,
                side=side,
                ask_dollars=ask,
                probability=prob,
            )
            if passed is None:
                continue
            return EntryEvent(
                timestamp=tick.timestamp,
                side=normalize_trade_side(passed["side"]),
                ticket_ask=float(passed["buy_price"]),
                buy_price=float(passed["buy_price"]),  # replaced by runner fill walk
                probability=float(passed["probability"]),
                ttc_seconds=int(passed["ttc_seconds"]),
                detail={
                    "reason": "entry_gates_passed",
                    "ticker": pkg.market_ticker,
                    "reject_skipped": reason,
                    "spot": tick.spot,
                    "yes_ask": tick.yes_ask,
                    "no_ask": tick.no_ask,
                },
            )
        return None

    def would_exit(
        self,
        tick: CycleTick,
        pkg: CyclePackage,
        settings: Mapping[str, Any],
        position: ReplayPosition,
        *,
        floor_confirm_count: int,
    ) -> tuple[Optional[ExitEvent], int]:
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
        # Sell price = 1 - opp_ask (same conversion ATS uses from current_close_price)
        su = normalize_trade_side(position.side)
        opp = tick.no_ask if su == "Y" else tick.yes_ask
        sell = (1.0 - float(opp)) if opp is not None else None
        return (
            ExitEvent(
                timestamp=tick.timestamp,
                reason="stop_loss_floor",
                close_method="stop_loss_floor",
                status="closed",
                sell_price=sell,
                market_result=pkg.market_result,
                win_loss=None,
                detail={"msg": detail, "ttc_seconds": tick.ttc_seconds},
            ),
            new_count,
        )
