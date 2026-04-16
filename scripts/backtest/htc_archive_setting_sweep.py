#!/usr/bin/env python3
"""
**Setting grid sweep** over ``historical_data.strike_table_master`` markets in a time window.

For each Cartesian product of override dimensions (defaults: ``max_time``, ``min_probability``,
``stop_loss_price``), runs the same **tick-table HTC replay** as
``core_backtester.py --replay-htc-market … --replay-from-tick-backtest`` on every discovered
market, using a **base** ``users…monitor_list_*`` row plus per-combo overrides. Ranks combos by
``--objective`` (default **sum_pnl** across markets that produced a trade).

**Requires** archive rows in the window. Uses **window-sliced** ``build_tick_backtest_from_strike_archive``
so each market’s tick table only contains snapshots inside ``[--start, --end)``.

**Example** (15m down to 2m max TTC as seconds, min prob 85–95, stop floor 0.15–0.25 USD):

```bash
REC_USER_SCHEMA=users_0001 PYTHONPATH=$(pwd) .venv/bin/python3 \\
  scripts/backtest/htc_archive_setting_sweep.py \\
  --start 2026-04-15T00:00:00-04:00 \\
  --end   2026-04-16T00:00:00-04:00 \\
  --monitor-id 10027 \\
  --replay-monitor-user 0001 \\
  --sweep-max-time-sec 900:120:60 \\
  --sweep-min-probability 85:95:1 \\
  --sweep-stop-loss 0.15:0.25:0.01 \\
  --series-prefix KXETH15M \\
  --replay-bankroll 10000 \\
  --replay-allocation-pct 20
```

See ``docs/BACKTESTING.md`` §5.6 and ``scripts/backtest/README.md``.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from scripts.backtest.helpers.db import get_connection  # noqa: E402
from scripts.backtest.helpers.htc_setting_grid_sweep import (  # noqa: E402
    discover_markets_for_contract_cycle,
    discover_markets_in_archive_window,
    parse_float_range_lo_hi_step,
    parse_int_range_hi_lo_step,
    rank_results,
    run_setting_grid_sweep,
)


def _parse_iso(s: str) -> datetime:
    t = (s or "").strip()
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    return datetime.fromisoformat(t)


def _hourly_cycle_window_et(*, contract_date_et: str, contract_hour_et: int) -> tuple[datetime, datetime]:
    d = datetime.strptime(str(contract_date_et), "%Y-%m-%d")
    h = int(contract_hour_et)
    if h < 0 or h > 23:
        raise ValueError("--contract-hour-et must be in 0..23")
    end_et = d.replace(hour=h, minute=0, second=0, microsecond=0, tzinfo=ZoneInfo("America/New_York"))
    start_et = end_et - timedelta(hours=1)
    return start_et, end_et


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--start", type=str, required=True, help="ISO-8601 window start (inclusive-ish for archive >=)")
    p.add_argument("--end", type=str, required=True, help="ISO-8601 window end (**exclusive** for archive <)")
    p.add_argument("--monitor-id", type=int, required=True)
    p.add_argument(
        "--replay-monitor-user",
        type=str,
        default="0001",
        help="Digits-only user suffix; monitor table = monitor_list_<user> (default 0001).",
    )
    p.add_argument("--replay-bankroll", type=float, default=10_000.0)
    p.add_argument("--replay-allocation-pct", type=float, default=20.0)
    p.add_argument(
        "--sweep-max-time-sec",
        type=str,
        default="900:120:60",
        metavar="HI:LO:STEP",
        help="``max_time`` sweep in **seconds** (DB units), high→low inclusive (default 900:120:60 = 15m→2m step 60s).",
    )
    p.add_argument(
        "--sweep-min-probability",
        type=str,
        default="85:95:1",
        metavar="LO:HI:STEP",
        help="min_probability grid (default 85:95:1).",
    )
    p.add_argument(
        "--sweep-stop-loss",
        type=str,
        default="0.15:0.25:0.01",
        metavar="LO:HI:STEP",
        help="stop_loss_price grid in **dollars** (default 0.15:0.25:0.01).",
    )
    p.add_argument(
        "--series-prefix",
        type=str,
        default=None,
        help="Optional filter: ``market_ticker LIKE '<prefix>%%'`` (e.g. KXETH15M).",
    )
    p.add_argument(
        "--contract-symbol",
        type=str,
        default=None,
        help="Exact contract-cycle mode: symbol (e.g. BTC).",
    )
    p.add_argument(
        "--contract-cadence",
        choices=("hourly",),
        default="hourly",
        help="Exact contract-cycle mode cadence (currently hourly only).",
    )
    p.add_argument(
        "--contract-date-et",
        type=str,
        default=None,
        help="Exact contract-cycle mode date in ET (YYYY-MM-DD).",
    )
    p.add_argument(
        "--contract-hour-et",
        type=int,
        default=None,
        metavar="H",
        help="Exact contract-cycle mode close hour in ET (0-23, e.g. 1 for 1am).",
    )
    p.add_argument(
        "--min-archive-rows",
        type=int,
        default=20,
        metavar="N",
        help="Only include markets with at least N archive rows in the window (default 20).",
    )
    p.add_argument(
        "--skip-materialize",
        action="store_true",
        help="Do not rebuild tick_backtest_* from archive (tables must already match the window).",
    )
    p.add_argument("--gate-profile", choices=("full", "simulated_15m"), default="full")
    p.add_argument("--replay-spike-alert-active", action="store_true")
    p.add_argument(
        "--objective",
        choices=("sum_pnl", "mean_pnl", "win_rate", "sum_ret_pct"),
        default="sum_pnl",
    )
    p.add_argument("--top", type=int, default=25, help="Print top N combos (default 25).")
    p.add_argument(
        "--json-out",
        action="store_true",
        help="Print full ranked list as JSON (all combos); default is text table for --top only.",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Print grid size and market list only; no replay.",
    )
    p.add_argument(
        "--no-compound",
        action="store_true",
        help="Use fixed starting bankroll for every market (no equity compounding across the window).",
    )
    p.add_argument(
        "--persist-trades",
        action="store_true",
        help="Write each closed replay to backtest.grid_sweep_trades (requires migration).",
    )
    p.add_argument(
        "--sweep-batch-id",
        type=str,
        default=None,
        help="UUID or label grouping one run in grid_sweep_trades (default: random UUID).",
    )
    p.add_argument(
        "--synthetic-monitor-id-base",
        type=int,
        default=9_000_000,
        metavar="N",
        help="First synthetic_monitor_id for combo index 0; combo i uses N+i (default 9000000).",
    )
    args = p.parse_args(argv)

    t0 = _parse_iso(args.start)
    t1 = _parse_iso(args.end)
    if t1 <= t0:
        print("error: --end must be after --start", file=sys.stderr)
        return 2

    mu = str(args.replay_monitor_user).strip()
    if not mu.isdigit():
        print("error: --replay-monitor-user must be digits only", file=sys.stderr)
        return 2
    monitor_table = f"monitor_list_{mu}"

    try:
        max_times = parse_int_range_hi_lo_step(args.sweep_max_time_sec)
        min_probs = parse_float_range_lo_hi_step(args.sweep_min_probability)
        stop_losses = parse_float_range_lo_hi_step(args.sweep_stop_loss)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    n_combo = len(max_times) * len(min_probs) * len(stop_losses)

    contract_mode = args.contract_symbol is not None or args.contract_date_et is not None or args.contract_hour_et is not None
    if contract_mode and not (args.contract_symbol and args.contract_date_et and args.contract_hour_et is not None):
        print(
            "error: contract-cycle mode requires --contract-symbol, --contract-date-et, and --contract-hour-et together",
            file=sys.stderr,
        )
        return 2
    if contract_mode and str(args.contract_cadence) == "hourly":
        try:
            t0, t1 = _hourly_cycle_window_et(
                contract_date_et=str(args.contract_date_et),
                contract_hour_et=int(args.contract_hour_et),
            )
        except ValueError as e:
            print(f"error: {e}", file=sys.stderr)
            return 2

    conn = get_connection()
    try:
        if contract_mode:
            tickers = discover_markets_for_contract_cycle(
                conn,
                contract_symbol=str(args.contract_symbol),
                contract_cadence=str(args.contract_cadence),
                contract_date_et=str(args.contract_date_et),
                contract_hour_et=int(args.contract_hour_et),
            )
        else:
            tickers = discover_markets_in_archive_window(
                conn,
                timestamp_start=t0,
                timestamp_end_exclusive=t1,
                series_prefix=args.series_prefix,
                min_archive_rows=int(args.min_archive_rows),
            )
    finally:
        conn.close()

    print(
        f"markets={len(tickers)}  grid max_time×min_prob×stop = {len(max_times)}×{len(min_probs)}×{len(stop_losses)} "
        f"= {n_combo} combos  replays≈{n_combo * max(1, len(tickers))}",
        file=sys.stderr,
    )
    if not tickers:
        print("error: no markets in archive for window + filters", file=sys.stderr)
        return 2
    if args.dry_run:
        print(json.dumps({"tickers": tickers, "combo_count": n_combo}, indent=2))
        return 0

    sweep_batch = (args.sweep_batch_id or "").strip() or str(uuid.uuid4())
    print(f"sweep_batch_id={sweep_batch}", file=sys.stderr)

    conn = get_connection()
    try:
        results = run_setting_grid_sweep(
            conn,
            tickers=tickers,
            timestamp_start=t0,
            timestamp_end_exclusive=t1,
            monitor_table=monitor_table,
            monitor_id=int(args.monitor_id),
            replay_user=mu,
            bankroll=float(args.replay_bankroll),
            allocation_pct=float(args.replay_allocation_pct),
            max_time_values=max_times,
            min_probability_values=min_probs,
            stop_loss_price_values=stop_losses,
            gate_profile=str(args.gate_profile),
            spike_alert_active=bool(args.replay_spike_alert_active),
            materialize_ticks=not bool(args.skip_materialize),
            compound=not bool(args.no_compound),
            persist_trades=bool(args.persist_trades),
            sweep_batch_id=sweep_batch,
            synthetic_monitor_id_base=int(args.synthetic_monitor_id_base),
            progress=None,
        )
    finally:
        conn.close()

    ranked = rank_results(results, args.objective, top=len(results) if args.json_out else int(args.top))

    if args.json_out:
        print(
            json.dumps(
                {
                    "objective": args.objective,
                    "monitor_id": args.monitor_id,
                    "monitor_table": monitor_table,
                    "sweep_batch_id": sweep_batch,
                    "synthetic_monitor_id_base": int(args.synthetic_monitor_id_base),
                    "compound": not bool(args.no_compound),
                    "window": {"start": args.start, "end": args.end},
                    "contract_cycle": (
                        {
                            "symbol": args.contract_symbol,
                            "cadence": args.contract_cadence,
                            "date_et": args.contract_date_et,
                            "hour_et": args.contract_hour_et,
                        }
                        if contract_mode
                        else None
                    ),
                    "tickers": tickers,
                    "ranked": [r.as_dict() | {"objective": r.objective(args.objective)} for r in ranked],
                },
                indent=2,
                default=str,
            )
        )
        return 0

    print(f"Top {len(ranked)} by {args.objective} (monitor {args.monitor_id}, {len(tickers)} markets)")
    hdr = f"{'max_t':>7} {'min_p':>6} {'stop':>6} {'synth':>8} {'traded':>6} {'wins':>5} {'sum_pnl':>10} {'final$':>10} {'win%':>6}"
    print(hdr)
    print("-" * len(hdr))
    for r in ranked:
        wr = (100.0 * r.wins / r.traded_markets) if r.traded_markets else 0.0
        print(
            f"{r.max_time:7d} {r.min_probability:6.2f} {r.stop_loss_price:6.2f} "
            f"{r.synthetic_monitor_id:8d} {r.traded_markets:6d} {r.wins:5d} {r.sum_pnl:10.2f} "
            f"{r.final_equity:10.2f} {wr:5.1f}%"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
