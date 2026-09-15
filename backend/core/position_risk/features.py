"""Shadow liquidation features from L2 (no EXIT_INTENT). Tape always UNKNOWN in Stage 1."""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

from backend.core.cycle_recon.measurements import complementary_asks, empty_whole_cent_levels
from backend.core.orderbook_strike_prices import project_taker_buy_from_levels
from backend.core.position_risk.book_health import TapeState
from backend.core.position_risk.liquidation import walk_sell_into_bids


@dataclass
class ShadowFeatures:
    ticker: str
    side: str
    size: float
    ts_ms: Optional[int]
    seq: Optional[int]
    eval_mono_ms: float
    liquidation_vwap: Optional[float]
    close_cost_vwap: Optional[float]
    fill_coverage: Optional[float]
    available: Optional[float]
    best_executable: Optional[float]
    worst_swept_level: Optional[float]
    depth_above_floor: Optional[float]
    floor_owned: Optional[float]
    empty_cent_bands: Optional[int]
    cliff_gap_cents: Optional[float]
    quote_velocity: Optional[float]
    depth_deficit: Optional[float]
    tape_state: str = TapeState.UNKNOWN.value
    ok: bool = False
    reason: str = ""
    extras: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _opt_float(v: Any) -> Optional[float]:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _owned_bids(yes: Dict[str, str], no: Dict[str, str], side: str) -> List[Tuple[float, float]]:
    """Levels for depth/cliff analysis — same path as liquidation walk."""
    from backend.core.position_risk.liquidation import executable_bid_levels

    return executable_bid_levels(yes, no, side)


def depth_above_owned_floor(
    yes: Dict[str, str],
    no: Dict[str, str],
    side: str,
    floor_owned: Optional[float],
) -> Optional[float]:
    if floor_owned is None:
        return None
    try:
        fl = float(floor_owned)
    except (TypeError, ValueError):
        return None
    total = 0.0
    for px, q in _owned_bids(yes, no, side):
        if px + 1e-12 >= fl:
            total += q
    return total


def cliff_gap_from_best(levels: Sequence[Tuple[float, float]]) -> Optional[float]:
    if len(levels) < 2:
        return None
    return abs(float(levels[1][0]) - float(levels[0][0]))


def compute_shadow_features(
    *,
    ticker: str,
    side: str,
    size: float,
    yes: Dict[str, str],
    no: Dict[str, str],
    floor_owned: Optional[float] = None,
    seq: Optional[int] = None,
    ts_ms: Optional[int] = None,
    prev_best: Optional[float] = None,
    prev_ts_ms: Optional[int] = None,
    prev_depth_above_floor: Optional[float] = None,
) -> ShadowFeatures:
    t0 = time.perf_counter()
    size_f = float(size)
    liq = walk_sell_into_bids(yes, no, side, size_f)
    close_proj = project_taker_buy_from_levels(yes, no, side, size_f, limit_price=None)
    asks = complementary_asks(yes, no, side)
    bids = _owned_bids(yes, no, side)
    best_exec = liq.get("best")
    cliff = cliff_gap_from_best(bids) if bids else None
    empty = empty_whole_cent_levels([(1.0 - px, sz) for px, sz in bids], bands=15) if bids else None
    depth_af = depth_above_owned_floor(yes, no, side, floor_owned)

    velocity = None
    if (
        best_exec is not None
        and prev_best is not None
        and ts_ms is not None
        and prev_ts_ms is not None
        and ts_ms > prev_ts_ms
    ):
        dt = (ts_ms - prev_ts_ms) / 1000.0
        if dt > 0:
            velocity = (float(best_exec) - float(prev_best)) / dt

    depth_def = None
    if depth_af is not None and prev_depth_above_floor is not None:
        depth_def = float(prev_depth_above_floor) - float(depth_af)

    ok = bool(liq.get("ok")) or bool(close_proj.get("ok"))
    reason = "ok" if ok else (close_proj.get("reason") or "insufficient_depth")
    eval_ms = (time.perf_counter() - t0) * 1000.0
    return ShadowFeatures(
        ticker=ticker,
        side=side,
        size=size_f,
        ts_ms=ts_ms,
        seq=seq,
        eval_mono_ms=eval_ms,
        liquidation_vwap=_opt_float(liq.get("vwap")),
        close_cost_vwap=_opt_float(close_proj.get("initial_proj_price")),
        fill_coverage=_opt_float(liq.get("coverage")),
        available=_opt_float(liq.get("available")),
        best_executable=_opt_float(best_exec),
        worst_swept_level=_opt_float(liq.get("worst")),
        depth_above_floor=_opt_float(depth_af),
        floor_owned=_opt_float(floor_owned),
        empty_cent_bands=int(empty) if empty is not None else None,
        cliff_gap_cents=(cliff * 100.0) if cliff is not None else None,
        quote_velocity=velocity,
        depth_deficit=depth_def,
        tape_state=TapeState.UNKNOWN.value,
        ok=ok,
        reason=str(reason),
        extras={
            "close_filled": close_proj.get("filled_fp"),
            "close_ok": close_proj.get("ok"),
            "ask_best": asks[0][0] if asks else None,
        },
    )
