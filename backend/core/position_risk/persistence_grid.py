"""Persistence candidate grid analysis (not authority)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

PERSISTENCE_MS_GRID = (0, 50, 100, 250, 500, 1000)


@dataclass
class BreachEvent:
    t_ms: int
    book_gen: int
    liquidation_vwap: float


def first_breach_times(
    series: Sequence[Tuple[int, Optional[float]]],
    *,
    threshold: float,
) -> Optional[BreachEvent]:
    """
    series: (t_ms, liquidation_vwap) sorted by time.
    Breach when vwap < threshold (owned proceeds fell).
    """
    gen = 0
    last_vwap = None
    for t_ms, vwap in series:
        if vwap is None:
            continue
        if last_vwap is None or abs(float(vwap) - float(last_vwap)) > 1e-9:
            gen += 1
            last_vwap = vwap
        if float(vwap) <= float(threshold) + 1e-12:
            return BreachEvent(t_ms=int(t_ms), book_gen=gen, liquidation_vwap=float(vwap))
    return None


def persistence_holds(
    series: Sequence[Tuple[int, Optional[float]]],
    *,
    threshold: float,
    persist_ms: int,
    min_book_gens: int,
) -> Optional[Dict[str, Any]]:
    """
    After first breach, require wall-clock persist_ms AND min distinct book gens
    while still below threshold. Returns fire time dict or None.
    """
    breach = first_breach_times(series, threshold=threshold)
    if breach is None:
        return None
    start_t = breach.t_ms
    gens = set()
    last_v = None
    gen_counter = 0
    for t_ms, vwap in series:
        if t_ms < start_t:
            continue
        if vwap is None:
            continue
        if float(vwap) > float(threshold) + 1e-12:
            return None  # recovered before persistence satisfied
        if last_v is None or abs(float(vwap) - float(last_v)) > 1e-9:
            gen_counter += 1
            last_v = vwap
            gens.add(gen_counter)
        elapsed = t_ms - start_t
        if elapsed >= persist_ms and len(gens) >= max(1, min_book_gens):
            return {
                "threshold": threshold,
                "persist_ms": persist_ms,
                "min_book_gens": min_book_gens,
                "first_breach_ms": start_t,
                "fire_ms": t_ms,
                "book_gens_below": len(gens),
                "vwap_at_fire": float(vwap),
            }
    return None


def run_persistence_grid(
    series: Sequence[Tuple[int, Optional[float]]],
    *,
    thresholds: Sequence[float] = (0.95, 0.90, 0.88),
    persist_grid: Sequence[int] = PERSISTENCE_MS_GRID,
    min_book_gens_grid: Sequence[int] = (1, 2, 3),
) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for thr in thresholds:
        first = first_breach_times(series, threshold=thr)
        out.append(
            {
                "kind": "first_breach",
                "threshold": thr,
                "event": None
                if first is None
                else {
                    "t_ms": first.t_ms,
                    "book_gen": first.book_gen,
                    "vwap": first.liquidation_vwap,
                },
            }
        )
        for pms in persist_grid:
            for mg in min_book_gens_grid:
                fired = persistence_holds(
                    series, threshold=thr, persist_ms=pms, min_book_gens=mg
                )
                out.append(
                    {
                        "kind": "persistence_candidate",
                        "threshold": thr,
                        "persist_ms": pms,
                        "min_book_gens": mg,
                        "result": fired,
                    }
                )
    return out
