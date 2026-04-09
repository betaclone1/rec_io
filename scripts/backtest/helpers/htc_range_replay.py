"""
Sequential **HTC** replay over many ``backtest.backtest_1m_*`` markets in a time window.

- **Settings:** ``users.strategy_list_<user>`` by name (AES + position/risk columns). Not monitor-specific.
- **Bankroll:** Fresh run: in-memory equity + **paper-style sticky** reference (``balance_snapshot`` rule:
  new high follows equity; between 70% and 100% of prior sticky the reference is frozen; at or below
  70% it steps down to equity).
- **Sizing:** ``monitor_manager``-style intended contracts via ``risk_replay._compute_intended_contracts``,
  capped by ``_contracts_for_allocation`` against **full current equity** (affordable), then
  ``contracts_cap`` from loss-prevention throttle (1).
- **Loss prevention:** Per closed trade (one trade per market in this harness): matches
  ``update_monitor_win_streak`` *single-trade cycle* outcome — loss resets streak and throttles when
  toggle on; wins increment streak until ``win_streak_threshold`` clears throttle.

- **Summary:** ``equity_low_dollars`` / ``equity_low_vs_starting_bankroll_pct`` = minimum simulated
  portfolio equity after each **closed** trade (and at start); no intra-position mark-to-market.
  ``max_drawdown_from_running_peak_*`` = largest drop from a prior **high-water** equity within the run.

CLI: ``core_backtester.py --replay-htc-range`` with ``--start`` / ``--end`` (ISO with timezone).
By default the core backtester runs ``--ingest-kalshi-trading-day`` for each overlapping Eastern
date (``--replay-htc-ingest-series``, default ``KXBTC15M``) before querying ``backtest`` tables.
"""

from __future__ import annotations

import re
from datetime import date as Date
from datetime import datetime
from typing import Any, Optional
from zoneinfo import ZoneInfo

from psycopg2 import extras
from psycopg2 import sql

from scripts.backtest.helpers.htc_backtest_replay import (
    _contracts_for_allocation,
    fetch_strategy_auto_entry_settings,
    first_htc_entry_hit,
    infer_strategy_list_name_for_kalshi_ticker,
    run_htc_single_market_replay,
)
from scripts.backtest.helpers.kalshi_candles_1m import qualified_backtest_candles_table
from scripts.backtest.helpers.risk_replay import _compute_intended_contracts

_BACKTEST_REL_RE = re.compile(r"^backtest_1m_[a-z0-9_]+$")


def _strategy_table_ok(name: str) -> bool:
    return bool(re.fullmatch(r"strategy_list_[0-9]+", name))


def fetch_strategy_range_aux(
    conn: Any, *, strategy_table: str, strategy_name: str
) -> dict[str, Any]:
    """Position sizing + loss-prevention fields from ``strategy_list``."""
    if not _strategy_table_ok(strategy_table):
        raise ValueError(f"invalid strategy table: {strategy_table!r}")
    name = (strategy_name or "").strip()
    if not name:
        raise ValueError("strategy_name is required")
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT position_size, position_type, multiplier, performance_based_allocation,
                   win_streak_threshold, loss_prevention_toggle, loss_prevention
            FROM users.{strategy_table}
            WHERE LOWER(name) = LOWER(%s)
            LIMIT 1
            """,
            (name,),
        )
        row = cur.fetchone()
        if not row:
            raise ValueError(f"no strategy {name!r} in users.{strategy_table}")
    return {
        "position_size": row[0],
        "position_type": row[1] or "percent",
        "multiplier": float(row[2]) if row[2] is not None else 1.0,
        "performance_based_allocation": bool(row[3]) if row[3] is not None else False,
        "win_streak_threshold": int(row[4]) if row[4] is not None else 22,
        "loss_prevention_toggle": bool(row[5]) if row[5] is not None else True,
        "loss_prevention": (row[6] or "none") if row[6] is not None else "none",
        "current_max_pct_exposure": None,
    }


def instant_to_et_naive(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        raise ValueError("datetime must be timezone-aware")
    return dt.astimezone(ZoneInfo("America/New_York")).replace(tzinfo=None)


def eastern_calendar_days_overlapping_range(start: datetime, end: datetime) -> list[Date]:
    """
    Eastern (America/New_York) **calendar dates** that overlap ``[start, end)`` in wall time.
    Used to run ``--ingest-kalshi-trading-day`` once per day before range replay.
    """
    from datetime import datetime as dt_cls
    from datetime import timedelta

    s = instant_to_et_naive(start)
    e = instant_to_et_naive(end)
    if e <= s:
        return []
    out: list[Date] = []
    cur = s.date()
    end_date = e.date()
    while cur <= end_date:
        day_start = dt_cls.combine(cur, dt_cls.min.time())
        day_end = day_start + timedelta(days=1)
        if day_start < e and day_end > s:
            out.append(cur)
        cur += timedelta(days=1)
    return out


def paper_style_sticky_step(sticky: float, equity: float, pnl: float) -> tuple[float, float]:
    """Mirror ``apply_aggregate_snapshot`` sticky ``bankroll_current`` when flat (simplified)."""
    eq = float(equity) + float(pnl)
    st = float(sticky)
    if eq > st:
        return eq, eq
    if st > 0 and eq <= st * 0.7:
        return eq, eq
    return eq, st


def list_backtest_market_tables_in_window(
    conn: Any,
    *,
    start_et_naive: datetime,
    end_et_naive: datetime,
) -> list[dict[str, Any]]:
    """
    Tables overlapping [start, end) on Eastern-naive ``timestamp`` column.
    Returns rows sorted by ``first_ts`` with validated ``relname`` and ``ticker``.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT c.relname
            FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = 'backtest'
              AND c.relkind = 'r'
              AND c.relname LIKE 'backtest_1m_%'
            ORDER BY c.relname
            """
        )
        rels = [r[0] for r in cur.fetchall()]

    out: list[dict[str, Any]] = []
    for rel in rels:
        if not _BACKTEST_REL_RE.match(rel):
            continue
        q = sql.SQL(
            "SELECT MIN({ts}) AS mn, MAX({ts}) AS mx, MAX({mt}) AS tkr FROM {sch}.{tbl}"
        ).format(
            ts=sql.Identifier("timestamp"),
            mt=sql.Identifier("market_ticker"),
            sch=sql.Identifier("backtest"),
            tbl=sql.Identifier(rel),
        )
        with conn.cursor() as cur:
            cur.execute(q)
            row = cur.fetchone()
        if not row or row[0] is None or row[1] is None:
            continue
        mn, mx, tkr = row[0], row[1], row[2]
        if mx < start_et_naive or mn >= end_et_naive:
            continue
        tks = (str(tkr).strip() if tkr else "") or None
        out.append(
            {
                "relname": rel,
                "first_ts": mn,
                "last_ts": mx,
                "market_ticker": tks,
            }
        )
    out.sort(key=lambda x: x["first_ts"])
    return out


def _apply_lp_after_trade(
    *,
    win_loss: str,
    toggle: bool,
    threshold: int,
    win_streak: int,
    lp_throttle: bool,
) -> tuple[int, bool]:
    wl = (win_loss or "").strip().upper()
    th = max(1, int(threshold))
    if not toggle:
        if wl == "L":
            return 0, False
        if wl == "W":
            return win_streak + 1, False
        return win_streak, False
    if wl == "L":
        return 0, True
    if wl == "W":
        ns = win_streak + 1
        return ns, ns < th
    return win_streak, lp_throttle


def run_htc_strategy_range_replay(
    conn: Any,
    *,
    start: datetime,
    end: datetime,
    starting_bankroll: float,
    strategy_name: str,
    strategy_table: str = "strategy_list_0001",
    replay_user: str = "0001",
    gate_profile: str = "full",
    spike_alert_active: bool = False,
    allocation_pct: Optional[float] = None,
    min_probability_override: Optional[float] = None,
    max_probability_override: Optional[float] = None,
) -> dict[str, Any]:
    """
    Walk all overlapping ``backtest_1m_*`` tables in time order; strategy filters by
    ``infer_strategy_list_name_for_kalshi_ticker`` vs ``strategy_name``.

    If ``allocation_pct`` is set (e.g. ``20``), each entry sizes contracts from
    ``_contracts_for_allocation(buy_price, spend_cap * allocation_pct / 100)`` (same idea as
    single-market replay). If ``None``, uses ``strategy_list`` position fields via
    ``_compute_intended_contracts``.
    """
    if starting_bankroll <= 0:
        raise ValueError("starting_bankroll must be positive")
    if end <= start:
        raise ValueError("end must be after start")
    if not _strategy_table_ok(strategy_table):
        raise ValueError(f"invalid strategy_table: {strategy_table!r}")
    if allocation_pct is not None and not (0.0 < float(allocation_pct) <= 100.0):
        raise ValueError("allocation_pct must be in (0, 100] when set")

    s_na = instant_to_et_naive(start)
    e_na = instant_to_et_naive(end)

    entry_settings = fetch_strategy_auto_entry_settings(
        conn, strategy_table=strategy_table, strategy_name=strategy_name
    )
    if min_probability_override is not None:
        entry_settings = dict(entry_settings)
        entry_settings["min_probability"] = float(min_probability_override)
    if max_probability_override is not None:
        entry_settings = dict(entry_settings)
        entry_settings["max_probability"] = float(max_probability_override)
    aux = fetch_strategy_range_aux(conn, strategy_table=strategy_table, strategy_name=strategy_name)

    tables = list_backtest_market_tables_in_window(conn, start_et_naive=s_na, end_et_naive=e_na)

    equity = float(starting_bankroll)
    sticky = float(starting_bankroll)
    peak = equity
    max_dd_dollars = 0.0
    equity_low = float(starting_bankroll)

    win_streak = 0
    lp_throttle = False
    th = int(aux["win_streak_threshold"])
    toggle = bool(aux["loss_prevention_toggle"])

    trades: list[dict[str, Any]] = []
    skipped_wrong_strategy = 0
    skipped_no_ticker = 0

    risk_row: dict[str, Any] = {"multiplier": aux["multiplier"]}

    for info in tables:
        tkr = info.get("market_ticker")
        if not tkr:
            skipped_no_ticker += 1
            continue
        inferred = infer_strategy_list_name_for_kalshi_ticker(tkr)
        if inferred.strip().lower() != strategy_name.strip().lower():
            skipped_wrong_strategy += 1
            continue

        fq = qualified_backtest_candles_table(tkr)
        with conn.cursor(cursor_factory=extras.RealDictCursor) as cur:
            cur.execute(f"SELECT * FROM {fq} ORDER BY end_period_ts ASC")
            rows = cur.fetchall()

        hit = first_htc_entry_hit(
            rows,
            entry_settings,
            spike_alert_active=spike_alert_active,
            gate_profile=gate_profile,
        )
        if hit is None:
            trades.append(
                {
                    "ticker": tkr,
                    "table": info["relname"],
                    "skipped": True,
                    "reason": "no_entry_signal",
                    "replay": {
                        "ok": True,
                        "no_trade": True,
                        "reason": "no_entry_signal",
                        "table": fq,
                    },
                }
            )
            continue

        buy_p = float(hit[1]["buy_price"])
        spend_cap = min(sticky, equity)
        if allocation_pct is not None:
            slice_dollars = spend_cap * float(allocation_pct) / 100.0
            if lp_throttle:
                intended = 1
            else:
                intended = _contracts_for_allocation(buy_p, slice_dollars)
        else:
            intended = _compute_intended_contracts(
                risk_row,
                aux,
                throttle_one=lp_throttle,
                allotment_dollars_override=sticky,
            )
        cap_aff = _contracts_for_allocation(buy_p, spend_cap)
        final_cap = min(intended, cap_aff)
        if lp_throttle:
            final_cap = min(final_cap, 1)
        final_cap = max(0, int(final_cap))
        if final_cap < 1:
            trades.append(
                {
                    "ticker": tkr,
                    "table": info["relname"],
                    "skipped": True,
                    "reason": "zero_contracts_after_sizing",
                    "buy_price": buy_p,
                    "intended_contracts": intended,
                    "affordable_contracts": cap_aff,
                }
            )
            continue

        res = run_htc_single_market_replay(
            conn,
            market_ticker=tkr,
            bankroll=spend_cap,
            allocation_pct=100.0,
            allocation_dollars_override=spend_cap,
            contracts_cap=final_cap,
            ret_pct_reference_balance=equity,
            entry_settings=entry_settings,
            entry_settings_source="strategy_list",
            replay_user=str(replay_user).strip(),
            strategy_name=strategy_name,
            spike_alert_active=spike_alert_active,
            gate_profile=gate_profile,
        )

        if res.get("no_trade"):
            trades.append(
                {
                    "ticker": tkr,
                    "table": info["relname"],
                    "skipped": True,
                    "reason": res.get("reason"),
                    "replay": res,
                }
            )
            continue

        pnl = float(res.get("pnl_dollars") or res.get("pnl") or 0.0)
        wl = str(res.get("win_loss") or "")
        equity, sticky = paper_style_sticky_step(sticky, equity, pnl)
        peak = max(peak, equity)
        max_dd_dollars = max(max_dd_dollars, peak - equity)
        equity_low = min(equity_low, equity)

        win_streak, lp_throttle = _apply_lp_after_trade(
            win_loss=wl,
            toggle=toggle,
            threshold=th,
            win_streak=win_streak,
            lp_throttle=lp_throttle,
        )

        trades.append(
            {
                "ticker": tkr,
                "table": info["relname"],
                "skipped": False,
                "equity_after": round(equity, 2),
                "sticky_bankroll_after": round(sticky, 2),
                "intended_contracts": intended,
                "final_contracts_cap": final_cap,
                "lp_throttle_next": lp_throttle,
                "win_streak_after": win_streak,
                "replay": res,
            }
        )

    closed = [t for t in trades if not t.get("skipped")]
    n = len(closed)
    wins = sum(1 for t in closed if (t["replay"].get("win_loss") or "").upper() == "W")
    losses = sum(1 for t in closed if (t["replay"].get("win_loss") or "").upper() == "L")
    flat = sum(1 for t in closed if (t["replay"].get("win_loss") or "").upper() == "D")
    total_pnl = sum(float(t["replay"].get("pnl_dollars") or t["replay"].get("pnl") or 0) for t in closed)

    conf_vals = []
    for t in closed:
        c = t["replay"].get("win_loss_confirmed")
        if c is not None:
            conf_vals.append(bool(c))
    n_conf = len(conf_vals)
    false_conf = sum(1 for v in conf_vals if not v)
    pct_false_conf = (100.0 * false_conf / n_conf) if n_conf else None

    start_f = float(starting_bankroll)
    total_ret_pct = ((equity - start_f) / start_f * 100.0) if start_f > 0 else 0.0
    max_dd_pct = (max_dd_dollars / peak * 100.0) if peak > 0 else 0.0
    equity_low_vs_start_pct = (
        ((equity_low - start_f) / start_f * 100.0) if start_f > 0 else 0.0
    )

    return {
        "ok": True,
        "mode": "replay_htc_strategy_range",
        "start_et_naive": s_na.isoformat(),
        "end_et_naive_exclusive": e_na.isoformat(),
        "strategy_name": strategy_name,
        "strategy_table": strategy_table,
        "min_probability": float(entry_settings["min_probability"]),
        "max_probability": float(entry_settings["max_probability"]),
        "allocation_pct": float(allocation_pct) if allocation_pct is not None else None,
        "starting_bankroll": start_f,
        "final_equity": round(equity, 2),
        "final_sticky_bankroll": round(sticky, 2),
        "total_pnl": round(total_pnl, 2),
        "total_return_pct": round(total_ret_pct, 4),
        "equity_low_dollars": round(equity_low, 2),
        "equity_low_vs_starting_bankroll_pct": round(equity_low_vs_start_pct, 4),
        "max_drawdown_from_running_peak_dollars": round(max_dd_dollars, 2),
        "max_drawdown_from_running_peak_pct": round(max_dd_pct, 4),
        "max_drawdown_dollars": round(max_dd_dollars, 2),
        "max_drawdown_pct_of_peak": round(max_dd_pct, 4),
        "trades_closed": n,
        "wins": wins,
        "losses": losses,
        "flat": flat,
        "win_rate_pct": round(100.0 * wins / n, 2) if n else None,
        "win_loss_confirmed_false_count": false_conf,
        "win_loss_confirmed_evaluated_count": n_conf,
        "win_loss_confirmed_false_pct": round(pct_false_conf, 2) if pct_false_conf is not None else None,
        "markets_considered": len(tables),
        "skipped_wrong_strategy": skipped_wrong_strategy,
        "skipped_no_ticker": skipped_no_ticker,
        "trades": trades,
    }
