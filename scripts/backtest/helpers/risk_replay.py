"""
Replay loss prevention + dynamic position sizing (PBA multiplier, percent/contract sizing)
against historical closed trades. Aligns with ``trade_manager.update_monitor_win_streak``
cycle grouping (ticker prefix) and ``monitor_manager`` total_position math.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Callable, Mapping, Optional, Sequence

from scripts.backtest.helpers.hypothetical_trades import recompute_closed_trade_hypothetical
from scripts.backtest.helpers.monitor_context import is_cycle_based_strategy


def cycle_key_from_trade(row: Mapping[str, Any]) -> str:
    t = row.get("ticker")
    if t is not None:
        ts = str(t).strip()
        if ts and "-" in ts:
            return ts.rsplit("-", 1)[0]
    c = (row.get("contract") or "") or ""
    d = (row.get("date") or "") or ""
    return f"{c}|{d}"


def _effective_event_ts(row: Mapping[str, Any]) -> datetime:
    """Match regime evaluation: prefer parsable closed_at, else created_at."""
    ca = row.get("closed_at")
    if isinstance(ca, datetime):
        return ca
    if isinstance(ca, str) and ca.strip():
        s = ca.strip()
        if re.match(r"^\d{4}-\d{2}-\d{2}", s):
            try:
                if s.endswith("Z"):
                    s = s[:-1] + "+00:00"
                return datetime.fromisoformat(s)
            except ValueError:
                pass
    created = row.get("created_at")
    if isinstance(created, datetime):
        return created
    raise ValueError("trade row missing created_at")


def _regime_timedelta(regime_window: Optional[str]) -> timedelta:
    w = (regime_window or "30d").strip()
    mapping = {
        "30d": timedelta(days=30),
        "7d": timedelta(days=7),
        "1d": timedelta(days=1),
        "12h": timedelta(hours=12),
    }
    return mapping.get(w, timedelta(days=30))


def _filter_trades_regime_live(
    trades: Sequence[Mapping[str, Any]],
    *,
    regime_window: str,
    threshold: float = 0.0,
) -> list[dict[str, Any]]:
    """
    Keep trades that would be allowed under live regime: rolling SUM(ret_pct) in
    ``regime_window`` before this trade's event time is >= ``threshold``.
    Uses stored ret_pct on prior closed rows (same shape as monitor_manager).
    """
    ordered = sorted(trades, key=_effective_event_ts)
    kept: list[dict[str, Any]] = []
    window = _regime_timedelta(regime_window)
    prior: list[tuple[datetime, float]] = []
    for r in ordered:
        te = _effective_event_ts(r)
        cutoff = te - window
        prior = [(t, v) for t, v in prior if t >= cutoff]
        s = sum(v for _, v in prior)
        if s >= threshold:
            kept.append(dict(r))
        rp = r.get("ret_pct")
        try:
            rv = float(rp) if rp is not None else None
        except (TypeError, ValueError):
            rv = None
        if rv is not None:
            prior.append((te, rv))
    return kept


def _compute_intended_contracts(
    row: Mapping[str, Any],
    risk: Mapping[str, Any],
    *,
    throttle_one: bool,
    allotment_dollars_override: float | None = None,
) -> int:
    """Mirror monitor_manager.recalculate_monitor_total_positions (single monitor)."""
    if throttle_one:
        return 1
    mult_raw = row.get("multiplier")
    try:
        multiplier_value = float(mult_raw) if mult_raw is not None else 1.0
    except (TypeError, ValueError):
        multiplier_value = 1.0
    if multiplier_value == 0:
        return 1

    position_size = risk.get("position_size")
    position_type = (risk.get("position_type") or "contracts").strip().lower()
    pba = bool(risk.get("performance_based_allocation"))
    max_pct_cap = None
    if risk.get("current_max_pct_exposure") is not None:
        try:
            max_pct_cap = float(risk["current_max_pct_exposure"])
        except (TypeError, ValueError):
            max_pct_cap = None

    if position_type == "percent":
        if allotment_dollars_override is not None:
            allotment_dollars = float(allotment_dollars_override)
        else:
            bat = risk.get("bankroll_allotment_total")
            if bat is None:
                return 1
            try:
                allotment_dollars = float(bat) / 100.0
            except (TypeError, ValueError):
                return 1
        try:
            ps = int(position_size) if position_size is not None else 0
        except (TypeError, ValueError):
            ps = 0
        base_pct = ps / 100.0
        effective_pct = base_pct * multiplier_value
        if pba and max_pct_cap is not None and max_pct_cap > 0:
            effective_pct = min(effective_pct, max_pct_cap)
        new_total = int(round(allotment_dollars * effective_pct))
        return max(1, new_total)
    try:
        ps_c = int(position_size) if position_size is not None else 1
    except (TypeError, ValueError):
        ps_c = 1
    return max(1, int(round(ps_c * multiplier_value)))


@dataclass
class LPState:
    win_streak: int = 0
    lp_throttle: bool = False


def _apply_cycle_to_lp_state(
    state: LPState,
    *,
    has_loss: bool,
    win_count: int,
    cycle_based_streak: bool,
    threshold: int,
    toggle: bool,
) -> None:
    if not toggle:
        if has_loss:
            state.win_streak = 0
        else:
            state.win_streak += 1 if cycle_based_streak else win_count
        state.lp_throttle = False
        return
    if has_loss:
        state.win_streak = 0
        state.lp_throttle = True
        return
    inc = 1 if cycle_based_streak else win_count
    state.win_streak += inc
    state.lp_throttle = state.win_streak < threshold


def _cycle_has_loss_and_win_count(trades: Sequence[Mapping[str, Any]]) -> tuple[bool, int]:
    has_loss = False
    win_count = 0
    for t in trades:
        wl = (t.get("win_loss") or "").strip().upper()
        if wl == "L":
            has_loss = True
        elif wl == "W":
            win_count += 1
    return has_loss, win_count


def _ordered_cycles(
    trades: Sequence[Mapping[str, Any]],
) -> list[tuple[str, list[dict[str, Any]]]]:
    buckets: dict[str, list[dict[str, Any]]] = {}
    for r in trades:
        k = cycle_key_from_trade(r)
        buckets.setdefault(k, []).append(dict(r))
    for lst in buckets.values():
        lst.sort(key=lambda x: x.get("created_at") or datetime.min)
    items = []
    for k, lst in buckets.items():
        end_ts = max(x.get("created_at") or datetime.min for x in lst)
        items.append((k, lst, end_ts))
    items.sort(key=lambda x: x[2])
    return [(k, lst) for k, lst, _ in items]


def _trade_sort_key(row: Mapping[str, Any]) -> tuple[datetime, int]:
    ca = row.get("created_at")
    if not isinstance(ca, datetime):
        ca = datetime.min
    tid = row.get("id")
    try:
        tid_i = int(tid) if tid is not None else 0
    except (TypeError, ValueError):
        tid_i = 0
    return (ca, tid_i)


@dataclass
class RiskReplayResult:
    sum_hypo_ret_pct: float
    sum_hypo_ret_pct_base: float
    sum_hypo_pnl: float
    closed_trades_count: int
    skipped_non_closed: int
    final_bankroll_cents: int | None = None
    compound_start_cents: int | None = None


def _replay_loss_prevention_compound(
    rows: list[dict[str, Any]],
    risk: Mapping[str, Any],
    *,
    win_streak_threshold: int,
    compound_start_cents: int,
    strategy: str | None,
    cycle_based: bool,
    toggle: bool,
) -> RiskReplayResult:
    """
    Global ``created_at`` order: bankroll compounds after each closed trade; percent sizing
    uses current bankroll dollars as the allotment base. LP state updates when the last row
    (any status) of a cycle is processed, using closed/settled rows only for W/L.
    """
    buckets: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        k = cycle_key_from_trade(r)
        buckets.setdefault(k, []).append(r)

    last_by_cycle: dict[str, dict[str, Any]] = {}
    for k, lst in buckets.items():
        last_by_cycle[k] = max(lst, key=_trade_sort_key)

    global_order = sorted(rows, key=_trade_sort_key)
    position_type = (risk.get("position_type") or "contracts").strip().lower()
    state = LPState()
    sim_cents = int(compound_start_cents)

    sum_ret = 0.0
    sum_pnl = 0.0
    closed_n = 0
    skip_nc = 0

    for r in global_order:
        ck = cycle_key_from_trade(r)
        throttle = state.lp_throttle
        st = (r.get("status") or "").strip().lower()
        if st in ("closed", "settled"):
            entry_dollars = sim_cents / 100.0
            override = entry_dollars if position_type == "percent" else None
            pos = _compute_intended_contracts(
                r, risk, throttle_one=throttle, allotment_dollars_override=override
            )
            hypo = recompute_closed_trade_hypothetical(r, position=pos)
            if hypo:
                closed_n += 1
                pnl = float(hypo.get("hypo_pnl") or 0.0)
                sum_pnl += pnl
                if entry_dollars > 0:
                    sum_ret += 100.0 * pnl / entry_dollars
                sim_cents += int(round(pnl * 100))
                if sim_cents < 1:
                    sim_cents = 1
            else:
                skip_nc += 1
        else:
            skip_nc += 1

        last_r = last_by_cycle.get(ck)
        if last_r is not None and last_r.get("id") == r.get("id"):
            settled = [
                x
                for x in buckets[ck]
                if str(x.get("status") or "").strip().lower() in ("closed", "settled")
            ]
            if settled:
                has_loss, win_count = _cycle_has_loss_and_win_count(settled)
                _apply_cycle_to_lp_state(
                    state,
                    has_loss=has_loss,
                    win_count=win_count,
                    cycle_based_streak=cycle_based,
                    threshold=win_streak_threshold,
                    toggle=toggle,
                )

    return RiskReplayResult(
        sum_hypo_ret_pct=sum_ret,
        sum_hypo_ret_pct_base=0.0,
        sum_hypo_pnl=sum_pnl,
        closed_trades_count=closed_n,
        skipped_non_closed=skip_nc,
        final_bankroll_cents=sim_cents,
        compound_start_cents=compound_start_cents,
    )


def replay_loss_prevention_threshold(
    trades: Sequence[Mapping[str, Any]],
    risk: Mapping[str, Any],
    *,
    win_streak_threshold: int,
    apply_regime_filter: bool,
    compound_start_cents: int | None = None,
) -> RiskReplayResult:
    """
    Chronological cycle replay: for each trade, hypothetical position from sizing + LP throttle
    **at cycle entry** (state after all prior completed cycles).

    When ``compound_start_cents`` is set, uses global time order, compounds bankroll after each
    closed trade, sizes percent strategies from the running balance, and sets ``sum_hypo_ret_pct``
    to the sum of per-trade ``100 * pnl / entry_balance`` (``sum_hypo_ret_pct_base`` is 0).
    """
    strategy = risk.get("strategy")
    cycle_based = is_cycle_based_strategy(strategy)
    toggle = bool(risk.get("loss_prevention_toggle", True))

    rows = [dict(x) for x in trades]
    if apply_regime_filter and bool(risk.get("regime_monitor_enabled")):
        rw = str(risk.get("regime_window") or "30d").strip()
        rows = _filter_trades_regime_live(rows, regime_window=rw, threshold=0.0)

    if compound_start_cents is not None:
        if compound_start_cents < 1:
            raise ValueError("compound_start_cents must be >= 1 (at least one cent)")
        return _replay_loss_prevention_compound(
            rows,
            risk,
            win_streak_threshold=win_streak_threshold,
            compound_start_cents=compound_start_cents,
            strategy=strategy,
            cycle_based=cycle_based,
            toggle=toggle,
        )

    cycles = _ordered_cycles(rows)
    state = LPState()

    sum_ret = 0.0
    sum_ret_b = 0.0
    sum_pnl = 0.0
    closed_n = 0
    skip_nc = 0

    for _ck, cycle_trades in cycles:
        throttle = state.lp_throttle
        settled = [
            r
            for r in cycle_trades
            if str(r.get("status") or "").strip().lower() in ("closed", "settled")
        ]
        for r in cycle_trades:
            st = (r.get("status") or "").strip().lower()
            if st not in ("closed", "settled"):
                skip_nc += 1
                continue
            pos = _compute_intended_contracts(
                r, risk, throttle_one=throttle, allotment_dollars_override=None
            )
            hypo = recompute_closed_trade_hypothetical(r, position=pos)
            if not hypo:
                skip_nc += 1
                continue
            closed_n += 1
            h = hypo.get("hypo_ret_pct")
            hb = hypo.get("hypo_ret_pct_base")
            if h is not None:
                sum_ret += float(h)
            if hb is not None:
                sum_ret_b += float(hb)
            sum_pnl += float(hypo.get("hypo_pnl") or 0.0)

        if not settled:
            continue
        has_loss, win_count = _cycle_has_loss_and_win_count(settled)
        _apply_cycle_to_lp_state(
            state,
            has_loss=has_loss,
            win_count=win_count,
            cycle_based_streak=cycle_based,
            threshold=win_streak_threshold,
            toggle=toggle,
        )

    return RiskReplayResult(
        sum_hypo_ret_pct=sum_ret,
        sum_hypo_ret_pct_base=sum_ret_b,
        sum_hypo_pnl=sum_pnl,
        closed_trades_count=closed_n,
        skipped_non_closed=skip_nc,
    )


def sweep_loss_prevention_thresholds(
    trades: Sequence[Mapping[str, Any]],
    risk: Mapping[str, Any],
    *,
    lo: int,
    hi: int,
    apply_regime_filter: bool,
    objective: Callable[[RiskReplayResult], float],
    compound_start_cents: int | None = None,
) -> list[tuple[int, RiskReplayResult, float]]:
    out: list[tuple[int, RiskReplayResult, float]] = []
    for th in range(lo, hi + 1):
        res = replay_loss_prevention_threshold(
            trades,
            risk,
            win_streak_threshold=th,
            apply_regime_filter=apply_regime_filter,
            compound_start_cents=compound_start_cents,
        )
        out.append((th, res, objective(res)))
    return out
