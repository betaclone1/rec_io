#!/usr/bin/env python3
"""
Minimal backtest: count trades per monitor over a time range and show W/L rate.

Loads ``monitor_list_<user>`` for each ``mon_<user>_<id>`` label and prints key settings
(strategy, symbol, etc.). Strategy drives how wins/losses are counted:

- **HTC-style** (default): each trade is one outcome; uses ``win_loss`` on each row.
- **Momentum Contain / Momentum Breakout**: cycles are ``contract`` + ``date`` (same as
  ``trade_manager`` cycle metrics). Only ``closed``/``settled`` rows contribute to cycle
  PnL; cycle **W** if ``SUM(pnl) > 0``, **L** if ``< 0**, flat if ``0``. Trade count is
  still all rows in the time window (any status).

**paper_trade:** default includes live and paper. Use ``--paper live`` or ``--paper paper`` to restrict.

**prob:** ``--min-prob`` / ``--max-prob`` use the DB scale (typically **0–100**, e.g. ``96`` for 96%%).

**TTC (minutes):** time from ``created_at`` to the **next** boundary in ``--ttc-timezone``:
hourly grid for most monitors; **15m** grid when the monitor's ``strategy`` contains ``15m``
(e.g. ``15m HTC``). Use ``--min-ttc-minutes`` / ``--max-ttc-minutes`` to filter.

**More columns:** repeatable ``--trade-filter column:op:value`` (allowlisted columns; see
``scripts/backtest/helpers/trade_filters.py``).

**PnL / returns:** ``--metrics`` (default ``ret_pct``; comma-separated or ``all`` for
``ret_pct``, ``ret_pct_base``, ``pnl``) and ``--agg`` (default ``sum``; comma-separated
``sum``, ``mean``, ``min``, ``max``, ``count``, ``stdev``). Per-trade basis: stats over
filtered trade rows. Per-cycle basis: stats over **cycles** (one value per contract+date:
sums of pnl / ret_pct / ret_pct_base within the cycle).

**Hypothetical sizing:** ``--hypothetical-position N`` recomputes **taker fees** (same formula
as ``trade_manager.estimate_kalshi_taker_fee``) and **PnL / ret_pct / ret_pct_base** per
**closed/settled** trade at fixed position ``N``. TTC filters move to **Python** (SQL TTC
omitted). Optional ``--hypo-ttc-under-minutes M`` prints an extra **sum hypo_pnl** for
trades whose open-time TTC (to next boundary; 15m vs hourly from monitor strategy) is **strictly < M**.

**Max TTC sweep (hypothetical):** ``--max-ttc-sweep HIGH:LOW`` (minutes, may be fractional) runs
once per ceiling from the higher bound down to the lower (inclusive). Step size defaults to
**60 seconds**; set ``--max-ttc-sweep-step-seconds`` to any value **≥ 1** (e.g. ``1`` for
per-second ceilings). One DB fetch per monitor; ceilings applied in Python. Mutually exclusive
with ``--max-ttc-minutes``. Very fine steps over a wide range hit a step-count cap (error with hint).

**Optimal TTC window (hypothetical):** ``--optimize-ttc-window`` searches **(MIN_TTC, MAX_TTC)**
bands where open-time TTC (minutes to the next 15m or hourly boundary) must satisfy
**MIN_TTC ≤ TTC ≤ MAX_TTC**. **MIN_TTC** (≥) is the **late-entry floor**; **MAX_TTC** (≤) is the
**early-entry cap** (higher TTC = more minutes left = earlier in the bar). Default objective is
**sum_ret_pct** = sum of hypothetical ``ret_pct`` over included closed trades (**total** return
contribution in %-points); use ``mean_ret_pct`` for per-trade average. Requires
``--hypothetical-position``. Grids: ``--optimize-ttc-min-range`` / ``--optimize-ttc-max-range``
(``LO:HI`` minutes) and ``--optimize-ttc-step-seconds``.

Uses ``created_at`` (timestamptz) for the window. Default: exclude ``test_filter=TRUE``.

DB: ``scripts/backtest/helpers/db.py`` (SSH prod default, etc.).

**Initiative (scope, supervisor parity, minutes vs seconds, UI roadmap):** ``docs/BACKTESTING.md``.

Example:
  python3 scripts/backtest/simple_backtest.py \\
    --monitors mon_0001_10002 \\
    --start 2026-01-01T00:00:00-05:00 \\
    --end 2027-01-01T00:00:00-05:00 \\
    --min-prob 96 --paper live

  python3 scripts/backtest/simple_backtest.py \\
    --monitors mon_0001_10002 \\
    --start 2026-01-01T00:00:00-05:00 \\
    --end 2027-01-01T00:00:00-05:00 \\
    --min-prob 97 --trade-filter momentum_percentile:gte:50

  python3 scripts/backtest/simple_backtest.py \\
    --monitors mon_0001_10026 \\
    --start 2026-03-01T00:00:00-05:00 \\
    --end 2026-04-01T00:00:00-05:00 \\
    --hypothetical-position 1500 --max-ttc-sweep 15:2 \\
    --max-ttc-sweep-step-seconds 60 \\
    --metrics pnl --agg sum
"""

from __future__ import annotations

import argparse
import os
import statistics
import sys
from datetime import datetime
from typing import Any, Sequence

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from scripts.backtest.helpers.constants import TRADES_TABLE
from scripts.backtest.helpers.db import get_connection
from scripts.backtest.helpers.filters import exclude_test_filter_sql
from scripts.backtest.helpers.monitor_context import (
    fetch_monitor_settings,
    format_monitor_settings_brief,
    is_cycle_based_strategy,
    parse_monitor_token,
)
from scripts.backtest.helpers.trade_filters import (
    TradeWhereParts,
    build_trade_where_parts,
    format_filters_for_display,
    strategy_implies_15m_ttc_grid,
)
from scripts.backtest.helpers.aggregates import (
    build_cycle_financial_select,
    build_trade_financial_select,
    financial_keys,
    format_financial_lines,
    parse_aggs_list,
    parse_metrics_list,
)
from scripts.backtest.helpers.hypothetical_trades import (
    open_to_next_boundary_minutes,
    recompute_closed_trade_hypothetical,
)


def _parse_instant(s: str) -> datetime:
    """Parse ISO-8601; require timezone-aware input for clarity against prod timestamptz."""
    s = s.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        raise argparse.ArgumentTypeError(
            f"Datetime must include a timezone offset (e.g. ...-05:00 or Z): {s!r}"
        )
    return dt


def _parse_monitors(s: str) -> list[str]:
    parts = [p.strip() for p in s.split(",")]
    out = [p for p in parts if p]
    if not out:
        raise argparse.ArgumentTypeError("Provide at least one monitor name")
    return out


_MAX_TTC_SWEEP_STEPS_CAP = 25_000
_OPTIMIZE_TTC_PAIR_CAP = 100_000


def _parse_max_ttc_sweep(s: str) -> tuple[float, float]:
    """
    ``HIGH:LOW`` inclusive bounds in **minutes** (float allowed). Run from the larger bound
    down to the smaller. Step size is ``--max-ttc-sweep-step-seconds`` (default 60).
    """
    parts = s.strip().split(":")
    if len(parts) != 2:
        raise argparse.ArgumentTypeError(
            f"Expected HIGH:LOW for --max-ttc-sweep (e.g. 15:2 or 10.5:2); got {s!r}"
        )
    try:
        a = float(parts[0].strip())
        b = float(parts[1].strip())
    except ValueError as e:
        raise argparse.ArgumentTypeError(f"Invalid max TTC sweep bounds in {s!r}") from e
    if a < 0 or b < 0:
        raise argparse.ArgumentTypeError("max TTC sweep bounds must be non-negative")
    return (a, b)


def _parse_grid_step_seconds(s: str) -> float:
    x = float(s.strip())
    if x < 1.0:
        raise argparse.ArgumentTypeError(
            "grid step seconds must be >= 1 (finest supported step is one second)"
        )
    return x


def _max_ttc_sweep_ceiling_minutes(
    hi_min: float,
    lo_min: float,
    step_seconds: float,
) -> list[float]:
    """
    Ceilings in **minutes**, descending from ``max(hi, lo)`` to ``min(hi, lo)`` inclusive,
    stepping down by ``step_seconds`` each iteration.
    """
    if step_seconds < 1.0:
        raise ValueError(
            "max TTC sweep step must be >= 1 second; sub-second steps are not supported"
        )
    hi = max(hi_min, lo_min)
    lo = min(hi_min, lo_min)
    hi_sec = hi * 60.0
    lo_sec = lo * 60.0
    est = int((hi_sec - lo_sec) / step_seconds) + 3
    if est > _MAX_TTC_SWEEP_STEPS_CAP:
        raise ValueError(
            f"max TTC sweep would need about {est} steps (cap {_MAX_TTC_SWEEP_STEPS_CAP}); "
            "increase --max-ttc-sweep-step-seconds or narrow HIGH:LOW"
        )
    out: list[float] = []
    s = hi_sec
    while s >= lo_sec - 1e-9:
        out.append(s / 60.0)
        if len(out) > _MAX_TTC_SWEEP_STEPS_CAP:
            raise ValueError(
                f"max TTC sweep exceeded {_MAX_TTC_SWEEP_STEPS_CAP} steps; "
                "increase step or narrow HIGH:LOW"
            )
        s -= step_seconds
    return out


def _fmt_sweep_ceiling_minutes(v: float) -> str:
    if abs(v - round(v)) < 1e-5:
        return str(int(round(v)))
    t = f"{v:.4f}".rstrip("0").rstrip(".")
    return t


def _text_table(
    headers: Sequence[str],
    rows: Sequence[Sequence[str]],
    *,
    aligns: Sequence[str],
    footers: Sequence[Sequence[str]] | None = None,
    indent: str = "",
) -> str:
    """
    Human-readable fixed-width table: header, rule, body rows, optional footer block
    (another rule then footer rows). ``aligns`` is ``l`` or ``r`` per column.
    """
    if len(headers) != len(aligns):
        raise ValueError("headers and aligns must have the same length")
    n = len(headers)
    footers = footers or []
    str_rows = [[str(c) for c in row] for row in rows]
    str_foot = [[str(c) for c in row] for row in footers]
    for row in str_rows + str_foot:
        if len(row) != n:
            raise ValueError("table row width does not match headers")
    widths = [len(str(h)) for h in headers]
    for row in str_rows + str_foot:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(cell))

    def pad(i: int, cell: str) -> str:
        w = widths[i]
        if aligns[i] == "r":
            return cell.rjust(w)
        return cell.ljust(w)

    def line(cells: Sequence[str]) -> str:
        return indent + " | ".join(pad(i, cells[i]) for i in range(n))

    sep = indent + "-+-".join("-" * widths[i] for i in range(n))
    out = [line([str(h) for h in headers]), sep]
    for row in str_rows:
        out.append(line(row))
    if str_foot:
        out.append(sep)
        for row in str_foot:
            out.append(line(row))
    return "\n".join(out)


def _financial_kv_table(
    st_sub: dict[str, Any],
    metrics: list[str],
    aggs: list[str],
    *,
    indent: str = "",
) -> str:
    body: list[list[str]] = []
    for ln in format_financial_lines(st_sub, metrics, aggs):
        t = ln.strip()
        if ": " not in t:
            continue
        key, val = t.split(": ", 1)
        body.append([key, val])
    if not body:
        return ""
    return _text_table(["metric", "value"], body, aligns=["l", "r"], indent=indent)


def _norm_range_endpoints(a: float, b: float) -> tuple[float, float]:
    return (min(a, b), max(a, b))


def _minute_grid_ascending(lo_m: float, hi_m: float, step_seconds: float) -> list[float]:
    """Inclusive minute values from ``lo_m`` to ``hi_m`` (order-insensitive), stepping by seconds."""
    if step_seconds < 1.0:
        raise ValueError("grid step must be >= 1 second")
    lo, hi = _norm_range_endpoints(lo_m, hi_m)
    lo_s, hi_s = lo * 60.0, hi * 60.0
    out: list[float] = []
    s = lo_s
    while s <= hi_s + 1e-9:
        out.append(s / 60.0)
        if len(out) > _MAX_TTC_SWEEP_STEPS_CAP:
            raise ValueError(
                f"optimize TTC axis grid exceeded {_MAX_TTC_SWEEP_STEPS_CAP} points; "
                "increase --optimize-ttc-step-seconds or narrow ranges"
            )
        s += step_seconds
    return out


def _optimize_objective_display_name(objective: str) -> str:
    labels = {
        "sum_ret_pct": "sum_ret_pct (total hypo % over closed trades in window)",
        "mean_ret_pct": "mean_ret_pct (average hypo % per closed trade)",
        "sum_ret_pct_base": "sum_ret_pct_base (total, mtb base)",
        "mean_ret_pct_base": "mean_ret_pct_base (average, mtb base)",
    }
    return labels.get(objective, objective)


def _optimize_ttc_objective_value(
    st: dict[str, Any],
    objective: str,
) -> float | None:
    rp = st["ret_pcts"]
    rb = st["ret_bases"]
    if objective == "mean_ret_pct":
        return float(sum(rp) / len(rp)) if rp else None
    if objective == "sum_ret_pct":
        return float(sum(rp)) if rp else None
    if objective == "mean_ret_pct_base":
        return float(sum(rb) / len(rb)) if rb else None
    if objective == "sum_ret_pct_base":
        return float(sum(rb)) if rb else None
    raise ValueError(f"unknown objective {objective!r}")


def _grid_search_hypothetical_ttc_window(
    enriched: list[dict[str, Any]],
    *,
    min_range: tuple[float, float],
    max_range: tuple[float, float],
    step_seconds: float,
    objective: str,
    min_closed_trades: int,
) -> list[dict[str, Any]]:
    min_grid = _minute_grid_ascending(min_range[0], min_range[1], step_seconds)
    max_grid = _minute_grid_ascending(max_range[0], max_range[1], step_seconds)
    pair_count = sum(1 for mn in min_grid for mx in max_grid if mn <= mx)
    if pair_count > _OPTIMIZE_TTC_PAIR_CAP:
        raise ValueError(
            f"optimize TTC grid would evaluate {pair_count} (min,max) pairs "
            f"(cap {_OPTIMIZE_TTC_PAIR_CAP}); widen --optimize-ttc-step-seconds or shrink ranges"
        )
    results: list[dict[str, Any]] = []
    for mn in min_grid:
        for mx in max_grid:
            if mn > mx:
                continue
            st = _summarize_hypothetical_enriched(
                enriched,
                min_ttc_minutes=mn,
                max_ttc_minutes=mx,
            )
            closed = int(st["closed_hypo_count"])
            if closed < min_closed_trades:
                continue
            obj = _optimize_ttc_objective_value(st, objective)
            rp, rb = st["ret_pcts"], st["ret_bases"]
            results.append(
                {
                    "min_ttc": float(mn),
                    "max_ttc": float(mx),
                    "total_trades": int(st["total_trades"]),
                    "closed_hypo_count": closed,
                    "wins": int(st["hypo_wins"]),
                    "losses": int(st["hypo_losses"]),
                    "hypo_flat": int(st["hypo_flat"]),
                    "mean_ret_pct": float(sum(rp) / len(rp)) if rp else None,
                    "sum_ret_pct": float(sum(rp)) if rp else None,
                    "mean_ret_pct_base": float(sum(rb) / len(rb)) if rb else None,
                    "sum_ret_pct_base": float(sum(rb)) if rb else None,
                    "sum_pnl": float(sum(st["pnls"])) if st["pnls"] else 0.0,
                    "objective_value": obj,
                }
            )
    results.sort(
        key=lambda r: r["objective_value"] if r["objective_value"] is not None else float("-inf"),
        reverse=True,
    )
    return results


def fetch_hypothetical_enriched_bundles(
    monitors: Sequence[str],
    start: datetime,
    end: datetime,
    *,
    include_test_filter: bool,
    paper_mode: str,
    min_prob: float | None,
    max_prob: float | None,
    ttc_timezone: str,
    trade_filters: Sequence[str],
    hypothetical_position: int,
    hypo_ttc_under_minutes: float | None,
) -> list[dict[str, Any]]:
    """
    One DB round-trip per monitor: raw trades + hypothetical enrichment (TTC + hypo PnL).
    No min/max TTC filter (applied later in Python).
    """
    test_clause = _test_clause(include_test_filter)
    bundles: list[dict[str, Any]] = []
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            for monitor in monitors:
                parsed = parse_monitor_token(monitor)
                settings: dict[str, Any] | None = None
                strategy: str | None = None
                if parsed:
                    u, mid = parsed
                    settings = fetch_monitor_settings(cur, u, mid)
                    if settings:
                        strategy = settings.get("strategy")

                grid_15m = strategy_implies_15m_ttc_grid(strategy)
                extra = build_trade_where_parts(
                    paper_mode=paper_mode,
                    min_prob=min_prob,
                    max_prob=max_prob,
                    min_ttc_minutes=None,
                    max_ttc_minutes=None,
                    ttc_timezone=ttc_timezone,
                    ttc_grid_15m=grid_15m,
                    trade_filters=trade_filters,
                    omit_ttc=True,
                )
                raw = _fetch_raw_trade_rows(
                    cur, monitor, start, end, test_clause, extra
                )
                enriched = _build_hypothetical_enriched(
                    raw,
                    hypo_position=hypothetical_position,
                    ttc_timezone=ttc_timezone,
                    grid_15m=grid_15m,
                )
                hypo_under: float | None = None
                if hypo_ttc_under_minutes is not None:
                    hypo_under = _hypo_ttc_under_sum_pnl(enriched, hypo_ttc_under_minutes)
                bundles.append(
                    {
                        "monitor": monitor,
                        "strategy": strategy or "(unknown)",
                        "settings": settings,
                        "ttc_grid": "15m" if grid_15m else "hourly",
                        "cycle_strategy_note": is_cycle_based_strategy(strategy),
                        "enriched": enriched,
                        "hypo_ttc_under_sum_pnl": hypo_under,
                    }
                )
    finally:
        conn.close()
    return bundles


def _print_optimize_ttc_window_report(
    bundles: Sequence[dict[str, Any]],
    search_results: Sequence[Sequence[dict[str, Any]]],
    *,
    include_test_filter: bool,
    filter_lines: list[str],
    hypothetical_position: int,
    objective: str,
    min_range: tuple[float, float],
    max_range: tuple[float, float],
    step_seconds: float,
    top_k: int,
    hypo_ttc_under_minutes: float | None,
) -> None:
    col_min = "MIN_TTC≥"
    col_max = "MAX_TTC≤"
    print("Active filters:")
    for ln in filter_lines:
        print(f"  {ln}")
    print()
    print(f"Hypothetical position={hypothetical_position}. TTC window optimization.")
    print(
        "  TTC at open = minutes from entry (created_at) to the next bar boundary (15m or hourly)."
    )
    print(
        f"  {col_min}  Lower bound on TTC: keep trades with at least this many minutes left "
        "(excludes very late entries; low TTC)."
    )
    print(
        f"  {col_max}  Upper bound on TTC: keep trades with at most this many minutes left "
        "(excludes very early entries; high TTC)."
    )
    print(
        f"  Band: open_TTC must be ≥ the MIN_TTC column and ≤ the MAX_TTC column "
        f"(each grid pair uses floor ≤ cap)."
    )
    lo_mn, hi_mn = _norm_range_endpoints(min_range[0], min_range[1])
    lo_mx, hi_mx = _norm_range_endpoints(max_range[0], max_range[1])
    print(
        f"  Grid — {col_min} candidates: {_fmt_sweep_ceiling_minutes(lo_mn)} .. "
        f"{_fmt_sweep_ceiling_minutes(hi_mn)} min; "
        f"{col_max} candidates: {_fmt_sweep_ceiling_minutes(lo_mx)} .. "
        f"{_fmt_sweep_ceiling_minutes(hi_mx)} min; step {step_seconds:g} s."
    )
    print(f"  Maximize: {_optimize_objective_display_name(objective)}")
    if objective.startswith("mean_"):
        print(
            "  Note: mean_* can favor narrow windows with few trades; raise "
            "--optimize-ttc-min-closed-trades or use sum_* for total contribution."
        )
    if hypo_ttc_under_minutes is not None:
        print(
            f"  (hypo-ttc-under bucket still computed on full SQL-filtered set; "
            f"see per-monitor line where TTC < {hypo_ttc_under_minutes} min)"
        )
    print()

    for b, scored in zip(bundles, search_results):
        print(f"--- {b['monitor']} ---")
        if b.get("settings"):
            print(format_monitor_settings_brief(b["settings"]))
        else:
            print("  (no monitor_list row)")
        if b.get("cycle_strategy_note"):
            print(
                "  Note: cycle-based strategy in live analytics; search is per closed trade (hypo)."
            )
        print(
            f"  strategy={b['strategy']!r}  TTC grid={b.get('ttc_grid', '?')}  "
            f"enriched_rows={len(b['enriched'])}"
        )
        if hypo_ttc_under_minutes is not None and b.get("hypo_ttc_under_sum_pnl") is not None:
            print(
                f"  sum_hypo_pnl (open TTC < {hypo_ttc_under_minutes}, before window): "
                f"{float(b['hypo_ttc_under_sum_pnl']):.2f}"
            )
        print()
        if not scored:
            print(
                f"  No ({col_min},{col_max}) pairs met --optimize-ttc-min-closed-trades "
                "(or grid empty)."
            )
            print()
            continue
        best_val = scored[0]["objective_value"]
        if best_val is None:
            print("  No window had computable returns (missing bankroll / no ret_pct).")
            print()
            continue
        tied = [r for r in scored if r["objective_value"] == best_val]
        print(
            f"  Best {objective} = {best_val:.6g}  ({len(tied)} tied window(s) at this value)"
        )
        tie_rows: list[list[str]] = []
        for r in tied[:20]:
            mnp, srp = r["mean_ret_pct"], r["sum_ret_pct"]
            mnp_s = f"{mnp:.6g}" if mnp is not None else "n/a"
            srp_s = f"{srp:.6g}" if srp is not None else "n/a"
            tie_rows.append(
                [
                    _fmt_sweep_ceiling_minutes(r["min_ttc"]),
                    _fmt_sweep_ceiling_minutes(r["max_ttc"]),
                    str(r["closed_hypo_count"]),
                    mnp_s,
                    srp_s,
                    f"{r['sum_pnl']:.2f}",
                ]
            )
        tie_hdr = (
            col_min,
            col_max,
            "closed",
            "mean_ret%",
            "sum_ret%",
            "sum_pnl",
        )
        print(
            _text_table(
                list(tie_hdr),
                tie_rows,
                aligns=["r"] * len(tie_hdr),
                indent="  ",
            )
        )
        if len(tied) > 20:
            print(f"  ... and {len(tied) - 20} more tied windows (same objective).")
        print()
        show = scored[: max(1, top_k)]
        top_hdr = (
            "rank",
            col_min,
            col_max,
            "closed",
            "mean_ret%",
            "sum_ret%",
            "sum_pnl",
            "win_rate",
            "score",
        )
        top_rows: list[list[str]] = []
        for i, r in enumerate(show, start=1):
            wr = _win_rate_pct(r["wins"], r["losses"])
            ov = r["objective_value"]
            ov_s = f"{ov:.6g}" if ov is not None else "n/a"
            mnp = r["mean_ret_pct"]
            srp = r["sum_ret_pct"]
            top_rows.append(
                [
                    str(i),
                    _fmt_sweep_ceiling_minutes(r["min_ttc"]),
                    _fmt_sweep_ceiling_minutes(r["max_ttc"]),
                    str(r["closed_hypo_count"]),
                    f"{mnp:.6g}" if mnp is not None else "n/a",
                    f"{srp:.6g}" if srp is not None else "n/a",
                    f"{r['sum_pnl']:.2f}",
                    wr,
                    ov_s,
                ]
            )
        print(f"  Top {len(show)} by {objective}  (score = that objective)")
        top_aligns = ["l"] + ["r"] * (len(top_hdr) - 1)
        print(_text_table(list(top_hdr), top_rows, aligns=top_aligns, indent="  "))
        print()

    note = (
        "Including test_filter=TRUE rows."
        if include_test_filter
        else "Excluding test_filter=TRUE rows (default)."
    )
    print(note)
    print("Window: created_at >= start AND created_at < end (half-open).")
    print(
        "sum_ret_pct / mean_ret_pct: hypothetical closed trades with non-null bankroll "
        "(same scaling as stored ret_pct). sum_ret_pct is the sum of %-points in the window, "
        "not dollar-weighted portfolio return."
    )


def _test_clause(include_test_filter: bool) -> str:
    return "" if include_test_filter else f"AND {exclude_test_filter_sql('t')}"


def _fetch_trade_level(
    cur,
    monitor: str,
    start: datetime,
    end: datetime,
    test_clause: str,
    extra: TradeWhereParts,
    metrics: list[str],
    aggs: list[str],
) -> dict[str, Any]:
    fin = build_trade_financial_select(metrics, aggs)
    sql = f"""
        SELECT
            COUNT(*)::bigint AS total_trades,
            COUNT(*) FILTER (WHERE t.win_loss = 'W')::bigint AS wins,
            COUNT(*) FILTER (WHERE t.win_loss = 'L')::bigint AS losses
            {fin}
        FROM {TRADES_TABLE} t
        WHERE t.monitor = %s
          AND t.created_at >= %s AND t.created_at < %s
          {test_clause}
          {extra.sql()}
    """
    cur.execute(sql, (monitor, start, end, *extra.params))
    row = cur.fetchone()
    cols = [d[0] for d in cur.description]
    return dict(zip(cols, row))


def _fetch_cycle_level(
    cur,
    monitor: str,
    start: datetime,
    end: datetime,
    test_clause: str,
    extra: TradeWhereParts,
    metrics: list[str],
    aggs: list[str],
) -> dict[str, Any]:
    fin = build_cycle_financial_select(metrics, aggs)
    sql = f"""
        WITH win AS (
            SELECT t.contract, t.date, t.pnl, t.ret_pct, t.ret_pct_base, t.status
            FROM {TRADES_TABLE} t
            WHERE t.monitor = %s
              AND t.created_at >= %s AND t.created_at < %s
              {test_clause}
              {extra.sql()}
        ),
        trade_count AS (
            SELECT COUNT(*)::bigint AS total_trades FROM win
        ),
        closed AS (
            SELECT contract, date, pnl, ret_pct, ret_pct_base
            FROM win
            WHERE LOWER(TRIM(status)) IN ('closed', 'settled')
              AND contract IS NOT NULL
              AND NULLIF(TRIM(date), '') IS NOT NULL
        ),
        cyc AS (
            SELECT contract, date,
                   SUM(COALESCE(pnl, 0)::double precision) AS spnl,
                   SUM(COALESCE(ret_pct, 0)::double precision) AS sret,
                   SUM(COALESCE(ret_pct_base, 0)::double precision) AS sretb
            FROM closed
            GROUP BY contract, date
        )
        SELECT
            (SELECT total_trades FROM trade_count) AS total_trades,
            (SELECT COUNT(*)::bigint FROM cyc) AS cycles,
            (SELECT COUNT(*) FILTER (WHERE spnl > 0)::bigint FROM cyc) AS cyc_wins,
            (SELECT COUNT(*) FILTER (WHERE spnl < 0)::bigint FROM cyc) AS cyc_losses,
            (SELECT COUNT(*) FILTER (WHERE spnl = 0)::bigint FROM cyc) AS cyc_flat
            {fin}
    """
    cur.execute(sql, (monitor, start, end, *extra.params))
    row = cur.fetchone()
    cols = [d[0] for d in cur.description]
    return dict(zip(cols, row))


def fetch_summaries(
    monitors: Sequence[str],
    start: datetime,
    end: datetime,
    *,
    include_test_filter: bool,
    paper_mode: str,
    min_prob: float | None,
    max_prob: float | None,
    min_ttc_minutes: float | None,
    max_ttc_minutes: float | None,
    ttc_timezone: str,
    trade_filters: Sequence[str],
    metrics: list[str],
    aggs: list[str],
) -> list[dict[str, Any]]:
    test_clause = _test_clause(include_test_filter)
    fin_keys = financial_keys(metrics, aggs)
    conn = get_connection()
    rows: list[dict[str, Any]] = []
    try:
        with conn.cursor() as cur:
            for monitor in monitors:
                parsed = parse_monitor_token(monitor)
                settings: dict[str, Any] | None = None
                strategy: str | None = None
                basis = "per_trade"
                if parsed:
                    u, mid = parsed
                    settings = fetch_monitor_settings(cur, u, mid)
                    if settings:
                        strategy = settings.get("strategy")
                        if is_cycle_based_strategy(strategy):
                            basis = "per_cycle_pnl"

                grid_15m = strategy_implies_15m_ttc_grid(strategy)
                extra = build_trade_where_parts(
                    paper_mode=paper_mode,
                    min_prob=min_prob,
                    max_prob=max_prob,
                    min_ttc_minutes=min_ttc_minutes,
                    max_ttc_minutes=max_ttc_minutes,
                    ttc_timezone=ttc_timezone,
                    ttc_grid_15m=grid_15m,
                    trade_filters=trade_filters,
                )

                if basis == "per_cycle_pnl":
                    st = _fetch_cycle_level(
                        cur, monitor, start, end, test_clause, extra, metrics, aggs
                    )
                    row_d: dict[str, Any] = {
                        "monitor": monitor,
                        "strategy": strategy or "(unknown)",
                        "basis": basis,
                        "settings": settings,
                        "ttc_grid": "15m" if grid_15m else "hourly",
                        "total_trades": int(st["total_trades"] or 0),
                        "cycles": int(st["cycles"] or 0),
                        "wins": int(st["cyc_wins"] or 0),
                        "losses": int(st["cyc_losses"] or 0),
                        "unresolved": int(st["cyc_flat"] or 0),
                    }
                else:
                    st = _fetch_trade_level(
                        cur, monitor, start, end, test_clause, extra, metrics, aggs
                    )
                    tt = int(st["total_trades"] or 0)
                    w, l = int(st["wins"] or 0), int(st["losses"] or 0)
                    row_d = {
                        "monitor": monitor,
                        "strategy": (strategy if strategy is not None else "(unknown)"),
                        "basis": basis,
                        "settings": settings,
                        "ttc_grid": "15m" if grid_15m else "hourly",
                        "total_trades": tt,
                        "cycles": None,
                        "wins": w,
                        "losses": l,
                        "unresolved": tt - w - l,
                    }
                for k in fin_keys:
                    if k in st:
                        row_d[k] = st[k]
                rows.append(row_d)
    finally:
        conn.close()
    return rows


def _py_ttc_ok(
    ttc_minutes: float | None,
    min_m: float | None,
    max_m: float | None,
) -> bool:
    """Match SQL: min uses >=, max uses <= (see ``trade_filters.build_trade_where_parts``)."""
    if min_m is not None or max_m is not None:
        if ttc_minutes is None:
            return False
    if min_m is not None and ttc_minutes < min_m:
        return False
    if max_m is not None and ttc_minutes > max_m:
        return False
    return True


def _agg_series(vals: list[float], agg: str) -> float | None:
    if not vals:
        if agg == "sum":
            return 0.0
        return None
    if agg == "sum":
        return float(sum(vals))
    if agg == "mean":
        return float(sum(vals) / len(vals))
    if agg == "min":
        return float(min(vals))
    if agg == "max":
        return float(max(vals))
    if agg == "count":
        return float(len(vals))
    if agg == "stdev":
        if len(vals) < 2:
            return None
        return float(statistics.stdev(vals))
    raise ValueError(agg)


def _hypo_financial_stats(
    metrics: list[str],
    aggs: list[str],
    pnls: list[float],
    ret_pcts: list[float],
    ret_bases: list[float],
) -> dict[str, Any]:
    series = {"pnl": pnls, "ret_pct": ret_pcts, "ret_pct_base": ret_bases}
    out: dict[str, Any] = {}
    for m in metrics:
        vals = series.get(m, [])
        for a in aggs:
            out[f"{a}_{m}"] = _agg_series(vals, a)
    return out


def _fetch_raw_trade_rows(
    cur,
    monitor: str,
    start: datetime,
    end: datetime,
    test_clause: str,
    extra: TradeWhereParts,
) -> list[dict[str, Any]]:
    sql = f"""
        SELECT
            t.id, t.monitor, t.created_at, t.status,
            t.buy_price, t.sell_price, t.position,
            t.bankroll, t.mtb_base_value, t.prob, t.paper_trade,
            t.win_loss, t.contract, t.date, t.trade_strategy
        FROM {TRADES_TABLE} t
        WHERE t.monitor = %s
          AND t.created_at >= %s AND t.created_at < %s
          {test_clause}
          {extra.sql()}
        ORDER BY t.created_at
    """
    cur.execute(sql, (monitor, start, end, *extra.params))
    cols = [d[0] for d in cur.description]
    rows = cur.fetchall()
    return [dict(zip(cols, row)) for row in rows]


def _build_hypothetical_enriched(
    raw: list[dict[str, Any]],
    *,
    hypo_position: int,
    ttc_timezone: str,
    grid_15m: bool,
) -> list[dict[str, Any]]:
    """Attach ``_ttc`` and ``_hypo`` to each row (one pass; reuse for max-TTC sweeps)."""
    enriched: list[dict[str, Any]] = []
    for r in raw:
        ttc = open_to_next_boundary_minutes(
            r["created_at"], ttc_timezone, grid_15m=grid_15m
        )
        hypo = recompute_closed_trade_hypothetical(r, position=hypo_position)
        enriched.append({**r, "_ttc": ttc, "_hypo": hypo})
    return enriched


def _hypo_ttc_under_sum_pnl(
    enriched: list[dict[str, Any]],
    hypo_ttc_under_minutes: float,
) -> float:
    """Sum hypo_pnl for closed rows with open TTC strictly below threshold (full enriched set)."""
    s = 0.0
    for x in enriched:
        ttc = x["_ttc"]
        if ttc is None or ttc >= hypo_ttc_under_minutes:
            continue
        h = x["_hypo"]
        if h:
            s += float(h["hypo_pnl"])
    return s


def _summarize_hypothetical_enriched(
    enriched: list[dict[str, Any]],
    *,
    min_ttc_minutes: float | None,
    max_ttc_minutes: float | None,
) -> dict[str, Any]:
    """
    Aggregate hypo PnL/returns for rows passing Python TTC min/max (same semantics as SQL).
    """
    primary = [x for x in enriched if _py_ttc_ok(x["_ttc"], min_ttc_minutes, max_ttc_minutes)]

    pnls: list[float] = []
    ret_pcts: list[float] = []
    ret_bases: list[float] = []
    hypo_w = hypo_l = hypo_d = 0
    for x in primary:
        h = x["_hypo"]
        if not h:
            continue
        pnls.append(float(h["hypo_pnl"]))
        if h["hypo_ret_pct"] is not None:
            ret_pcts.append(float(h["hypo_ret_pct"]))
        if h["hypo_ret_pct_base"] is not None:
            ret_bases.append(float(h["hypo_ret_pct_base"]))
        wl = h["hypo_win_loss"]
        if wl == "W":
            hypo_w += 1
        elif wl == "L":
            hypo_l += 1
        else:
            hypo_d += 1

    return {
        "total_trades": len(primary),
        "closed_hypo_count": len(pnls),
        "hypo_wins": hypo_w,
        "hypo_losses": hypo_l,
        "hypo_flat": hypo_d,
        "pnls": pnls,
        "ret_pcts": ret_pcts,
        "ret_bases": ret_bases,
    }


def _enrich_hypothetical_rows(
    raw: list[dict[str, Any]],
    *,
    hypo_position: int,
    ttc_timezone: str,
    grid_15m: bool,
    min_ttc_minutes: float | None,
    max_ttc_minutes: float | None,
    hypo_ttc_under_minutes: float | None,
) -> dict[str, Any]:
    """
    Returns counts and series for hypothetical closed/settled recomputation.

    ``hypo_ttc_under_sum_pnl``: sum hypo_pnl for closed trades with open TTC **strictly below**
    the threshold, evaluated on the **full** SQL-filtered list (before Python TTC min/max).
    """
    enriched = _build_hypothetical_enriched(
        raw,
        hypo_position=hypo_position,
        ttc_timezone=ttc_timezone,
        grid_15m=grid_15m,
    )
    st = _summarize_hypothetical_enriched(
        enriched,
        min_ttc_minutes=min_ttc_minutes,
        max_ttc_minutes=max_ttc_minutes,
    )
    hypo_ttc_under_sum: float | None = None
    if hypo_ttc_under_minutes is not None:
        hypo_ttc_under_sum = _hypo_ttc_under_sum_pnl(enriched, hypo_ttc_under_minutes)
    st["hypo_ttc_under_sum_pnl"] = hypo_ttc_under_sum
    return st


def fetch_hypothetical_summaries(
    monitors: Sequence[str],
    start: datetime,
    end: datetime,
    *,
    include_test_filter: bool,
    paper_mode: str,
    min_prob: float | None,
    max_prob: float | None,
    min_ttc_minutes: float | None,
    max_ttc_minutes: float | None,
    ttc_timezone: str,
    trade_filters: Sequence[str],
    metrics: list[str],
    aggs: list[str],
    hypothetical_position: int,
    hypo_ttc_under_minutes: float | None,
    max_ttc_sweep: tuple[float, float] | None = None,
    max_ttc_sweep_step_seconds: float = 60.0,
) -> list[dict[str, Any]]:
    """
    Hypothetical fixed position: fees + PnL + returns per closed/settled trade; TTC in Python.

    When ``max_ttc_sweep`` is set, runs one summary per ceiling from ``max(a,b)`` down to
    ``min(a,b)`` minutes inclusive, stepping by ``max_ttc_sweep_step_seconds``, reusing one
    enriched pass per monitor.
    """
    test_clause = _test_clause(include_test_filter)
    conn = get_connection()
    rows_out: list[dict[str, Any]] = []
    try:
        with conn.cursor() as cur:
            for monitor in monitors:
                parsed = parse_monitor_token(monitor)
                settings: dict[str, Any] | None = None
                strategy: str | None = None
                if parsed:
                    u, mid = parsed
                    settings = fetch_monitor_settings(cur, u, mid)
                    if settings:
                        strategy = settings.get("strategy")

                grid_15m = strategy_implies_15m_ttc_grid(strategy)
                extra = build_trade_where_parts(
                    paper_mode=paper_mode,
                    min_prob=min_prob,
                    max_prob=max_prob,
                    min_ttc_minutes=min_ttc_minutes,
                    max_ttc_minutes=max_ttc_minutes,
                    ttc_timezone=ttc_timezone,
                    ttc_grid_15m=grid_15m,
                    trade_filters=trade_filters,
                    omit_ttc=True,
                )

                raw = _fetch_raw_trade_rows(
                    cur, monitor, start, end, test_clause, extra
                )
                enriched = _build_hypothetical_enriched(
                    raw,
                    hypo_position=hypothetical_position,
                    ttc_timezone=ttc_timezone,
                    grid_15m=grid_15m,
                )
                hypo_under_val: float | None = None
                if hypo_ttc_under_minutes is not None:
                    hypo_under_val = _hypo_ttc_under_sum_pnl(
                        enriched, hypo_ttc_under_minutes
                    )

                cycle_based = is_cycle_based_strategy(strategy)
                base_meta = {
                    "monitor": monitor,
                    "strategy": strategy or "(unknown)",
                    "basis": "per_trade_hypo",
                    "settings": settings,
                    "ttc_grid": "15m" if grid_15m else "hourly",
                    "cycle_strategy_note": cycle_based,
                    "hypo_ttc_under_sum_pnl": hypo_under_val,
                }

                if max_ttc_sweep is not None:
                    hi_m, lo_m = max_ttc_sweep[0], max_ttc_sweep[1]
                    ceilings = _max_ttc_sweep_ceiling_minutes(
                        hi_m, lo_m, max_ttc_sweep_step_seconds
                    )
                    for ceiling_min in ceilings:
                        st = _summarize_hypothetical_enriched(
                            enriched,
                            min_ttc_minutes=min_ttc_minutes,
                            max_ttc_minutes=float(ceiling_min),
                        )
                        fin: dict[str, Any] = {}
                        if metrics and aggs:
                            fin = _hypo_financial_stats(
                                metrics,
                                aggs,
                                st["pnls"],
                                st["ret_pcts"],
                                st["ret_bases"],
                            )
                        row_d: dict[str, Any] = {
                            **base_meta,
                            "max_ttc_ceiling_minutes": float(ceiling_min),
                            "total_trades": st["total_trades"],
                            "closed_hypo_count": st["closed_hypo_count"],
                            "wins": st["hypo_wins"],
                            "losses": st["hypo_losses"],
                            "unresolved": st["total_trades"] - st["closed_hypo_count"],
                            "hypo_flat": st["hypo_flat"],
                        }
                        row_d.update(fin)
                        rows_out.append(row_d)
                else:
                    st = _summarize_hypothetical_enriched(
                        enriched,
                        min_ttc_minutes=min_ttc_minutes,
                        max_ttc_minutes=max_ttc_minutes,
                    )
                    fin = {}
                    if metrics and aggs:
                        fin = _hypo_financial_stats(
                            metrics,
                            aggs,
                            st["pnls"],
                            st["ret_pcts"],
                            st["ret_bases"],
                        )
                    row_d = {
                        **base_meta,
                        "max_ttc_ceiling_minutes": None,
                        "total_trades": st["total_trades"],
                        "closed_hypo_count": st["closed_hypo_count"],
                        "wins": st["hypo_wins"],
                        "losses": st["hypo_losses"],
                        "unresolved": st["total_trades"] - st["closed_hypo_count"],
                        "hypo_flat": st["hypo_flat"],
                    }
                    row_d.update(fin)
                    rows_out.append(row_d)
    finally:
        conn.close()
    return rows_out


def _win_rate_pct(wins: int, losses: int) -> str:
    denom = wins + losses
    if denom == 0:
        return "n/a"
    return f"{100.0 * wins / denom:.1f}%"


def _fmt_combo_sum(metric: str, total: float) -> str:
    if metric == "pnl":
        return f"{total:.2f}"
    return f"{total:.6g}"


def _print_report(
    rows: list[dict[str, Any]],
    *,
    include_test_filter: bool,
    filter_lines: list[str],
    metrics: list[str],
    aggs: list[str],
) -> None:
    print("Active filters:")
    for ln in filter_lines:
        print(f"  {ln}")
    print()

    for r in rows:
        print(f"--- {r['monitor']} ---")
        if r.get("settings"):
            print(format_monitor_settings_brief(r["settings"]))
        else:
            print("  (no monitor_list row; using per-trade W/L)")
        print(
            f"  basis={r['basis']}  strategy={r['strategy']!r}  TTC grid={r.get('ttc_grid', '?')}"
            + ("  (~2 trades per cycle; W/L from SUM(pnl) per contract+date)" if r["basis"] == "per_cycle_pnl" else "")
        )
        print()

    hdr = (
        "monitor",
        "strategy",
        "basis",
        "trades",
        "cycles",
        "wins",
        "losses",
        "unresolved_or_flat",
        "win_rate",
    )
    aligns_tbl = ("l", "l", "l", "r", "r", "r", "r", "r", "r")
    bases: set[str] = set()
    tot_t = tot_cy = tot_w = tot_l = tot_u = 0
    body_tbl: list[list[str]] = []
    for r in rows:
        bases.add(r["basis"])
        cy = r["cycles"]
        cy_s = str(cy) if cy is not None else "—"
        body_tbl.append(
            [
                str(r["monitor"]),
                str(r["strategy"]),
                str(r["basis"]),
                str(r["total_trades"]),
                cy_s,
                str(r["wins"]),
                str(r["losses"]),
                str(r["unresolved"]),
                _win_rate_pct(r["wins"], r["losses"]),
            ]
        )
        tot_t += r["total_trades"]
        tot_cy += cy or 0
        tot_w += r["wins"]
        tot_l += r["losses"]
        tot_u += r["unresolved"]
    if len(bases) == 1:
        cy_tot = str(tot_cy) if "per_cycle_pnl" in bases else "—"
        foot = [
            [
                "TOTAL",
                "—",
                "—",
                str(tot_t),
                cy_tot,
                str(tot_w),
                str(tot_l),
                str(tot_u),
                _win_rate_pct(tot_w, tot_l),
            ]
        ]
    else:
        foot = [
            [
                "TOTAL",
                "—",
                "mixed",
                str(tot_t),
                str(tot_cy),
                str(tot_w),
                str(tot_l),
                str(tot_u),
                "(no combined win_rate)",
            ]
        ]
    print("Summary")
    print(_text_table(list(hdr), body_tbl, aligns=aligns_tbl, footers=foot))
    print()

    if metrics and aggs:
        print("Financial aggregates")
        print(
            "  (per_trade: over filtered trade rows | per_cycle_pnl: one series per cycle "
            "= SUM of column within contract+date among closed/settled)"
        )
        for r in rows:
            print(f"  [{r['monitor']}] basis={r['basis']}")
            st_sub = {k: r.get(k) for k in financial_keys(metrics, aggs)}
            tbl = _financial_kv_table(st_sub, metrics, aggs, indent="    ")
            if tbl:
                print(tbl)
        if len(rows) > 1 and "sum" in aggs:
            comb: list[list[str]] = []
            for m in metrics:
                k = f"sum_{m}"
                vals = [float(r[k]) for r in rows if r.get(k) is not None]
                if vals:
                    comb.append([k, _fmt_combo_sum(m, sum(vals))])
            if comb:
                print("  Combined (sum of each monitor's sum_* in this run)")
                print(_text_table(["metric", "value"], comb, aligns=["l", "r"], indent="    "))
        print()

    note = (
        "Including test_filter=TRUE rows."
        if include_test_filter
        else "Excluding test_filter=TRUE rows (default)."
    )
    print(note)
    print("Window: created_at >= start AND created_at < end (half-open).")
    print(
        "Cycle mode: groups closed/settled trades by (contract, date); W/L from sign of SUM(pnl); "
        "flat cycles (sum pnl = 0) in unresolved_or_flat."
    )


def _print_hypothetical_report(
    rows: list[dict[str, Any]],
    *,
    include_test_filter: bool,
    filter_lines: list[str],
    metrics: list[str],
    aggs: list[str],
    hypothetical_position: int,
    hypo_ttc_under_minutes: float | None,
) -> None:
    print("Active filters:")
    for ln in filter_lines:
        print(f"  {ln}")
    print()
    print(
        f"Hypothetical mode: fixed position={hypothetical_position} "
        "(Kalshi taker fees recomputed; PnL/ret_pct/ret_pct_base from hypo fills). "
        "TTC filters applied in Python (SQL TTC omitted)."
    )
    if hypo_ttc_under_minutes is not None:
        print(
            f"  Extra bucket: sum hypo_pnl where open TTC < {hypo_ttc_under_minutes} "
            "(minutes; on SQL-filtered rows before --min/--max-ttc-minutes)."
        )
    print()

    for r in rows:
        print(f"--- {r['monitor']} ---")
        if r.get("settings"):
            print(format_monitor_settings_brief(r["settings"]))
        else:
            print("  (no monitor_list row)")
        if r.get("cycle_strategy_note"):
            print(
                "  Note: monitor strategy is cycle-based in live analytics; "
                "this hypothetical block is **per closed trade** (not cycle roll-up)."
            )
        print(
            f"  basis={r['basis']}  strategy={r['strategy']!r}  TTC grid={r.get('ttc_grid', '?')}"
        )
        print()

    hdr = (
        "monitor",
        "strategy",
        "trades",
        "closed_hypo",
        "wins",
        "losses",
        "hypo_flat",
        "unresolved_or_open",
        "win_rate",
    )
    aligns_h = ("l", "l", "r", "r", "r", "r", "r", "r", "r")
    body_h: list[list[str]] = []
    tot_t = tot_ch = tot_w = tot_l = tot_f = tot_u = 0
    for r in rows:
        tt = int(r["total_trades"])
        ch = int(r["closed_hypo_count"])
        w, l = int(r["wins"]), int(r["losses"])
        hf = int(r.get("hypo_flat", 0))
        un = tt - w - l
        body_h.append(
            [
                str(r["monitor"]),
                str(r["strategy"]),
                str(tt),
                str(ch),
                str(w),
                str(l),
                str(hf),
                str(un),
                _win_rate_pct(w, l),
            ]
        )
        tot_t += tt
        tot_ch += ch
        tot_w += w
        tot_l += l
        tot_f += hf
        tot_u += un
    foot_h = [
        [
            "TOTAL",
            "—",
            str(tot_t),
            str(tot_ch),
            str(tot_w),
            str(tot_l),
            str(tot_f),
            str(tot_u),
            _win_rate_pct(tot_w, tot_l),
        ]
    ]
    print("Summary (hypothetical)")
    print(_text_table(list(hdr), body_h, aligns=aligns_h, footers=foot_h))
    print()

    if hypo_ttc_under_minutes is not None:
        print(
            "Hypo PnL sub-bucket (open TTC strictly under threshold, before Python TTC min/max)"
        )
        combined = 0.0
        urows: list[list[str]] = []
        col = f"sum_hypo_pnl (TTC < {hypo_ttc_under_minutes} min)"
        for r in rows:
            v = r.get("hypo_ttc_under_sum_pnl")
            if v is None:
                continue
            urows.append([str(r["monitor"]), f"{float(v):.2f}"])
            combined += float(v)
        if urows:
            print(_text_table(["monitor", col], urows, aligns=["l", "r"]))
        if len(rows) > 1 and urows:
            print(
                _text_table(
                    ["scope", col],
                    [["all monitors (sum)", f"{combined:.2f}"]],
                    aligns=["l", "r"],
                )
            )
        print()

    if metrics and aggs:
        print("Hypothetical financial aggregates (closed/settled recomputed values)")
        fin_keys = financial_keys(metrics, aggs)
        for r in rows:
            print(f"  [{r['monitor']}]")
            st_sub = {k: r.get(k) for k in fin_keys}
            tbl = _financial_kv_table(st_sub, metrics, aggs, indent="    ")
            if tbl:
                print(tbl)
        if len(rows) > 1 and "sum" in aggs:
            comb: list[list[str]] = []
            for m in metrics:
                k = f"sum_{m}"
                vals = [float(r[k]) for r in rows if r.get(k) is not None]
                if vals:
                    comb.append([k, _fmt_combo_sum(m, sum(vals))])
            if comb:
                print("  Combined (sum of each monitor's sum_* in this run)")
                print(_text_table(["metric", "value"], comb, aligns=["l", "r"], indent="    "))
        print()

    note = (
        "Including test_filter=TRUE rows."
        if include_test_filter
        else "Excluding test_filter=TRUE rows (default)."
    )
    print(note)
    print("Window: created_at >= start AND created_at < end (half-open).")


def _fmt_sweep_fin_cell(key: str, v: object) -> str:
    if v is None:
        return "n/a"
    if key.startswith("count_"):
        return str(int(v))
    if "_pnl" in key:
        return f"{float(v):.2f}"
    try:
        x = float(v)
    except (TypeError, ValueError):
        return str(v)
    if abs(x) >= 1000 or abs(x) < 0.0001:
        return f"{x:.6g}"
    return f"{x:.4f}"


def _print_hypothetical_sweep_report(
    rows: list[dict[str, Any]],
    *,
    include_test_filter: bool,
    filter_lines: list[str],
    metrics: list[str],
    aggs: list[str],
    hypothetical_position: int,
    hypo_ttc_under_minutes: float | None,
    sweep_hi: float,
    sweep_lo: float,
    sweep_step_seconds: float,
) -> None:
    print("Active filters:")
    for ln in filter_lines:
        print(f"  {ln}")
    print()
    print(
        f"Hypothetical mode: fixed position={hypothetical_position} "
        "(Kalshi taker fees recomputed). "
        f"Max TTC sweep: ceilings from {_fmt_sweep_ceiling_minutes(sweep_hi)} down to "
        f"{_fmt_sweep_ceiling_minutes(sweep_lo)} minutes inclusive, "
        f"step {sweep_step_seconds:g} s (open TTC must be <= ceiling; same as --max-ttc-minutes)."
    )
    if hypo_ttc_under_minutes is not None:
        print(
            f"  Extra bucket (per monitor, independent of ceiling): sum hypo_pnl where open TTC < "
            f"{hypo_ttc_under_minutes} (before ceiling filter)."
        )
    print()

    fin_keys = financial_keys(metrics, aggs) if metrics and aggs else []

    i = 0
    while i < len(rows):
        r0 = rows[i]
        monitor = r0["monitor"]
        chunk: list[dict[str, Any]] = []
        while i < len(rows) and rows[i]["monitor"] == monitor:
            chunk.append(rows[i])
            i += 1

        print(f"--- {monitor} ---")
        if r0.get("settings"):
            print(format_monitor_settings_brief(r0["settings"]))
        else:
            print("  (no monitor_list row)")
        if r0.get("cycle_strategy_note"):
            print(
                "  Note: monitor strategy is cycle-based in live analytics; "
                "this hypothetical block is **per closed trade** (not cycle roll-up)."
            )
        print(
            f"  basis={r0['basis']}  strategy={r0['strategy']!r}  TTC grid={r0.get('ttc_grid', '?')}"
        )
        if hypo_ttc_under_minutes is not None:
            u = r0.get("hypo_ttc_under_sum_pnl")
            if u is not None:
                print(
                    f"  sum_hypo_pnl (open TTC < {hypo_ttc_under_minutes} min, before ceiling): "
                    f"{float(u):.2f}"
                )
        print()

        base_headers = [
            "max_ttc<=",
            "trades",
            "closed_hypo",
            "wins",
            "losses",
            "hypo_flat",
            "unres",
            "win_rate",
        ]
        headers = base_headers + fin_keys
        aligns_sw = ["r"] * len(headers)
        body_sw: list[list[str]] = []
        for r in chunk:
            mtc = _fmt_sweep_ceiling_minutes(float(r["max_ttc_ceiling_minutes"]))
            tt = int(r["total_trades"])
            ch = int(r["closed_hypo_count"])
            w, l = int(r["wins"]), int(r["losses"])
            hf = int(r.get("hypo_flat", 0))
            un = tt - w - l
            row = [
                mtc,
                str(tt),
                str(ch),
                str(w),
                str(l),
                str(hf),
                str(un),
                _win_rate_pct(w, l),
            ]
            for fk in fin_keys:
                row.append(_fmt_sweep_fin_cell(fk, r.get(fk)))
            body_sw.append(row)
        print(f"Max TTC sweep ({monitor})")
        print(_text_table(headers, body_sw, aligns=aligns_sw))
        print()

    note = (
        "Including test_filter=TRUE rows."
        if include_test_filter
        else "Excluding test_filter=TRUE rows (default)."
    )
    print(note)
    print("Window: created_at >= start AND created_at < end (half-open).")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--monitors",
        type=_parse_monitors,
        required=True,
        help="Comma-separated monitor names (e.g. mon_0001_1,mon_0001_2)",
    )
    p.add_argument("--start", type=_parse_instant, required=True, help="ISO-8601 start (inclusive)")
    p.add_argument("--end", type=_parse_instant, required=True, help="ISO-8601 end (exclusive)")
    p.add_argument(
        "--include-test-filter",
        action="store_true",
        help="Include trades with test_filter=TRUE (default is to exclude them)",
    )
    p.add_argument(
        "--paper",
        choices=("all", "live", "paper"),
        default="all",
        help="paper_trade: all (default), live only, or paper only",
    )
    p.add_argument(
        "--min-prob",
        type=float,
        default=None,
        help="Minimum t.prob (DB scale, typically 0–100)",
    )
    p.add_argument(
        "--max-prob",
        type=float,
        default=None,
        help="Maximum t.prob (DB scale)",
    )
    p.add_argument(
        "--min-ttc-minutes",
        type=float,
        default=None,
        help="Minimum open→next-boundary TTC (minutes; grid from monitor strategy)",
    )
    p.add_argument(
        "--max-ttc-minutes",
        type=float,
        default=None,
        help="Maximum open→next-boundary TTC (minutes)",
    )
    p.add_argument(
        "--ttc-timezone",
        default="America/New_York",
        help="IANA zone for TTC boundaries (default America/New_York)",
    )
    p.add_argument(
        "--trade-filter",
        action="append",
        default=[],
        metavar="COL:OP:VAL",
        help="Repeatable. Allowlisted column, op (eq,ne,gt,gte,lt,lte,like,ilike), value.",
    )
    p.add_argument(
        "--metrics",
        default="ret_pct",
        help="Comma-separated: ret_pct (default), ret_pct_base, pnl, or all; use none to skip",
    )
    p.add_argument(
        "--agg",
        default="sum",
        help="Comma-separated: sum (default), mean, min, max, count, stdev",
    )
    p.add_argument(
        "--hypothetical-position",
        type=int,
        default=None,
        metavar="N",
        help=(
            "Recompute taker fees and PnL/returns at fixed position N for each closed/settled trade; "
            "TTC min/max run in Python (not SQL). See --hypo-ttc-under-minutes."
        ),
    )
    p.add_argument(
        "--hypo-ttc-under-minutes",
        type=float,
        default=None,
        metavar="M",
        help=(
            "Print extra sum hypo_pnl for trades whose open TTC is strictly < M minutes; "
            "evaluated on SQL-filtered rows before applying --min-ttc-minutes / --max-ttc-minutes."
        ),
    )
    p.add_argument(
        "--max-ttc-sweep",
        type=_parse_max_ttc_sweep,
        default=None,
        metavar="HIGH:LOW",
        help=(
            "Requires --hypothetical-position. Max-TTC ceilings in minutes from HIGH down to LOW "
            "(inclusive; floats allowed). Step: --max-ttc-sweep-step-seconds (default 60). "
            "Mutually exclusive with --max-ttc-minutes."
        ),
    )
    p.add_argument(
        "--max-ttc-sweep-step-seconds",
        type=_parse_grid_step_seconds,
        default=60.0,
        metavar="SEC",
        help=(
            "With --max-ttc-sweep only: seconds between ceiling values (default 60). "
            "Minimum 1 (finest supported step)."
        ),
    )
    p.add_argument(
        "--optimize-ttc-window",
        action="store_true",
        help=(
            "Requires --hypothetical-position. Grid over (MIN_TTC≥, MAX_TTC≤) bands; maximizes "
            "--optimize-ttc-objective (default sum_ret_pct = total hypo ret_pct). Mutually "
            "exclusive with --max-ttc-sweep and --min-ttc-minutes / --max-ttc-minutes."
        ),
    )
    p.add_argument(
        "--optimize-ttc-min-range",
        type=_parse_max_ttc_sweep,
        default=(0.0, 30.0),
        metavar="LO:HI",
        help=(
            "Grid for MIN_TTC≥ (late-entry floor, minutes open→next boundary). Default 0:30"
        ),
    )
    p.add_argument(
        "--optimize-ttc-max-range",
        type=_parse_max_ttc_sweep,
        default=(0.0, 30.0),
        metavar="LO:HI",
        help=(
            "Grid for MAX_TTC≤ (early-entry cap, minutes open→next boundary). Default 0:30"
        ),
    )
    p.add_argument(
        "--optimize-ttc-step-seconds",
        type=_parse_grid_step_seconds,
        default=60.0,
        metavar="SEC",
        help="Step for both min and max axes (default 60). Minimum 1.",
    )
    p.add_argument(
        "--optimize-ttc-objective",
        choices=(
            "mean_ret_pct",
            "sum_ret_pct",
            "mean_ret_pct_base",
            "sum_ret_pct_base",
        ),
        default="sum_ret_pct",
        help=(
            "Metric to maximize (default sum_ret_pct = total hypo ret_pct in window). "
            "Alternatives: mean_ret_pct, sum_ret_pct_base, mean_ret_pct_base."
        ),
    )
    p.add_argument(
        "--optimize-ttc-top",
        type=int,
        default=15,
        metavar="N",
        help="Print the top N (min,max) windows by objective after the best/tied section (default 15).",
    )
    p.add_argument(
        "--optimize-ttc-min-closed-trades",
        type=int,
        default=5,
        metavar="K",
        help=(
            "Skip windows with fewer than K closed hypo trades (default 5). "
            "Use 1 to include narrow windows (mean_* can spike on one trade)."
        ),
    )
    args = p.parse_args(argv)

    if args.end <= args.start:
        print("error: --end must be after --start", file=sys.stderr)
        return 2
    if args.hypothetical_position is not None and args.hypothetical_position <= 0:
        print("error: --hypothetical-position must be a positive integer", file=sys.stderr)
        return 2
    if args.max_ttc_sweep is not None and args.max_ttc_minutes is not None:
        print(
            "error: use either --max-ttc-sweep or --max-ttc-minutes, not both",
            file=sys.stderr,
        )
        return 2
    if args.max_ttc_sweep is not None and args.hypothetical_position is None:
        print(
            "error: --max-ttc-sweep requires --hypothetical-position (hypothetical TTC is in Python)",
            file=sys.stderr,
        )
        return 2
    if args.max_ttc_sweep is None and args.max_ttc_sweep_step_seconds != 60.0:
        print(
            "error: --max-ttc-sweep-step-seconds only applies with --max-ttc-sweep",
            file=sys.stderr,
        )
        return 2
    if args.optimize_ttc_window and args.hypothetical_position is None:
        print(
            "error: --optimize-ttc-window requires --hypothetical-position",
            file=sys.stderr,
        )
        return 2
    if args.optimize_ttc_window and args.max_ttc_sweep is not None:
        print(
            "error: use either --optimize-ttc-window or --max-ttc-sweep, not both",
            file=sys.stderr,
        )
        return 2
    if args.optimize_ttc_window and (
        args.min_ttc_minutes is not None or args.max_ttc_minutes is not None
    ):
        print(
            "error: --optimize-ttc-window sets its own min/max grid; "
            "do not pass --min-ttc-minutes or --max-ttc-minutes",
            file=sys.stderr,
        )
        return 2
    if args.optimize_ttc_top < 1:
        print("error: --optimize-ttc-top must be >= 1", file=sys.stderr)
        return 2
    if args.optimize_ttc_min_closed_trades < 1:
        print("error: --optimize-ttc-min-closed-trades must be >= 1", file=sys.stderr)
        return 2

    if args.optimize_ttc_window:
        try:
            bundles = fetch_hypothetical_enriched_bundles(
                args.monitors,
                args.start,
                args.end,
                include_test_filter=args.include_test_filter,
                paper_mode=args.paper,
                min_prob=args.min_prob,
                max_prob=args.max_prob,
                ttc_timezone=args.ttc_timezone,
                trade_filters=args.trade_filter or [],
                hypothetical_position=args.hypothetical_position,
                hypo_ttc_under_minutes=args.hypo_ttc_under_minutes,
            )
            search_results = [
                _grid_search_hypothetical_ttc_window(
                    b["enriched"],
                    min_range=args.optimize_ttc_min_range,
                    max_range=args.optimize_ttc_max_range,
                    step_seconds=args.optimize_ttc_step_seconds,
                    objective=args.optimize_ttc_objective,
                    min_closed_trades=args.optimize_ttc_min_closed_trades,
                )
                for b in bundles
            ]
        except ValueError as e:
            print(f"error: {e}", file=sys.stderr)
            return 2

        filter_lines = format_filters_for_display(
            paper_mode=args.paper,
            min_prob=args.min_prob,
            max_prob=args.max_prob,
            min_ttc=None,
            max_ttc=None,
            ttc_timezone=args.ttc_timezone,
            trade_filters=args.trade_filter or [],
        )
        filter_lines.append(
            "TTC stepping: 15m grid if monitor strategy contains '15m'; else hourly (per monitor)."
        )
        filter_lines.append(
            f"Hypothetical position: {args.hypothetical_position} (TTC window search in Python)."
        )
        mn0, mn1 = args.optimize_ttc_min_range[0], args.optimize_ttc_min_range[1]
        mx0, mx1 = args.optimize_ttc_max_range[0], args.optimize_ttc_max_range[1]
        filter_lines.append(
            f"optimize TTC: min axis {_fmt_sweep_ceiling_minutes(min(mn0, mn1))}.."
            f"{_fmt_sweep_ceiling_minutes(max(mn0, mn1))} min; max axis "
            f"{_fmt_sweep_ceiling_minutes(min(mx0, mx1))}..{_fmt_sweep_ceiling_minutes(max(mx0, mx1))} "
            f"min; step {args.optimize_ttc_step_seconds:g} s; objective={args.optimize_ttc_objective}"
        )
        _print_optimize_ttc_window_report(
            bundles,
            search_results,
            include_test_filter=args.include_test_filter,
            filter_lines=filter_lines,
            hypothetical_position=args.hypothetical_position,
            objective=args.optimize_ttc_objective,
            min_range=args.optimize_ttc_min_range,
            max_range=args.optimize_ttc_max_range,
            step_seconds=args.optimize_ttc_step_seconds,
            top_k=args.optimize_ttc_top,
            hypo_ttc_under_minutes=args.hypo_ttc_under_minutes,
        )
        return 0

    metrics: list[str] = []
    aggs: list[str] = []
    try:
        metrics = parse_metrics_list(args.metrics)
        aggs = parse_aggs_list(args.agg)
        if metrics and not aggs:
            aggs = ["sum"]
        if args.hypothetical_position is not None:
            rows = fetch_hypothetical_summaries(
                args.monitors,
                args.start,
                args.end,
                include_test_filter=args.include_test_filter,
                paper_mode=args.paper,
                min_prob=args.min_prob,
                max_prob=args.max_prob,
                min_ttc_minutes=args.min_ttc_minutes,
                max_ttc_minutes=args.max_ttc_minutes,
                ttc_timezone=args.ttc_timezone,
                trade_filters=args.trade_filter or [],
                metrics=metrics,
                aggs=aggs,
                hypothetical_position=args.hypothetical_position,
                hypo_ttc_under_minutes=args.hypo_ttc_under_minutes,
                max_ttc_sweep=args.max_ttc_sweep,
                max_ttc_sweep_step_seconds=args.max_ttc_sweep_step_seconds,
            )
        else:
            rows = fetch_summaries(
                args.monitors,
                args.start,
                args.end,
                include_test_filter=args.include_test_filter,
                paper_mode=args.paper,
                min_prob=args.min_prob,
                max_prob=args.max_prob,
                min_ttc_minutes=args.min_ttc_minutes,
                max_ttc_minutes=args.max_ttc_minutes,
                ttc_timezone=args.ttc_timezone,
                trade_filters=args.trade_filter or [],
                metrics=metrics,
                aggs=aggs,
            )
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    filter_lines = format_filters_for_display(
        paper_mode=args.paper,
        min_prob=args.min_prob,
        max_prob=args.max_prob,
        min_ttc=args.min_ttc_minutes,
        max_ttc=args.max_ttc_minutes,
        ttc_timezone=args.ttc_timezone,
        trade_filters=args.trade_filter or [],
    )
    filter_lines.append(
        "TTC stepping: 15m grid if monitor strategy contains '15m'; else hourly (per monitor)."
    )
    if args.hypothetical_position is not None:
        filter_lines.append(
            f"Hypothetical position: {args.hypothetical_position} "
            "(min/max TTC applied in Python when set)."
        )
    if args.max_ttc_sweep is not None:
        a, b = args.max_ttc_sweep[0], args.max_ttc_sweep[1]
        hi, lo = max(a, b), min(a, b)
        filter_lines.append(
            f"max TTC sweep: {_fmt_sweep_ceiling_minutes(hi)} down to {_fmt_sweep_ceiling_minutes(lo)} "
            f"min, step {args.max_ttc_sweep_step_seconds:g} s (hypothetical only)"
        )
    if metrics and aggs:
        filter_lines.append(f"Financial metrics: {','.join(metrics)}; aggregations: {','.join(aggs)}")
    else:
        filter_lines.append("Financial metrics: (none)")
    if args.hypothetical_position is not None:
        if args.max_ttc_sweep is not None:
            a, b = args.max_ttc_sweep[0], args.max_ttc_sweep[1]
            sweep_hi, sweep_lo = max(a, b), min(a, b)
            _print_hypothetical_sweep_report(
                rows,
                include_test_filter=args.include_test_filter,
                filter_lines=filter_lines,
                metrics=metrics,
                aggs=aggs,
                hypothetical_position=args.hypothetical_position,
                hypo_ttc_under_minutes=args.hypo_ttc_under_minutes,
                sweep_hi=sweep_hi,
                sweep_lo=sweep_lo,
                sweep_step_seconds=args.max_ttc_sweep_step_seconds,
            )
        else:
            _print_hypothetical_report(
                rows,
                include_test_filter=args.include_test_filter,
                filter_lines=filter_lines,
                metrics=metrics,
                aggs=aggs,
                hypothetical_position=args.hypothetical_position,
                hypo_ttc_under_minutes=args.hypo_ttc_under_minutes,
            )
    else:
        _print_report(
            rows,
            include_test_filter=args.include_test_filter,
            filter_lines=filter_lines,
            metrics=metrics,
            aggs=aggs,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
