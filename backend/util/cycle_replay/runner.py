"""
Cycle-package replay runner.

Strategy-agnostic: loads a sealed package, reconstructs 1 Hz ticks, and drives a
pluggable strategy adapter. First goal: recreate live entry/exit decisions without
calling AES/ATS HTTP.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

from backend.core.cycle_package import CyclePackage, CycleTick, load_cycle_package
from backend.util.cycle_replay.fills import apply_paper_entry_fill
from backend.util.cycle_replay.strategies import get_strategy_adapter
from backend.util.cycle_replay.strategies.base import StrategyAdapter
from backend.util.cycle_replay.trade_shape import normalize_trade_side, side_to_yes_no
from backend.util.cycle_replay.types import EntryEvent, ExitEvent, ReplayPosition


@dataclass
class ReplayResult:
    package_path: str
    market_ticker: str
    strategy: str
    settings: Dict[str, Any]
    ticks_scanned: int
    entries: List[EntryEvent] = field(default_factory=list)
    rejected_entries: List[Dict[str, Any]] = field(default_factory=list)
    positions: List[ReplayPosition] = field(default_factory=list)
    first_entry: Optional[EntryEvent] = None
    market_result: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        def _entry(e: EntryEvent) -> Dict[str, Any]:
            return {
                "timestamp": e.timestamp.isoformat().replace("+00:00", "Z"),
                "side": normalize_trade_side(e.side),
                "ticket_ask": e.ticket_ask,
                "initial_price": e.ticket_ask,
                "buy_price": e.buy_price,
                "position": e.filled,
                "fees": e.fees,
                "probability": e.probability,
                "ttc_seconds": e.ttc_seconds,
                "detail": e.detail,
            }

        def _exit(x: Optional[ExitEvent]) -> Optional[Dict[str, Any]]:
            if x is None:
                return None
            return {
                "timestamp": x.timestamp.isoformat().replace("+00:00", "Z"),
                "reason": x.reason,
                "status": x.status,
                "close_method": x.close_method or x.reason,
                "sell_price": x.sell_price,
                "market_result": x.market_result,
                "win_loss": x.win_loss,
                "detail": x.detail,
            }

        return {
            "package_path": self.package_path,
            "market_ticker": self.market_ticker,
            "strategy": self.strategy,
            "settings": self.settings,
            "ticks_scanned": self.ticks_scanned,
            "market_result": self.market_result,
            "first_entry": _entry(self.first_entry) if self.first_entry else None,
            "entries": [_entry(e) for e in self.entries],
            "rejected_entries": self.rejected_entries,
            "positions": [
                {
                    "side": p.side,
                    "entry": _entry(p.entry),
                    "exit": _exit(p.exit),
                }
                for p in self.positions
            ],
        }


def run_cycle_replay(
    package: Path | str | CyclePackage,
    settings: Mapping[str, Any],
    *,
    strategy: str | StrategyAdapter = "Expiration Scalp",
    allow_reentry: bool = False,
    settle_at_close: bool = True,
) -> ReplayResult:
    """
    Replay one package against one strategy + settings snapshot.

    - Enters at most once unless ``allow_reentry``.
    - On entry intent, walks the reconstructed book like paper IOC/market fill.
    - Floor exits via strategy adapter.
    - If still open at cycle close and ``settle_at_close``, exits as ``expired``
      with sell_price 1.0 (win) / 0.0 (loss) from package ``market_result`` when
      available; otherwise ``still_open``.
    """
    pkg = package if isinstance(package, CyclePackage) else load_cycle_package(package)
    adapter: StrategyAdapter = (
        strategy if not isinstance(strategy, str) else get_strategy_adapter(strategy)
    )

    settings_d = dict(settings)
    result = ReplayResult(
        package_path=str(pkg.path),
        market_ticker=pkg.market_ticker,
        strategy=adapter.name,
        settings=settings_d,
        ticks_scanned=0,
        market_result=pkg.market_result,
    )

    open_pos: Optional[ReplayPosition] = None
    floor_confirm = 0
    close_sec = pkg.close_utc.replace(microsecond=0)

    for tick in _iter_ticks(pkg):
        result.ticks_scanned += 1

        if open_pos is not None:
            exit_ev, floor_confirm = adapter.would_exit(
                tick,
                pkg,
                settings_d,
                open_pos,
                floor_confirm_count=floor_confirm,
            )
            if exit_ev is not None:
                open_pos.exit = exit_ev
                result.positions.append(open_pos)
                open_pos = None
                floor_confirm = 0
                if not allow_reentry:
                    # Keep scanning only for exit completeness; no new entries.
                    continue

        if open_pos is None and (allow_reentry or not result.entries):
            intent = adapter.would_enter(
                tick,
                pkg,
                settings_d,
                already_in_position=False,
            )
            if intent is not None:
                filled_entry, reject = apply_paper_entry_fill(intent, tick, settings_d)
                if filled_entry is None:
                    result.rejected_entries.append(
                        {
                            "timestamp": intent.timestamp.isoformat().replace("+00:00", "Z"),
                            "side": intent.side,
                            "ticket_ask": intent.ticket_ask or intent.buy_price,
                            "reason": reject,
                        }
                    )
                else:
                    result.entries.append(filled_entry)
                    if result.first_entry is None:
                        result.first_entry = filled_entry
                    open_pos = ReplayPosition(
                        side=normalize_trade_side(filled_entry.side),
                        entry=filled_entry,
                    )
                    floor_confirm = 0

        # Natural close on the closing second (or last tick at/after close)
        if open_pos is not None and settle_at_close and tick.timestamp >= close_sec:
            open_pos.exit = _settlement_exit_for_position(tick, pkg, open_pos.side)
            result.positions.append(open_pos)
            open_pos = None
            floor_confirm = 0
            if not allow_reentry:
                break

    if open_pos is not None:
        # Past end of tick stream without hitting close settle
        if settle_at_close:
            last = CycleTick(
                timestamp=close_sec,
                ttc_seconds=0,
                spot=None,
                avg_60s=None,
                yes_ask=None,
                no_ask=None,
                probability_15m=None,
                yes_prob_15m=None,
                no_prob_15m=None,
                fair_price=None,
                floor_strike=pkg.floor_strike,
            )
            open_pos.exit = _settlement_exit_for_position(last, pkg, open_pos.side)
        else:
            open_pos.exit = ExitEvent(
                timestamp=close_sec,
                reason="still_open",
                sell_price=None,
            )
        result.positions.append(open_pos)

    return result


def _iter_ticks(pkg: CyclePackage):
    from backend.core.cycle_package import iter_cycle_ticks

    return iter_cycle_ticks(pkg)


def _settlement_exit_for_position(tick: CycleTick, pkg: CyclePackage, side: str) -> ExitEvent:
    mr = (pkg.market_result or "").strip().lower()
    su = side_to_yes_no(side)
    sell: Optional[float] = None
    win_loss: Optional[str] = None
    if mr in ("yes", "no"):
        sell = 1.0 if mr == su else 0.0
        win_loss = "W" if sell == 1.0 else "L"
    return ExitEvent(
        timestamp=tick.timestamp,
        reason="expired",
        close_method="expired",
        status="closed",
        sell_price=sell,
        market_result=mr or None,
        win_loss=win_loss,
        detail={"market_result": mr or None},
    )
