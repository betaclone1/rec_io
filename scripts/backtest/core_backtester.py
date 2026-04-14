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

**Risk replay (loss prevention + sizing + optional regime):** ``--lp-streak-threshold-sweep LOW:HIGH``
replays cycles like ``trade_manager`` (ticker-prefix cycles; momentum = one streak increment per
winning cycle). Position contracts use ``monitor_manager`` math: ``percent`` mode uses
``bankroll_allotment_total`` and each row's ``multiplier``; PBA applies ``current_max_pct_exposure``
cap when ``performance_based_allocation`` is on. Optional ``--lp-sweep-apply-regime`` drops rows that
would be paper-only under ``regime_monitor`` (rolling sum of prior ``ret_pct`` in ``regime_window``).
Mutually exclusive with ``--hypothetical-position`` and TTC optimization flags.
Optional ``--compound-start-usd`` (with the LP sweep): trades processed in global time order; bankroll
starts at that USD amount (cent-rounded); each closed trade adds hypo PnL; **percent** sizing uses
the running balance as the allotment dollars base; ``sum_hypo_ret_pct`` becomes the sum of
``100 * pnl / entry_balance`` per trade (``sum_hypo_ret_pct_base`` is 0 in this mode).

**Combo grid:** ``--combo-risk-grid`` + ``--compound-start-usd`` grids min-prob, TTC band, and LP
threshold; objective is **total return %** ``(ending/start-1)×100`` on the compounded bankroll.

Uses ``created_at`` (timestamptz) for the window. Default: exclude ``test_filter=TRUE``.

DB: ``scripts/backtest/helpers/db.py`` (SSH prod default, etc.).

**Tick-level backtest table:** ``--build-tick-backtest TICKER`` builds ``backtest.tick_backtest_<slug>`` with
columns aligned to ``live_data.strike_table_15m`` (trade prices as YES/NO asks; bids/spreads NULL).
Optional ``volume_fp`` / ``open_interest_fp`` from ``backtest.backtest_1m_<slug>`` when that table exists
(same minute repeated per tick). Sources: ``live_data.live_price_log_1s_*``, trades, candles. See
``scripts/backtest/helpers/tick_backtest_build.py``. **HTC replay on ticks:** ``--replay-htc-market TICKER
--replay-from-tick-backtest`` runs AES/ATS over ``tick_backtest_<slug>`` (see ``htc_backtest_replay``).

**Kalshi → backtest schema (any tickers):** ``--ingest-kalshi-tickers T1 T2 ...`` fetches 1m
candlesticks plus ``floor_strike`` / ``market_result`` (historical markets API, then live market
fallback) and upserts into ``backtest.backtest_1m_<slug>`` per ticker. For ``KXBTC*`` / ``KXETH*``
tickers, joins ``historical_data.btc_price_history`` / ``eth_price_history`` on Eastern-naive
``timestamp`` and copies price-history columns (``open``, ``high``, …). A ticker is **skipped**
(no table create / upsert) if Kalshi returns no 1m candles for the window, or (with spot join on)
if any bar minute is missing from the corresponding ``*_price_history`` table. Use ``--ingest-no-spot``
to skip that join. Creates schema/tables as needed (no per-ticker SQL migrations). Does not require
``--monitors`` / ``--start`` / ``--end``.
**Series + close window:** ``--ingest-kalshi-series KXBTC15M --ingest-kalshi-close-start ... --ingest-kalshi-close-end ...``
paginates Kalshi ``GET /markets`` (``series_ticker`` + close-time bounds), then ingests each
discovered ticker (skips still apply per market).

**Eastern trading day (preferred for 15m batches):** ``--ingest-kalshi-trading-day KXETH15M 2026-03-31``
builds **96** tickers for that **US Eastern calendar date** (same ``YYYY-MM-DD`` convention as
``trade.date`` / ``today_est``), matching ``kalshi_contract_settlement_end_est`` / settlement grid.
No discovery API call; skips still apply if Kalshi has no market or data for a slot.
**Hourly** daily contracts (strike in ``-T...``) are not synthesized (96×15m only).

**HTTP:** ``REC_IO_KALSHI_HTTP_RETRIES`` (see ``kalshi_candles_1m._http_json``) retries transient timeouts.

**Backtest row contract (``backtest.backtest_1m_<slug>``):** Each row is **one Kalshi 1m bar**
aligned to Eastern-naive ``timestamp`` (bar end), intended as the artifact a future virtual
``auto_entry_supervisor`` / trade replay can read without tick data. Design goal: **conservative**
semantics: store **intervals** where the true live path is unknown, not optimistic point guesses.

- **Facts (observed in that minute):** Kalshi ``yes_price_*_dollars`` from API ``price`` OHLC;
  ``no_price_*`` = ``1 −`` YES (clamped); YES bid/ask OHLC; ``volume_fp`` / ``open_interest_fp``;
  ``floor_strike`` / ``market_result`` for the cycle; joined symbol columns from
  ``historical_data.*_price_history`` (``open``, ``high``, …, ``momentum_percentile``, …) when
  the ticker maps to BTC/ETH.

- **Derived bounds (compatible with the bar, not tick-truth):** ``ttc_15m_open_seconds`` /
  ``ttc_15m_close_seconds`` (15m boundary TTC at bar open vs close); ``strike_buffer_min`` /
  ``strike_buffer_max`` from symbol ``low``/``high`` vs ``floor_strike``; ``yes_prob_15m_min`` /
  ``max`` and ``no_prob_15m_min`` / ``max`` from **four corners** of (TTC, buffer) over the minute,
  using the same analytics lookup as live strike tables, then **active-side complements** on the
  0–100 scale (``active_side`` = **yes**: no = ``100 − pos``; **no**: yes = ``100 − neg``;
  **cross**: raw pos/neg). ``yes_diff_*`` / ``no_diff_*`` are **ranges** from two ``money_line``
  corners (low spot / min active prob / low YES ask vs high / max / high YES ask). Code:
  ``scripts/backtest/helpers/backtest_strike_span.py``.

- **Gates for later replay:** ``active_side`` is **yes** / **no** if the whole minute's symbol
  range is strictly on one side of strike; **cross** if ``low ≤ strike ≤ high``.
  ``minute_tradeable`` is false when **cross** (no clean money-line side for that minute).

- **Future virtual supervisors:** should map each live gate to a **pessimistic** choice among
  stored ``*_min`` / ``*_max`` (e.g. minimum prob when checking a floor). Ingest does **not**
  simulate trades; it only materializes the row contract. Full column list:
  ``docs/MASTER_DB_SCHEMA_REFERENCE.md`` (schema ``backtest``).

**Initiative (scope, supervisor parity, minutes vs seconds, UI roadmap):** ``docs/BACKTESTING.md``.

Example:
  python3 scripts/backtest/core_backtester.py \\
    --monitors mon_0001_10002 \\
    --start 2026-01-01T00:00:00-05:00 \\
    --end 2027-01-01T00:00:00-05:00 \\
    --min-prob 96 --paper live

  python3 scripts/backtest/core_backtester.py \\
    --monitors mon_0001_10002 \\
    --start 2026-01-01T00:00:00-05:00 \\
    --end 2027-01-01T00:00:00-05:00 \\
    --min-prob 97 --trade-filter momentum_percentile:gte:50

  python3 scripts/backtest/core_backtester.py \\
    --monitors mon_0001_10026 \\
    --start 2026-03-01T00:00:00-05:00 \\
    --end 2026-04-01T00:00:00-05:00 \\
    --hypothetical-position 1500 --max-ttc-sweep 15:2 \\
    --max-ttc-sweep-step-seconds 60 \\
    --metrics pnl --agg sum
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
from datetime import datetime, timezone
from typing import Any, Sequence

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from scripts.backtest.helpers.constants import TRADES_TABLE
from scripts.backtest.helpers.db import get_connection
from scripts.backtest.helpers.filters import exclude_test_filter_sql
from scripts.backtest.helpers.monitor_context import (
    fetch_monitor_risk_settings,
    fetch_monitor_settings,
    format_monitor_settings_brief,
    is_cycle_based_strategy,
    parse_monitor_token,
)
from scripts.backtest.helpers.risk_replay import (
    replay_loss_prevention_threshold,
    sweep_loss_prevention_thresholds,
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
from scripts.backtest.helpers.htc_backtest_replay import (
    fetch_monitor_auto_entry_settings,
    fetch_strategy_auto_entry_settings,
    infer_strategy_list_name_for_kalshi_ticker,
    run_htc_single_market_replay,
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


def _parse_lp_streak_sweep(s: str) -> tuple[int, int]:
    """Inclusive integer range ``LOW:HIGH`` for win_streak_threshold sweep (order-independent)."""
    parts = s.strip().split(":")
    if len(parts) != 2:
        raise argparse.ArgumentTypeError(
            f"Expected LOW:HIGH for --lp-streak-threshold-sweep (e.g. 1:30); got {s!r}"
        )
    try:
        a = int(parts[0].strip())
        b = int(parts[1].strip())
    except ValueError as e:
        raise argparse.ArgumentTypeError(f"Invalid integer bounds in {s!r}") from e
    if a < 1 or b < 1:
        raise argparse.ArgumentTypeError("LP streak sweep bounds must be >= 1")
    lo, hi = (a, b) if a <= b else (b, a)
    return (lo, hi)


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


def _objective_from_replay_result(
    res: Any,
    objective: str,
) -> float:
    if objective == "sum_ret_pct":
        return float(res.sum_hypo_ret_pct)
    if objective == "sum_ret_pct_base":
        return float(res.sum_hypo_ret_pct_base)
    if objective == "sum_pnl":
        return float(res.sum_hypo_pnl)
    raise ValueError(objective)


def _total_return_pct_compound(res: Any) -> float:
    """Whole-period return vs starting compound bankroll (percent points)."""
    fc = res.final_bankroll_cents
    sc = res.compound_start_cents
    if fc is None or sc is None or sc <= 0:
        return float("-inf")
    return (fc / sc - 1.0) * 100.0


def _parse_combo_prob_range(s: str) -> tuple[float, float, float]:
    """``LOW:HIGH:STEP`` for min-probability grid (DB scale, e.g. 90:98:2)."""
    parts = s.strip().split(":")
    if len(parts) != 3:
        raise argparse.ArgumentTypeError(
            f"Expected LOW:HIGH:STEP for combo prob grid (e.g. 90:98:2); got {s!r}"
        )
    try:
        lo, hi, step = float(parts[0]), float(parts[1]), float(parts[2])
    except ValueError as e:
        raise argparse.ArgumentTypeError(f"Invalid combo prob range {s!r}") from e
    if step <= 0:
        raise argparse.ArgumentTypeError("combo prob STEP must be positive")
    if lo > hi:
        lo, hi = hi, lo
    return (lo, hi, step)


def _prob_grid_values(lo: float, hi: float, step: float) -> list[float]:
    out: list[float] = []
    x = lo
    n = 0
    while x <= hi + 1e-9:
        out.append(round(x, 6))
        x += step
        n += 1
        if n > 50_000:
            raise ValueError("prob grid exceeded 50000 points; increase STEP")
    return out


_COMBO_GRID_MAX_EVALS = 500_000


def _filter_enriched_for_combo(
    enriched: Sequence[dict[str, Any]],
    *,
    min_prob: float,
    min_ttc: float,
    max_ttc: float,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for r in enriched:
        p = r.get("prob")
        try:
            pv = float(p) if p is not None else None
        except (TypeError, ValueError):
            pv = None
        if pv is None or pv < min_prob:
            continue
        ttc = r.get("_ttc")
        if ttc is None:
            continue
        if ttc < min_ttc or ttc > max_ttc:
            continue
        out.append(r)
    return out


def _run_combo_risk_grid_for_monitor(
    *,
    monitor: str,
    risk: dict[str, Any],
    enriched: list[dict[str, Any]],
    compound_cents: int,
    prob_lo: float,
    prob_hi: float,
    prob_step: float,
    ttc_min_range: tuple[float, float],
    ttc_max_range: tuple[float, float],
    ttc_step_seconds: float,
    lp_lo: int,
    lp_hi: int,
    min_closed_trades: int,
    apply_regime_filter: bool,
) -> tuple[list[dict[str, Any]], int, int]:
    """
    Cartesian grid: min_prob × (min_ttc,max_ttc TTC band) × LP threshold.
    Objective: maximize total return % vs compound start (final/start-1)*100.
    Returns (sorted results desc, skipped_short_filter_combos, eval_count).
    """
    prob_vals = _prob_grid_values(prob_lo, prob_hi, prob_step)
    min_grid = _minute_grid_ascending(ttc_min_range[0], ttc_min_range[1], ttc_step_seconds)
    max_grid = _minute_grid_ascending(ttc_max_range[0], ttc_max_range[1], ttc_step_seconds)
    pair_count = sum(1 for mn in min_grid for mx in max_grid if mn <= mx)
    eval_count = pair_count * len(prob_vals) * (lp_hi - lp_lo + 1)
    if eval_count > _COMBO_GRID_MAX_EVALS:
        raise ValueError(
            f"combo grid would run {eval_count} replays (cap {_COMBO_GRID_MAX_EVALS}); "
            "widen --combo-ttc-step-seconds, narrow prob/LP/TTC ranges, or raise cap in code"
        )

    results: list[dict[str, Any]] = []
    skipped_short = 0
    ran = 0
    for min_prob in prob_vals:
        for mn in min_grid:
            for mx in max_grid:
                if mn > mx:
                    continue
                filtered = _filter_enriched_for_combo(
                    enriched, min_prob=min_prob, min_ttc=mn, max_ttc=mx
                )
                closed_ct = sum(
                    1
                    for r in filtered
                    if str(r.get("status") or "").strip().lower() in ("closed", "settled")
                )
                if closed_ct < min_closed_trades:
                    skipped_short += 1
                    continue
                clean_rows = [{k: v for k, v in r.items() if k != "_ttc"} for r in filtered]
                for lp_th in range(lp_lo, lp_hi + 1):
                    res = replay_loss_prevention_threshold(
                        clean_rows,
                        risk,
                        win_streak_threshold=lp_th,
                        apply_regime_filter=apply_regime_filter,
                        compound_start_cents=compound_cents,
                    )
                    ran += 1
                    tr = _total_return_pct_compound(res)
                    results.append(
                        {
                            "monitor": monitor,
                            "min_prob": float(min_prob),
                            "min_ttc": float(mn),
                            "max_ttc": float(mx),
                            "lp_threshold": int(lp_th),
                            "total_return_pct": float(tr),
                            "sum_hypo_ret_pct": float(res.sum_hypo_ret_pct),
                            "sum_hypo_pnl": float(res.sum_hypo_pnl),
                            "final_bankroll_cents": res.final_bankroll_cents,
                            "closed_trades": int(res.closed_trades_count),
                        }
                    )
    results.sort(key=lambda r: r["total_return_pct"], reverse=True)
    return results, skipped_short, ran


def _print_combo_pool_diagnostics(enriched: Sequence[dict[str, Any]], *, ttc_timezone: str) -> None:
    """Observed prob/TTC on closed/settled rows in the wide fetch (before combo filters)."""
    probs: list[float] = []
    ttcs: list[float] = []
    for r in enriched:
        if str(r.get("status") or "").strip().lower() not in ("closed", "settled"):
            continue
        p = r.get("prob")
        try:
            if p is not None:
                probs.append(float(p))
        except (TypeError, ValueError):
            pass
        t = r.get("_ttc")
        if t is not None:
            ttcs.append(float(t))
    print("  Wide-pool diagnostics (closed/settled only, before prob/TTC grid filters):")
    if probs:
        print(
            f"    t.prob: min={min(probs):.4g} max={max(probs):.4g} "
            "(same scale as --min-prob; typically 0–100)"
        )
    else:
        print("    t.prob: (no numeric values on closed/settled rows)")
    if ttcs:
        print(
            f"    open→next-boundary TTC min ({ttc_timezone}): "
            f"min={min(ttcs):.4g} max={max(ttcs):.4g} minutes"
        )
    else:
        print(f"    TTC: (none computed; check created_at / timezone)")
    print()


def _print_combo_risk_grid_report(
    monitor: str,
    rows: list[dict[str, Any]],
    *,
    top_k: int,
    compound_usd: float,
    skipped_short: int,
    filter_lines: list[str],
    include_test_filter: bool,
    eval_count: int,
) -> None:
    print("Active filters:")
    for ln in filter_lines:
        print(f"  {ln}")
    print()
    print(
        "Combo risk grid: maximize **total return %** = (ending_bankroll / start - 1) × 100 "
        f"with compound start {_fmt_usd_from_cents(int(round(compound_usd * 100)))}."
    )
    print(
        "  Each point = filter trades by min_prob + open→next-boundary TTC band, "
        "then compound LP replay over LP win_streak_threshold."
    )
    print(
        "  Table columns are **filter settings**, not observed mins: e.g. min_prob=90 means "
        "keep rows with prob>=90; if every row is already >=95, 90–94 are equivalent. "
        "TTC max above your data max is non-binding (e.g. max=18 when all TTC<=15)."
    )
    note = (
        "Including test_filter=TRUE rows."
        if include_test_filter
        else "Excluding test_filter=TRUE rows (default)."
    )
    print(f"  {note}")
    print(
        f"  Replay evaluations: {eval_count}  "
        f"(skipped min-prob×TTC combos with too few closed: {skipped_short})"
    )
    print()

    print(f"  Top {min(top_k, len(rows))} grid points by total_return_pct")
    hdr = (
        "rank",
        "total_ret%",
        "min_prob",
        "min_ttc",
        "max_ttc",
        "lp_thr",
        "closed",
        "ending$",
    )
    show = rows[:top_k]
    body: list[list[str]] = []
    for i, r in enumerate(show, start=1):
        body.append(
            [
                str(i),
                f"{r['total_return_pct']:.4f}",
                f"{r['min_prob']:.4g}",
                f"{r['min_ttc']:.6g}",
                f"{r['max_ttc']:.6g}",
                str(r["lp_threshold"]),
                str(r["closed_trades"]),
                _fmt_usd_from_cents(r["final_bankroll_cents"]),
            ]
        )
    print(_text_table(list(hdr), body, aligns=["r"] * len(hdr), indent="  "))
    print()
    if rows:
        b = rows[0]
        print(
            "  Best: "
            f"min_prob>={b['min_prob']:.4g}  "
            f"TTC [{b['min_ttc']:.4g},{b['max_ttc']:.4g}] min  "
            f"LP streak threshold={b['lp_threshold']}  "
            f"total_ret%={b['total_return_pct']:.4f}  "
            f"ending={_fmt_usd_from_cents(b['final_bankroll_cents'])}  "
            f"closed={b['closed_trades']}"
        )


def _fmt_usd_from_cents(cents: int | None) -> str:
    if cents is None:
        return "n/a"
    return f"${cents / 100.0:,.2f}"


def _print_lp_streak_threshold_sweep_report(
    blocks: list[dict[str, Any]],
    *,
    include_test_filter: bool,
    filter_lines: list[str],
    sweep_lo: int,
    sweep_hi: int,
    apply_regime: bool,
    objective: str,
    compound_start_usd: float | None,
) -> None:
    print("Active filters:")
    for ln in filter_lines:
        print(f"  {ln}")
    print()
    print(
        "Loss-prevention + dynamic sizing replay: cycle grouping matches trade_manager "
        "(ticker prefix); position contracts match monitor_manager (percent×allotment×trade "
        "multiplier, PBA max_pct cap when performance_based_allocation is on)."
    )
    print(
        f"  Sweep win_streak_threshold: {sweep_lo}..{sweep_hi} (inclusive). "
        f"Objective: maximize {objective}."
    )
    print(
        f"  Regime pre-filter (rolling sum ret_pct): {'on' if apply_regime else 'off'} "
        "(when on, uses monitor regime_monitor_enabled / regime_window)."
    )
    note = (
        "Including test_filter=TRUE rows."
        if include_test_filter
        else "Excluding test_filter=TRUE rows (default)."
    )
    print(f"  {note}")
    if compound_start_usd is not None:
        print(
            f"  Compounding: start {_fmt_usd_from_cents(int(round(compound_start_usd * 100)))} "
            "(percent strategies size from running balance after each trade; "
            "sum_hypo_ret_pct = sum of per-trade 100×pnl/entry_balance; "
            "sum_hypo_ret_pct_base column is 0)."
        )
    print()

    for blk in blocks:
        print(f"--- {blk['monitor']} ---")
        risk = blk.get("risk") or {}
        print(
            f"  strategy={risk.get('strategy')!r}  "
            f"position={risk.get('position_size')} {risk.get('position_type')!r}  "
            f"PBA={risk.get('performance_based_allocation')}  "
            f"allotment_total_cents={risk.get('bankroll_allotment_total')}  "
            f"loss_prevention_toggle={risk.get('loss_prevention_toggle')}  "
            f"DB win_streak_threshold={risk.get('win_streak_threshold')}"
        )
        if apply_regime and risk.get("regime_monitor_enabled"):
            print(
                f"  regime: enabled  window={risk.get('regime_window')!r} "
                "(threshold sum ret_pct < 0 would be paper-only; those rows skipped)"
            )
        elif apply_regime:
            print("  regime: disabled on monitor (pre-filter is a no-op)")
        print()
        hdr = ("thr", "sum_hypo_ret_pct", "sum_hypo_ret_base", "sum_hypo_pnl", "n_closed")
        aligns = ("r", "r", "r", "r", "r")
        lines = []
        for th, rres, _score in blk["sweep_rows"]:
            lines.append(
                [
                    str(th),
                    f"{rres.sum_hypo_ret_pct:.6g}",
                    f"{rres.sum_hypo_ret_pct_base:.6g}",
                    f"{rres.sum_hypo_pnl:.2f}",
                    str(rres.closed_trades_count),
                ]
            )
        print(_text_table(list(hdr), lines, aligns=list(aligns), indent="  "))
        best = blk.get("best")
        if best:
            bth, br, bsc = best
            print()
            end_b = (
                f"  ending_bankroll={_fmt_usd_from_cents(br.final_bankroll_cents)}"
                if br.final_bankroll_cents is not None
                else ""
            )
            print(
                f"  Best threshold={bth}  {objective}={bsc:.6g}  "
                f"sum_hypo_ret_pct={br.sum_hypo_ret_pct:.6g}  "
                f"closed_trades={br.closed_trades_count}{end_b}"
            )
        cur_th = risk.get("win_streak_threshold")
        if cur_th is not None and blk.get("baseline") is not None:
            br0 = blk["baseline"]
            print()
            end0 = (
                f"  ending_bankroll={_fmt_usd_from_cents(br0.final_bankroll_cents)}"
                if br0.final_bankroll_cents is not None
                else ""
            )
            print(
                f"  At DB threshold={cur_th}: sum_hypo_ret_pct={br0.sum_hypo_ret_pct:.6g}  "
                f"sum_hypo_pnl={br0.sum_hypo_pnl:.2f}  closed={br0.closed_trades_count}{end0}"
            )
        print()


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


def _fetch_risk_replay_trade_rows(
    cur,
    monitor: str,
    start: datetime,
    end: datetime,
    test_clause: str,
    extra: TradeWhereParts,
) -> list[dict[str, Any]]:
    sql = f"""
        SELECT
            t.id, t.created_at, t.closed_at, t.status,
            t.buy_price, t.sell_price, t.position,
            t.bankroll, t.mtb_base_value, t.prob, t.paper_trade,
            t.win_loss, t.contract, t.date, t.trade_strategy,
            t.ticker, t.multiplier, t.weekly_cycle, t.ret_pct
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


def _fmt_ingest_duration(seconds: float) -> str:
    """Human-readable duration for ingest progress (non-negative seconds)."""
    if seconds < 0 or seconds != seconds:  # NaN
        return "?"
    s = int(round(seconds))
    if s >= 3600:
        return f"{s // 3600}h{(s % 3600) // 60}m"
    if s >= 60:
        return f"{s // 60}m{s % 60}s"
    return f"{max(0, s)}s"


_KALSHI_INGEST_CALIBRATE_N = 5
_KALSHI_INGEST_QUIET_SUCCESS_THRESHOLD = 12
_KALSHI_INGEST_PROGRESS_INTERVAL_DEFAULT_S = 0.75
_KALSHI_INGEST_PROGRESS_INTERVAL_MIN_S = 0.15
_KALSHI_INGEST_PROGRESS_INTERVAL_MAX_S = 30.0


def _kalshi_ingest_progress_interval_s() -> float:
    """Wall-clock spacing between progress lines (fluid UI); override with ``REC_IO_KALSHI_INGEST_PROGRESS_INTERVAL_S``."""
    raw = (os.getenv("REC_IO_KALSHI_INGEST_PROGRESS_INTERVAL_S") or "").strip()
    if raw:
        try:
            v = float(raw)
            return max(
                _KALSHI_INGEST_PROGRESS_INTERVAL_MIN_S,
                min(v, _KALSHI_INGEST_PROGRESS_INTERVAL_MAX_S),
            )
        except ValueError:
            pass
    return _KALSHI_INGEST_PROGRESS_INTERVAL_DEFAULT_S


def _run_ingest_kalshi_tickers(
    tickers: list[str],
    *,
    include_spot: bool = True,
    print_contract_banner: bool = True,
    pause_seconds: float = 0.0,
    batch_label: str | None = None,
    verbose: bool = False,
) -> int:
    """Fetch Kalshi candles + market metadata (+ optional spot history) into ``backtest``."""
    from scripts.backtest.helpers.kalshi_candles_1m import (
        qualified_backtest_candles_table,
        run_fill_backtest_candles_with_meta,
    )

    if print_contract_banner:
        print(
            "Backtest row contract (facts vs bounds, conservative replay): "
            "see **Backtest row contract** in this file's module docstring "
            "(scripts/backtest/core_backtester.py)."
        )
    queue = [x.strip() for x in tickers if x.strip()]
    n_total = len(queue)
    if n_total == 0:
        return 0
    quiet_success = (not verbose) and n_total >= _KALSHI_INGEST_QUIET_SUCCESS_THRESHOLD
    progress_interval_s = _kalshi_ingest_progress_interval_s()
    cal_samples = min(_KALSHI_INGEST_CALIBRATE_N, n_total)
    prefix = f"{batch_label} — " if batch_label else ""
    if n_total > 1:
        print(
            f"Kalshi ingest: {prefix}{n_total} market(s). "
            f"Projected **full run** from mean of first {cal_samples} table(s) (~{_KALSHI_INGEST_CALIBRATE_N} max); "
            f"progress ~every {progress_interval_s:g}s (and on completion). "
            f"Wall time = HTTP + DB + commit"
            + (" + pause." if pause_seconds > 0 else ".")
        )
    conn = get_connection()
    ingested_n = 0
    skipped_n = 0
    t_batch0 = time.monotonic()
    last_progress_mono = t_batch0
    per_market_seconds: list[float] = []
    calibrated_s: float | None = None
    try:
        for idx, tt in enumerate(queue, start=1):
            t0 = time.perf_counter()
            fq = qualified_backtest_candles_table(tt)
            res = run_fill_backtest_candles_with_meta(conn, tt, include_spot=include_spot)
            conn.commit()
            if res.skipped:
                skipped_n += 1
                print(f"{tt}: skipped — {res.skip_reason}")
            else:
                ingested_n += 1
                if not quiet_success:
                    spot_note = (
                        f", price_history_minutes={res.price_history_hits}/{res.row_count}"
                        if include_spot
                        else ""
                    )
                    print(
                        f"{tt}: ingested {res.row_count} rows -> {fq} "
                        f"(metadata_source={res.metadata_source}, open_ts={res.open_ts}, close_ts={res.close_ts}"
                        f"{spot_note})"
                    )
            if pause_seconds > 0:
                time.sleep(pause_seconds)
            dt = time.perf_counter() - t0
            per_market_seconds.append(dt)

            just_calibrated = False
            if calibrated_s is None and len(per_market_seconds) >= cal_samples:
                calibrated_s = sum(per_market_seconds[:cal_samples]) / float(cal_samples)
                proj_full = n_total * calibrated_s
                print(
                    f"  Calibrated ~{calibrated_s:.1f}s/table (mean of first {cal_samples}) — "
                    f"projected **entire run** ~{_fmt_ingest_duration(proj_full)} for all {n_total} tables."
                )
                just_calibrated = True

            if n_total <= 1:
                continue

            elapsed = time.monotonic() - t_batch0
            pct = 100.0 * idx / n_total
            if calibrated_s is not None:
                eta_rem = (n_total - idx) * calibrated_s
                rate_label = f"~{calibrated_s:.1f}s/table (fixed est. from first {cal_samples})"
            else:
                run_avg = sum(per_market_seconds) / len(per_market_seconds)
                eta_rem = (n_total - idx) * run_avg
                rate_label = f"~{run_avg:.1f}s/table (provisional)"

            now = time.monotonic()
            due_by_time = (now - last_progress_mono) >= progress_interval_s
            print_progress = just_calibrated or idx == n_total or due_by_time

            if print_progress:
                last_progress_mono = now
                phase = "calibrated" if calibrated_s is not None else "provisional"
                el_sec = int(round(max(0.0, elapsed)))
                eta_sec = int(round(max(0.0, eta_rem)))
                eta_total_s = el_sec + eta_sec
                print(
                    f"  Progress {idx}/{n_total} ({pct:.2f}%) — elapsed {_fmt_ingest_duration(elapsed)} — "
                    f"ETA remaining ~{_fmt_ingest_duration(eta_rem)} — {rate_label} | "
                    f"kalshi_ingest idx={idx} total={n_total} pct={pct:.3f} elapsed_s={el_sec} "
                    f"eta_rem_s={eta_sec} eta_total_s={eta_total_s} phase={phase}"
                )
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    batch_wall = time.monotonic() - t_batch0
    if n_total >= 2 or skipped_n > 0:
        print(
            f"Ingest summary: {ingested_n} ingested, {skipped_n} skipped "
            f"(of {n_total} candidate(s)); batch wall time {_fmt_ingest_duration(batch_wall)}."
        )
    elif n_total == 1:
        print(f"Ingest complete (1 market); wall time {_fmt_ingest_duration(batch_wall)}.")
    return 0


def _run_ingest_kalshi_trading_day(
    series_ticker: str,
    trading_day_yyyy_mm_dd: str,
    *,
    include_spot: bool = True,
    pause_seconds: float = 0.0,
    verbose: bool = False,
) -> int:
    """
    Ingest **96** synthetic ``KX*15M`` tickers for one Eastern calendar day (``trade.date`` label).

    Does not call ``GET /markets`` for discovery; each ticker is still validated by Kalshi when
    fetching candles and market metadata.
    """
    from scripts.backtest.helpers.kalshi_ticker_construct import (
        kalshi_15m_market_tickers_for_eastern_date,
        parse_eastern_trading_day_arg,
    )

    try:
        d = parse_eastern_trading_day_arg(trading_day_yyyy_mm_dd)
        tickers = kalshi_15m_market_tickers_for_eastern_date(series_ticker, d)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    print(
        "Backtest row contract (facts vs bounds, conservative replay): "
        "see **Backtest row contract** in this file's module docstring "
        "(scripts/backtest/core_backtester.py)."
    )
    st = series_ticker.strip()
    print(
        f"{st}: synthetic Eastern trading day {trading_day_yyyy_mm_dd} — "
        f"{len(tickers)} 15m slot(s) (America/New_York calendar; aligns with trade.date)."
    )
    return _run_ingest_kalshi_tickers(
        tickers,
        include_spot=include_spot,
        print_contract_banner=False,
        pause_seconds=pause_seconds,
        batch_label=f"{st} {trading_day_yyyy_mm_dd}",
        verbose=verbose,
    )


def _run_ingest_kalshi_trading_day_range(
    series_ticker: str,
    start_yyyy_mm_dd: str,
    end_yyyy_mm_dd: str,
    *,
    include_spot: bool = True,
    pause_seconds: float = 0.0,
    verbose: bool = False,
) -> int:
    """
    Ingest synthetic ``KX*15M`` tickers for each Eastern calendar day from start through end inclusive
    (96 per day). One batch: single calibration and **full-run** ETA for all tables.
    """
    from scripts.backtest.helpers.kalshi_ticker_construct import (
        kalshi_15m_market_tickers_for_eastern_date_range,
        parse_eastern_trading_day_arg,
    )

    try:
        d0 = parse_eastern_trading_day_arg(start_yyyy_mm_dd)
        d1 = parse_eastern_trading_day_arg(end_yyyy_mm_dd)
        tickers = kalshi_15m_market_tickers_for_eastern_date_range(series_ticker, d0, d1)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    st = series_ticker.strip()
    n_days = (d1 - d0).days + 1
    print(
        "Backtest row contract (facts vs bounds, conservative replay): "
        "see **Backtest row contract** in this file's module docstring "
        "(scripts/backtest/core_backtester.py)."
    )
    print(
        f"{st}: synthetic Eastern trading-day range {start_yyyy_mm_dd} .. {end_yyyy_mm_dd} "
        f"({n_days} calendar day(s), America/New_York) — {len(tickers)} 15m market(s)."
    )
    return _run_ingest_kalshi_tickers(
        tickers,
        include_spot=include_spot,
        print_contract_banner=False,
        pause_seconds=pause_seconds,
        batch_label=f"{st} {start_yyyy_mm_dd}..{end_yyyy_mm_dd} ({n_days}d)",
        verbose=verbose,
    )


def _run_ingest_kalshi_series_close_window(
    series_ticker: str,
    close_start: datetime,
    close_end: datetime,
    *,
    include_spot: bool = True,
    pause_seconds: float = 0.0,
    verbose: bool = False,
) -> int:
    """Discover markets via Kalshi GET /markets, then run the same ingest loop as explicit tickers."""
    from scripts.backtest.helpers.kalshi_candles_1m import discover_market_tickers_by_series_close_window

    min_u = int(close_start.astimezone(timezone.utc).timestamp())
    max_u = int(close_end.astimezone(timezone.utc).timestamp())
    if min_u >= max_u:
        print(
            "error: --ingest-kalshi-close-end must be after --ingest-kalshi-close-start",
            file=sys.stderr,
        )
        return 2
    try:
        tickers = discover_market_tickers_by_series_close_window(series_ticker, min_u, max_u)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    st = series_ticker.strip()
    print(
        "Backtest row contract (facts vs bounds, conservative replay): "
        "see **Backtest row contract** in this file's module docstring "
        "(scripts/backtest/core_backtester.py)."
    )
    print(
        f"{st}: discovered {len(tickers)} market(s) "
        f"(GET /markets series_ticker + min_close_ts={min_u} max_close_ts={max_u})."
    )
    if not tickers:
        return 0
    return _run_ingest_kalshi_tickers(
        tickers,
        include_spot=include_spot,
        print_contract_banner=False,
        pause_seconds=pause_seconds,
        batch_label=f"{st} close {min_u}..{max_u}",
        verbose=verbose,
    )


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--build-tick-backtest",
        default=None,
        metavar="TICKER",
        help=(
            "If set: build backtest.tick_backtest_<slug> for one ticker (strike_table_15m-shaped columns; "
            "trade-based asks). Uses live 1s price log + kalshi_historical_trades_api; optional "
            "backtest_1m_<slug> for volume_fp/open_interest_fp. Then exit. Mutually exclusive with Kalshi ingest."
        ),
    )
    p.add_argument(
        "--ingest-kalshi-tickers",
        nargs="+",
        metavar="TICKER",
        default=None,
        help=(
            "If set: for each Kalshi market ticker, upsert 1m candles + floor_strike/market_result "
            "into backtest.backtest_1m_<slug> (creates table if needed); then exit. "
            "Skips a ticker when Kalshi has no 1m candles for the window, or (unless --ingest-no-spot) "
            "when KXBTC*/KXETH* is missing any matching minute in historical_data.*_price_history. "
            "KXBTC* / KXETH* tickers also join price_history (open, high, …). "
            "Omit --monitors / --start / --end when using this. For 15m full Eastern days, "
            "prefer --ingest-kalshi-trading-day (96 synthetic tickers, no discovery). "
            "Row semantics: see module docstring **Backtest row contract**."
        ),
    )
    p.add_argument(
        "--ingest-kalshi-series",
        default=None,
        metavar="SERIES",
        help=(
            "Kalshi series_ticker (e.g. KXBTC15M). With --ingest-kalshi-close-start and "
            "--ingest-kalshi-close-end, lists markets via GET /markets (close-time window), "
            "then ingests each. For full 15m Eastern days use --ingest-kalshi-trading-day or "
            "--ingest-kalshi-trading-day-range instead. Mutually exclusive with other ingest modes."
        ),
    )
    p.add_argument(
        "--ingest-kalshi-close-start",
        type=_parse_instant,
        default=None,
        help=(
            "ISO-8601 (timezone required). Kalshi min_close_ts (UTC epoch) for --ingest-kalshi-series."
        ),
    )
    p.add_argument(
        "--ingest-kalshi-close-end",
        type=_parse_instant,
        default=None,
        help=(
            "ISO-8601 (timezone required). Kalshi max_close_ts (UTC epoch) for --ingest-kalshi-series."
        ),
    )
    p.add_argument(
        "--ingest-kalshi-trading-day",
        nargs=2,
        metavar=("SERIES", "YYYY-MM-DD"),
        default=None,
        help=(
            "Synthetic **96** KX*15M tickers for Eastern calendar YYYY-MM-DD (trade.date / "
            "America/New_York), then ingest each. No GET /markets discovery. Use "
            "--ingest-kalshi-trading-day-range for many days in one batch. Mutually exclusive "
            "with --ingest-kalshi-tickers, --ingest-kalshi-trading-day-range, and "
            "--ingest-kalshi-series. Not for hourly -T markets."
        ),
    )
    p.add_argument(
        "--ingest-kalshi-trading-day-range",
        nargs=3,
        metavar=("SERIES", "START_YYYY-MM-DD", "END_YYYY-MM-DD"),
        default=None,
        help=(
            "Synthetic KX*15M tickers for each Eastern calendar day from START through END inclusive "
            "(**96 × number of days**). Single ingest batch: one calibrated **full-run** ETA. "
            "Mutually exclusive with other ingest modes."
        ),
    )
    p.add_argument(
        "--ingest-kalshi-pause-seconds",
        type=float,
        default=0.0,
        metavar="SEC",
        help=(
            "Sleep SEC after each market during Kalshi ingest (0 default). Use small values "
            "if the API is throttling; accuracy unchanged (only pacing)."
        ),
    )
    p.add_argument(
        "--ingest-no-spot",
        action="store_true",
        help=(
            "With Kalshi ingest: do not join btc/eth price_history (leave open/high/… NULL); "
            "also skips the full-coverage spot preflight for KXBTC*/KXETH*."
        ),
    )
    p.add_argument(
        "--ingest-kalshi-verbose",
        action="store_true",
        help=(
            "With Kalshi ingest: print every successful market line (default: quiet for large batches)."
        ),
    )
    p.add_argument(
        "--replay-htc-market",
        default=None,
        metavar="TICKER",
        help=(
            "Single-market HTC gate replay on ``backtest.backtest_1m_<slug>`` (default), or on "
            "``backtest.tick_backtest_<slug>`` when ``--replay-from-tick-backtest`` is set. Entry "
            "settings from ``users.strategy_list_<user>`` (default: ``15m HTC`` or ``Hourly HTC`` "
            "from ticker), unless ``--replay-monitor-id`` is set (then ``users.monitor_list_<user>``). "
            "Bankroll from --replay-bankroll / --replay-allocation-pct; prints JSON and exits. "
            "Omit --monitors / --start / --end. Mutually exclusive with Kalshi ingest modes."
        ),
    )
    p.add_argument(
        "--replay-from-tick-backtest",
        action="store_true",
        help=(
            "With --replay-htc-market only: scan ``backtest.tick_backtest_<slug>`` chronologically "
            "(1s strike-shaped rows) for AES entry + ATS exits instead of 1m candle bars. "
            "Build the table first with --build-tick-backtest."
        ),
    )
    p.add_argument(
        "--replay-htc-range",
        action="store_true",
        help=(
            "Sequential HTC replay: every ``backtest.backtest_1m_*`` table overlapping "
            "``[--start, --end)`` (Eastern-naive bar timestamps), ordered by first bar. "
            "Settings from ``users.strategy_list_<user>`` (--replay-strategy, default ``15m HTC``); "
            "``--replay-allocation-pct`` (default 20) sizes each entry as that percent of spendable "
            "balance (same as --replay-htc-market). Loss prevention from strategy row. "
            "Fresh in-memory bankroll (--replay-bankroll). "
            "By default, runs Kalshi synthetic trading-day ingest for each overlapping Eastern "
            "calendar day (``--replay-htc-ingest-series``, default KXBTC15M) so ``backtest`` tables "
            "exist; use --replay-htc-skip-ingest if already filled. "
            "Requires --start and --end. Mutually exclusive with --replay-htc-market and "
            "top-level Kalshi ingest flags."
        ),
    )
    p.add_argument(
        "--replay-htc-skip-ingest",
        action="store_true",
        help=(
            "With --replay-htc-range: skip pre-flight ``--ingest-kalshi-trading-day`` per overlapping "
            "Eastern date (default is to create/fill tables first)."
        ),
    )
    p.add_argument(
        "--replay-htc-ingest-series",
        default="KXBTC15M",
        metavar="SERIES",
        help=(
            "With --replay-htc-range: Kalshi 15m series ticker for synthetic trading-day ingest "
            "before replay (default KXBTC15M). No effect with --replay-htc-skip-ingest."
        ),
    )
    p.add_argument(
        "--replay-bankroll",
        type=float,
        default=10_000.0,
        metavar="USD",
        help="Starting bankroll for --replay-htc-market / --replay-htc-range (default 10000).",
    )
    p.add_argument(
        "--replay-allocation-pct",
        type=float,
        default=20.0,
        metavar="PCT",
        help=(
            "Percent of bankroll (single-market) or spend cap (range) per entry for "
            "--replay-htc-market / --replay-htc-range (default 20)."
        ),
    )
    p.add_argument(
        "--replay-monitor-id",
        type=int,
        default=None,
        metavar="ID",
        help=(
            "Optional: use ``users.monitor_list_<user>``.id for entry settings instead of "
            "``strategy_list_<user>`` (mutually exclusive with --replay-strategy)."
        ),
    )
    p.add_argument(
        "--replay-strategy",
        default=None,
        metavar="NAME",
        help=(
            "Optional: ``users.strategy_list_<user>``.name for entry settings (e.g. ``\"15m HTC\"``). "
            "Default when --replay-monitor-id is omitted: inferred from ticker (15m vs hourly). "
            "Mutually exclusive with --replay-monitor-id."
        ),
    )
    p.add_argument(
        "--replay-monitor-user",
        default="0001",
        metavar="USER",
        help=(
            "Digits-only user suffix for ``strategy_list_<USER>`` / ``monitor_list_<USER>`` "
            "(default 0001)."
        ),
    )
    p.add_argument(
        "--replay-gate-profile",
        choices=("full", "simulated_15m"),
        default="full",
        help="Gate profile passed to hourly HTC evaluator (default full).",
    )
    p.add_argument(
        "--replay-spike-alert-active",
        action="store_true",
        help="Treat spike cooldown as active for min_probability adjustment in --replay-htc-market.",
    )
    p.add_argument(
        "--monitors",
        type=_parse_monitors,
        default=None,
        help=(
            "Comma-separated monitor names (e.g. mon_0001_1,mon_0001_2); required unless "
            "Kalshi ingest (--ingest-kalshi-tickers, --ingest-kalshi-trading-day, "
            "--ingest-kalshi-trading-day-range, or --ingest-kalshi-series + close range) "
            "or --replay-htc-market / --replay-htc-range"
        ),
    )
    p.add_argument(
        "--start",
        type=_parse_instant,
        default=None,
        help=(
            "ISO-8601 start (inclusive); required unless using Kalshi ingest modes "
            "(--ingest-kalshi-tickers / --ingest-kalshi-trading-day / --ingest-kalshi-series) "
            "or --replay-htc-market; required with --replay-htc-range"
        ),
    )
    p.add_argument(
        "--end",
        type=_parse_instant,
        default=None,
        help=(
            "ISO-8601 end (exclusive); required unless using Kalshi ingest modes "
            "(--ingest-kalshi-tickers / --ingest-kalshi-trading-day / --ingest-kalshi-series) "
            "or --replay-htc-market; required with --replay-htc-range"
        ),
    )
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
        help=(
            "Minimum t.prob for trade SQL filters (DB scale, typically 0–100). "
            "With --replay-htc-range / --replay-htc-market, also overrides strategy/monitor "
            "min_probability when set."
        ),
    )
    p.add_argument(
        "--max-prob",
        type=float,
        default=None,
        help=(
            "Maximum t.prob for trade SQL filters (DB scale). "
            "With --replay-htc-range / --replay-htc-market, also overrides max_probability when set."
        ),
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
    p.add_argument(
        "--lp-streak-threshold-sweep",
        type=_parse_lp_streak_sweep,
        default=None,
        metavar="LOW:HIGH",
        help=(
            "Replay loss prevention + dynamic sizing (monitor percent/contracts × each trade's "
            "multiplier, PBA max_pct cap). Sweep integer win_streak_threshold from LOW through "
            "HIGH inclusive; rank by --lp-sweep-objective. Mutually exclusive with "
            "--hypothetical-position and TTC optimization/sweep flags."
        ),
    )
    p.add_argument(
        "--lp-sweep-apply-regime",
        action="store_true",
        help=(
            "With --lp-streak-threshold-sweep: drop trades that would be paper-only under "
            "regime_monitor (rolling sum of prior ret_pct in regime_window < 0)."
        ),
    )
    p.add_argument(
        "--lp-sweep-objective",
        choices=("sum_ret_pct", "sum_ret_pct_base", "sum_pnl"),
        default="sum_ret_pct",
        help="Metric to maximize for --lp-streak-threshold-sweep (default sum_ret_pct).",
    )
    p.add_argument(
        "--compound-start-usd",
        type=float,
        default=None,
        metavar="USD",
        help=(
            "Starting bankroll in US dollars for compound replay (e.g. 5000). Required with "
            "--combo-risk-grid; with --lp-streak-threshold-sweep optional. "
            "Trades run in global time order; balance compounds after each closed trade; "
            "percent sizing uses the running balance."
        ),
    )
    p.add_argument(
        "--combo-risk-grid",
        action="store_true",
        help=(
            "Grid search: (--combo-min-prob-range) × TTC band × (--combo-lp-range) LP thresholds. "
            "Requires --compound-start-usd. Maximizes total return %% = (final/start-1)×100. "
            "One DB fetch per monitor; filters in Python. Mutually exclusive with LP sweep, "
            "hypothetical position, and TTC optimize/sweep."
        ),
    )
    p.add_argument(
        "--combo-min-prob-range",
        type=_parse_combo_prob_range,
        default=_parse_combo_prob_range("90:98:2"),
        metavar="LO:HI:STEP",
        help="Min t.prob grid (DB scale). Default 90:98:2.",
    )
    p.add_argument(
        "--combo-lp-range",
        type=_parse_lp_streak_sweep,
        default=_parse_lp_streak_sweep("1:30"),
        metavar="LO:HI",
        help="Inclusive LP win_streak_threshold sweep. Default 1:30.",
    )
    p.add_argument(
        "--combo-ttc-min-range",
        type=_parse_max_ttc_sweep,
        default=(0.0, 30.0),
        metavar="LO:HI",
        help="Grid axis for MIN open→next-boundary TTC (minutes). Default 0:30.",
    )
    p.add_argument(
        "--combo-ttc-max-range",
        type=_parse_max_ttc_sweep,
        default=(0.0, 30.0),
        metavar="LO:HI",
        help="Grid axis for MAX open→next-boundary TTC (minutes). Default 0:30.",
    )
    p.add_argument(
        "--combo-ttc-step-seconds",
        type=_parse_grid_step_seconds,
        default=180.0,
        metavar="SEC",
        help="Step for both TTC axes on the combo grid (default 180 = 3 min). Minimum 1.",
    )
    p.add_argument(
        "--combo-min-closed-trades",
        type=int,
        default=30,
        metavar="K",
        help="Skip a (min_prob,TTC band) slice if fewer than K closed/settled trades (default 30).",
    )
    p.add_argument(
        "--combo-top",
        type=int,
        default=25,
        metavar="N",
        help="Print top N grid points per monitor (default 25).",
    )
    args = p.parse_args(argv)

    ingest_mode_count = (
        (1 if args.ingest_kalshi_tickers else 0)
        + (1 if args.ingest_kalshi_series else 0)
        + (1 if args.ingest_kalshi_trading_day else 0)
        + (1 if args.ingest_kalshi_trading_day_range else 0)
    )
    if ingest_mode_count > 1:
        p.error(
            "choose at most one: --ingest-kalshi-tickers, --ingest-kalshi-trading-day, "
            "--ingest-kalshi-trading-day-range, or --ingest-kalshi-series (with close range)"
        )
    if args.ingest_kalshi_pause_seconds < 0:
        p.error("--ingest-kalshi-pause-seconds must be >= 0")
    if (args.ingest_kalshi_close_start is not None or args.ingest_kalshi_close_end is not None) and (
        not args.ingest_kalshi_series
    ):
        p.error("--ingest-kalshi-close-start / --ingest-kalshi-close-end require --ingest-kalshi-series")
    if args.ingest_kalshi_series:
        if args.ingest_kalshi_close_start is None or args.ingest_kalshi_close_end is None:
            p.error(
                "--ingest-kalshi-series requires --ingest-kalshi-close-start and --ingest-kalshi-close-end"
            )
        return _run_ingest_kalshi_series_close_window(
            args.ingest_kalshi_series,
            args.ingest_kalshi_close_start,
            args.ingest_kalshi_close_end,
            include_spot=not args.ingest_no_spot,
            pause_seconds=args.ingest_kalshi_pause_seconds,
            verbose=args.ingest_kalshi_verbose,
        )

    if args.ingest_kalshi_trading_day:
        ser, ymd = args.ingest_kalshi_trading_day
        return _run_ingest_kalshi_trading_day(
            ser,
            ymd,
            include_spot=not args.ingest_no_spot,
            pause_seconds=args.ingest_kalshi_pause_seconds,
            verbose=args.ingest_kalshi_verbose,
        )

    if args.ingest_kalshi_trading_day_range:
        ser, ymd0, ymd1 = args.ingest_kalshi_trading_day_range
        return _run_ingest_kalshi_trading_day_range(
            ser,
            ymd0,
            ymd1,
            include_spot=not args.ingest_no_spot,
            pause_seconds=args.ingest_kalshi_pause_seconds,
            verbose=args.ingest_kalshi_verbose,
        )

    if args.ingest_kalshi_tickers:
        return _run_ingest_kalshi_tickers(
            args.ingest_kalshi_tickers,
            include_spot=not args.ingest_no_spot,
            pause_seconds=args.ingest_kalshi_pause_seconds,
            verbose=args.ingest_kalshi_verbose,
        )

    if args.build_tick_backtest:
        if ingest_mode_count:
            p.error("--build-tick-backtest cannot combine with Kalshi ingest modes")
        tkr = (args.build_tick_backtest or "").strip()
        if not tkr:
            p.error("--build-tick-backtest requires a non-empty ticker")
        from scripts.backtest.helpers.tick_backtest_build import build_tick_backtest_table

        conn = get_connection()
        try:
            out = build_tick_backtest_table(conn, tkr)
        finally:
            conn.close()
        print(json.dumps(out, indent=2, default=str))
        return 0

    if args.replay_htc_range:
        if ingest_mode_count:
            p.error("--replay-htc-range cannot be combined with Kalshi ingest modes")
        if args.replay_htc_market:
            p.error("use at most one of --replay-htc-range or --replay-htc-market")
        if args.start is None or args.end is None:
            p.error("--replay-htc-range requires --start and --end (timezone-aware ISO-8601)")
        if args.end <= args.start:
            print("error: --end must be after --start", file=sys.stderr)
            return 2
        if args.replay_bankroll <= 0:
            p.error("--replay-bankroll must be positive")
        if not (0.0 < args.replay_allocation_pct <= 100.0):
            p.error("--replay-allocation-pct must be in (0, 100]")
        mu = str(args.replay_monitor_user).strip()
        if not mu.isdigit():
            p.error("--replay-monitor-user must be digits only (e.g. 0001)")
        sname = (args.replay_strategy or "15m HTC").strip()
        if not sname:
            p.error("--replay-strategy cannot be empty when set")

        if not args.replay_htc_skip_ingest:
            from scripts.backtest.helpers.htc_range_replay import eastern_calendar_days_overlapping_range

            ser = (args.replay_htc_ingest_series or "").strip()
            if not ser:
                p.error("--replay-htc-ingest-series must be non-empty when ingest is enabled")
            days = eastern_calendar_days_overlapping_range(args.start, args.end)
            if not days:
                print(
                    "warning: no Eastern calendar days overlap [--start, --end); "
                    "ingest skipped",
                    file=sys.stderr,
                )
            for d in days:
                ymd = d.strftime("%Y-%m-%d")
                print(
                    f"[replay-htc-range] ingest {ser} Eastern trading day {ymd} …",
                    file=sys.stderr,
                    flush=True,
                )
                rc = _run_ingest_kalshi_trading_day(
                    ser,
                    ymd,
                    include_spot=not args.ingest_no_spot,
                    pause_seconds=args.ingest_kalshi_pause_seconds,
                    verbose=args.ingest_kalshi_verbose,
                )
                if rc != 0:
                    return rc

        from scripts.backtest.helpers.htc_range_replay import run_htc_strategy_range_replay

        conn = get_connection()
        try:
            out = run_htc_strategy_range_replay(
                conn,
                start=args.start,
                end=args.end,
                starting_bankroll=float(args.replay_bankroll),
                strategy_name=sname,
                strategy_table=f"strategy_list_{mu}",
                replay_user=mu,
                spike_alert_active=bool(args.replay_spike_alert_active),
                gate_profile=str(args.replay_gate_profile),
                allocation_pct=float(args.replay_allocation_pct),
                min_probability_override=float(args.min_prob)
                if args.min_prob is not None
                else None,
                max_probability_override=float(args.max_prob)
                if args.max_prob is not None
                else None,
            )
        finally:
            conn.close()
        print(json.dumps(out, indent=2, default=str))
        return 0

    if args.replay_from_tick_backtest and not args.replay_htc_market:
        p.error("--replay-from-tick-backtest requires --replay-htc-market")
    if args.replay_htc_range and args.replay_from_tick_backtest:
        p.error("--replay-from-tick-backtest cannot be combined with --replay-htc-range")

    if args.replay_htc_market:
        if ingest_mode_count:
            p.error("--replay-htc-market cannot be combined with Kalshi ingest modes")
        if args.replay_bankroll <= 0:
            p.error("--replay-bankroll must be positive")
        if not (0.0 < args.replay_allocation_pct <= 100.0):
            p.error("--replay-allocation-pct must be in (0, 100]")
        ticker = args.replay_htc_market.strip()
        if not ticker:
            p.error("--replay-htc-market must be a non-empty ticker")
        mu = str(args.replay_monitor_user).strip()
        if not mu.isdigit():
            p.error("--replay-monitor-user must be digits only (e.g. 0001)")
        if args.replay_monitor_id is not None and args.replay_strategy:
            p.error("use at most one of --replay-monitor-id or --replay-strategy")
        conn = get_connection()
        try:
            if args.replay_monitor_id is not None:
                stg = fetch_monitor_auto_entry_settings(
                    conn,
                    monitor_table=f"monitor_list_{mu}",
                    monitor_id=int(args.replay_monitor_id),
                )
                if args.min_prob is not None or args.max_prob is not None:
                    stg = dict(stg)
                    if args.min_prob is not None:
                        stg["min_probability"] = float(args.min_prob)
                    if args.max_prob is not None:
                        stg["max_probability"] = float(args.max_prob)
                out = run_htc_single_market_replay(
                    conn,
                    market_ticker=ticker,
                    bankroll=float(args.replay_bankroll),
                    allocation_pct=float(args.replay_allocation_pct),
                    entry_settings=stg,
                    entry_settings_source="monitor_list",
                    replay_user=mu,
                    monitor_id=int(args.replay_monitor_id),
                    spike_alert_active=bool(args.replay_spike_alert_active),
                    gate_profile=str(args.replay_gate_profile),
                    from_tick_table=bool(args.replay_from_tick_backtest),
                )
            else:
                sname = (args.replay_strategy or infer_strategy_list_name_for_kalshi_ticker(ticker)).strip()
                if not sname:
                    p.error("--replay-strategy (or inferable ticker) is required without --replay-monitor-id")
                stg = fetch_strategy_auto_entry_settings(
                    conn,
                    strategy_table=f"strategy_list_{mu}",
                    strategy_name=sname,
                )
                if args.min_prob is not None or args.max_prob is not None:
                    stg = dict(stg)
                    if args.min_prob is not None:
                        stg["min_probability"] = float(args.min_prob)
                    if args.max_prob is not None:
                        stg["max_probability"] = float(args.max_prob)
                out = run_htc_single_market_replay(
                    conn,
                    market_ticker=ticker,
                    bankroll=float(args.replay_bankroll),
                    allocation_pct=float(args.replay_allocation_pct),
                    entry_settings=stg,
                    entry_settings_source="strategy_list",
                    replay_user=mu,
                    strategy_name=sname,
                    spike_alert_active=bool(args.replay_spike_alert_active),
                    gate_profile=str(args.replay_gate_profile),
                    from_tick_table=bool(args.replay_from_tick_backtest),
                )
        finally:
            conn.close()
        print(json.dumps(out, indent=2, default=str))
        return 0

    if args.monitors is None or args.start is None or args.end is None:
        p.error(
            "the following arguments are required: --monitors, --start, --end "
            "(unless using --ingest-kalshi-tickers, --ingest-kalshi-trading-day, "
            "--ingest-kalshi-trading-day-range, --ingest-kalshi-series, "
            "--replay-htc-market, or --replay-htc-range)"
        )

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

    if args.compound_start_usd is not None:
        if args.lp_streak_threshold_sweep is None and not args.combo_risk_grid:
            print(
                "error: --compound-start-usd requires --lp-streak-threshold-sweep or --combo-risk-grid",
                file=sys.stderr,
            )
            return 2
        if args.compound_start_usd <= 0:
            print("error: --compound-start-usd must be positive", file=sys.stderr)
            return 2

    if args.combo_risk_grid:
        if args.compound_start_usd is None:
            print(
                "error: --combo-risk-grid requires --compound-start-usd",
                file=sys.stderr,
            )
            return 2
        if args.lp_streak_threshold_sweep is not None:
            print(
                "error: use either --combo-risk-grid or --lp-streak-threshold-sweep, not both",
                file=sys.stderr,
            )
            return 2
        if args.hypothetical_position is not None:
            print(
                "error: --combo-risk-grid cannot be combined with --hypothetical-position",
                file=sys.stderr,
            )
            return 2
        if args.optimize_ttc_window:
            print(
                "error: --combo-risk-grid cannot be combined with --optimize-ttc-window",
                file=sys.stderr,
            )
            return 2
        if args.max_ttc_sweep is not None:
            print(
                "error: --combo-risk-grid cannot be combined with --max-ttc-sweep",
                file=sys.stderr,
            )
            return 2
        if args.min_prob is not None or args.max_prob is not None:
            print(
                "error: --combo-risk-grid uses --combo-min-prob-range; "
                "do not pass --min-prob or --max-prob",
                file=sys.stderr,
            )
            return 2
        if args.min_ttc_minutes is not None or args.max_ttc_minutes is not None:
            print(
                "error: --combo-risk-grid uses --combo-ttc-*-range; "
                "do not pass --min-ttc-minutes or --max-ttc-minutes",
                file=sys.stderr,
            )
            return 2
        if args.combo_top < 1:
            print("error: --combo-top must be >= 1", file=sys.stderr)
            return 2
        if args.combo_min_closed_trades < 1:
            print("error: --combo-min-closed-trades must be >= 1", file=sys.stderr)
            return 2

        compound_cents = int(round(float(args.compound_start_usd) * 100.0))
        if compound_cents < 1:
            print("error: --compound-start-usd rounds to < 1 cent", file=sys.stderr)
            return 2
        pl_lo, pl_hi = args.combo_lp_range
        prob_lo, prob_hi, prob_step = args.combo_min_prob_range
        test_clause = _test_clause(args.include_test_filter)
        conn = get_connection()
        try:
            with conn.cursor() as cur:
                for monitor in args.monitors:
                    parsed = parse_monitor_token(monitor)
                    if not parsed:
                        print(f"error: cannot parse monitor label {monitor!r}", file=sys.stderr)
                        return 2
                    u, mid = parsed
                    risk = fetch_monitor_risk_settings(cur, u, mid)
                    if not risk:
                        print(
                            f"error: no monitor_list row for {monitor} (user {u} id {mid})",
                            file=sys.stderr,
                        )
                        return 2
                    strategy = risk.get("strategy")
                    grid_15m = strategy_implies_15m_ttc_grid(strategy)
                    extra = build_trade_where_parts(
                        paper_mode=args.paper,
                        min_prob=None,
                        max_prob=None,
                        min_ttc_minutes=None,
                        max_ttc_minutes=None,
                        ttc_timezone=args.ttc_timezone,
                        ttc_grid_15m=grid_15m,
                        trade_filters=args.trade_filter or [],
                    )
                    raw = _fetch_risk_replay_trade_rows(
                        cur, monitor, args.start, args.end, test_clause, extra
                    )
                    enriched: list[dict[str, Any]] = []
                    for r in raw:
                        ttc = open_to_next_boundary_minutes(
                            r["created_at"],
                            args.ttc_timezone,
                            grid_15m=grid_15m,
                        )
                        enriched.append({**r, "_ttc": ttc})
                    print(f"--- {monitor} (combo grid) ---")
                    _print_combo_pool_diagnostics(
                        enriched, ttc_timezone=args.ttc_timezone
                    )
                    try:
                        rows_out, skipped_short, ran = _run_combo_risk_grid_for_monitor(
                            monitor=monitor,
                            risk=risk,
                            enriched=enriched,
                            compound_cents=compound_cents,
                            prob_lo=prob_lo,
                            prob_hi=prob_hi,
                            prob_step=prob_step,
                            ttc_min_range=args.combo_ttc_min_range,
                            ttc_max_range=args.combo_ttc_max_range,
                            ttc_step_seconds=args.combo_ttc_step_seconds,
                            lp_lo=pl_lo,
                            lp_hi=pl_hi,
                            min_closed_trades=args.combo_min_closed_trades,
                            apply_regime_filter=args.lp_sweep_apply_regime,
                        )
                    except ValueError as e:
                        print(f"error: {e}", file=sys.stderr)
                        return 2
                    filter_lines = format_filters_for_display(
                        paper_mode=args.paper,
                        min_prob=None,
                        max_prob=None,
                        min_ttc=None,
                        max_ttc=None,
                        ttc_timezone=args.ttc_timezone,
                        trade_filters=args.trade_filter or [],
                    )
                    filter_lines.append(
                        "TTC stepping: 15m grid if monitor strategy contains '15m'; else hourly."
                    )
                    filter_lines.append(
                        f"combo grid prob {prob_lo:g}:{prob_hi:g} step {prob_step:g}; "
                        f"LP {pl_lo}..{pl_hi}; TTC min axis {args.combo_ttc_min_range}; "
                        f"TTC max axis {args.combo_ttc_max_range}; step {args.combo_ttc_step_seconds:g}s"
                    )
                    _print_combo_risk_grid_report(
                        monitor,
                        rows_out,
                        top_k=args.combo_top,
                        compound_usd=float(args.compound_start_usd),
                        skipped_short=skipped_short,
                        filter_lines=filter_lines,
                        include_test_filter=args.include_test_filter,
                        eval_count=ran,
                    )
        finally:
            conn.close()
        return 0

    if args.lp_streak_threshold_sweep is not None:
        if args.hypothetical_position is not None:
            print(
                "error: --lp-streak-threshold-sweep cannot be combined with --hypothetical-position",
                file=sys.stderr,
            )
            return 2
        if args.optimize_ttc_window:
            print(
                "error: --lp-streak-threshold-sweep cannot be combined with --optimize-ttc-window",
                file=sys.stderr,
            )
            return 2
        if args.max_ttc_sweep is not None:
            print(
                "error: --lp-streak-threshold-sweep cannot be combined with --max-ttc-sweep",
                file=sys.stderr,
            )
            return 2

    if args.lp_streak_threshold_sweep is not None:
        lo, hi = args.lp_streak_threshold_sweep
        compound_cents: int | None = None
        if args.compound_start_usd is not None:
            compound_cents = int(round(float(args.compound_start_usd) * 100.0))
            if compound_cents < 1:
                print("error: --compound-start-usd rounds to < 1 cent", file=sys.stderr)
                return 2
        test_clause = _test_clause(args.include_test_filter)
        blocks: list[dict[str, Any]] = []
        conn = get_connection()
        try:
            with conn.cursor() as cur:
                for monitor in args.monitors:
                    parsed = parse_monitor_token(monitor)
                    if not parsed:
                        print(f"error: cannot parse monitor label {monitor!r}", file=sys.stderr)
                        return 2
                    u, mid = parsed
                    risk = fetch_monitor_risk_settings(cur, u, mid)
                    if not risk:
                        print(
                            f"error: no monitor_list row for {monitor} (user {u} id {mid})",
                            file=sys.stderr,
                        )
                        return 2
                    strategy = risk.get("strategy")
                    grid_15m = strategy_implies_15m_ttc_grid(strategy)
                    extra = build_trade_where_parts(
                        paper_mode=args.paper,
                        min_prob=args.min_prob,
                        max_prob=args.max_prob,
                        min_ttc_minutes=args.min_ttc_minutes,
                        max_ttc_minutes=args.max_ttc_minutes,
                        ttc_timezone=args.ttc_timezone,
                        ttc_grid_15m=grid_15m,
                        trade_filters=args.trade_filter or [],
                    )
                    raw = _fetch_risk_replay_trade_rows(
                        cur, monitor, args.start, args.end, test_clause, extra
                    )
                    sweep_rows = sweep_loss_prevention_thresholds(
                        raw,
                        risk,
                        lo=lo,
                        hi=hi,
                        apply_regime_filter=args.lp_sweep_apply_regime,
                        objective=lambda r: _objective_from_replay_result(
                            r, args.lp_sweep_objective
                        ),
                        compound_start_cents=compound_cents,
                    )
                    best = max(sweep_rows, key=lambda x: x[2])
                    db_th = risk.get("win_streak_threshold")
                    baseline = None
                    try:
                        db_th_int = int(db_th) if db_th is not None else None
                    except (TypeError, ValueError):
                        db_th_int = None
                    if db_th_int is not None:
                        baseline = replay_loss_prevention_threshold(
                            raw,
                            risk,
                            win_streak_threshold=db_th_int,
                            apply_regime_filter=args.lp_sweep_apply_regime,
                            compound_start_cents=compound_cents,
                        )
                    blocks.append(
                        {
                            "monitor": monitor,
                            "risk": risk,
                            "sweep_rows": sweep_rows,
                            "best": best,
                            "baseline": baseline,
                        }
                    )
        finally:
            conn.close()

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
        filter_lines.append(
            f"LP streak sweep {lo}..{hi}; objective={args.lp_sweep_objective}; "
            f"regime pre-filter={'on' if args.lp_sweep_apply_regime else 'off'}"
        )
        if args.compound_start_usd is not None:
            filter_lines.append(
                f"Compounding: start USD={args.compound_start_usd:g} ({compound_cents} cents)"
            )
        _print_lp_streak_threshold_sweep_report(
            blocks,
            include_test_filter=args.include_test_filter,
            filter_lines=filter_lines,
            sweep_lo=lo,
            sweep_hi=hi,
            apply_regime=args.lp_sweep_apply_regime,
            objective=args.lp_sweep_objective,
            compound_start_usd=args.compound_start_usd,
        )
        return 0

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
