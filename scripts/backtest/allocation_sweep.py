#!/usr/bin/env python3
"""
Sweep monitor allocation combinations on historical trades with compounded bankroll.

Use this for multi-monitor allocation tests like:
- monitor 10026 and 10027 in 20-30% (1% steps)
- monitor 10023 in 5-15% (1% steps)
- shared bankroll, no skim, per-trade fixed allocation by monitor

Example:
  REC_IO_BACKTEST_DB=prod REC_IO_BACKTEST_QUIET=1 .venv/bin/python3 scripts/backtest/allocation_sweep.py \
    --start 2026-02-20T00:00:00-05:00 \
    --start-bankroll 5000 \
    --monitor mon_0001_10026:20:30 \
    --monitor mon_0001_10027:20:30 \
    --monitor mon_0001_10023:5:15 \
    --step 1 \
    --top 10
"""

from __future__ import annotations

import argparse
import itertools
import math
import os
import sys
from datetime import datetime
from typing import Any

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from scripts.backtest.helpers.db import get_connection
from scripts.backtest.helpers.hypothetical_trades import recompute_closed_trade_hypothetical


def _parse_monitor_range(raw: str) -> tuple[str, int, int]:
    parts = [p.strip() for p in raw.split(":")]
    if len(parts) != 3:
        raise ValueError(f"invalid --monitor value: {raw!r}; expected mon_x_y:min:max")
    mon, lo_s, hi_s = parts
    lo = int(lo_s)
    hi = int(hi_s)
    if lo < 0 or hi < 0 or hi < lo:
        raise ValueError(f"invalid range in {raw!r}")
    return mon, lo, hi


def _load_closed_rows(monitors: list[str], start_iso: str) -> list[dict[str, Any]]:
    start_ts = datetime.fromisoformat(start_iso)
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, monitor, created_at, date, time, ticker, status,
                       buy_price, sell_price, side, fees, pnl, strike, symbol_open, symbol_close, win_loss
                FROM users.trades_0001
                WHERE monitor = ANY(%s)
                  AND created_at >= %s
                ORDER BY created_at ASC, id ASC
                """,
                (monitors, start_ts),
            )
            rows = cur.fetchall()
            cols = [d[0] for d in cur.description]
    finally:
        conn.close()
    all_rows = [dict(zip(cols, r)) for r in rows]
    return [r for r in all_rows if str(r.get("status") or "").strip().lower() in ("closed", "settled")]


def _run_combo(closed_rows: list[dict[str, Any]], alloc_pct: dict[str, float], start_bankroll_usd: float) -> dict[str, Any]:
    bal_cents = int(round(start_bankroll_usd * 100.0))
    low_cents = bal_cents
    low_trade = None
    used = 0
    skipped = 0

    for t in closed_rows:
        m = str(t.get("monitor") or "").strip()
        ap = alloc_pct.get(m)
        if ap is None:
            skipped += 1
            continue

        bp = t.get("buy_price")
        try:
            buy_price = float(bp) if bp is not None else None
        except Exception:
            buy_price = None
        if buy_price is None or buy_price <= 0 or buy_price >= 1:
            skipped += 1
            continue

        alloc_usd = (bal_cents / 100.0) * ap
        position = int(math.floor(alloc_usd / buy_price))
        if position < 1:
            skipped += 1
            continue

        hypo = recompute_closed_trade_hypothetical(t, position=position)
        if not hypo:
            skipped += 1
            continue

        pnl = float(hypo.get("hypo_pnl") or 0.0)
        bal_cents += int(round(pnl * 100))
        if bal_cents < 1:
            bal_cents = 1
        used += 1

        if bal_cents < low_cents:
            low_cents = bal_cents
            low_trade = {
                "id": t.get("id"),
                "monitor": m,
                "created_at": t.get("created_at"),
                "date": t.get("date"),
                "time": t.get("time"),
                "ticker": t.get("ticker"),
            }

    final_usd = bal_cents / 100.0
    pnl_usd = final_usd - start_bankroll_usd
    return {
        "alloc_pct": alloc_pct,
        "final_usd": final_usd,
        "pnl_usd": pnl_usd,
        "ret_pct": (pnl_usd / start_bankroll_usd) * 100.0 if start_bankroll_usd > 0 else 0.0,
        "low_usd": low_cents / 100.0,
        "low_trade": low_trade,
        "used": used,
        "skipped": skipped,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Sweep per-monitor bankroll allocations on historical trades.")
    ap.add_argument("--start", required=True, help="ISO start timestamp, e.g. 2026-02-20T00:00:00-05:00")
    ap.add_argument("--start-bankroll", type=float, default=5000.0, help="Starting bankroll in USD")
    ap.add_argument(
        "--monitor",
        action="append",
        required=True,
        help="Repeatable monitor allocation range: mon_0001_10026:20:30 (percents, inclusive)",
    )
    ap.add_argument("--step", type=int, default=1, help="Percent step size (default 1)")
    ap.add_argument("--top", type=int, default=10, help="Top N combos to print by pnl (default 10)")
    args = ap.parse_args()

    if args.step < 1:
        raise ValueError("--step must be >= 1")

    specs = [_parse_monitor_range(x) for x in args.monitor]
    monitors = [m for m, _, _ in specs]
    grids = [list(range(lo, hi + 1, args.step)) for _, lo, hi in specs]

    closed_rows = _load_closed_rows(monitors, args.start)
    if not closed_rows:
        print("No closed/settled rows found for requested monitors/time range.")
        return 1

    results: list[dict[str, Any]] = []
    for combo in itertools.product(*grids):
        alloc_pct = {specs[i][0]: combo[i] / 100.0 for i in range(len(specs))}
        results.append(_run_combo(closed_rows, alloc_pct, args.start_bankroll))

    results.sort(key=lambda r: r["pnl_usd"], reverse=True)
    best = results[0]

    print(f"sweep_combos={len(results)}")
    print(f"closed_rows={len(closed_rows)}")
    print("BEST_COMBO")
    for mon, apct in best["alloc_pct"].items():
        print(f"alloc_{mon}={apct*100:.0f}%")
    print(f"final_balance_usd={best['final_usd']:.2f}")
    print(f"final_pnl_usd={best['pnl_usd']:.2f}")
    print(f"ret_pct={best['ret_pct']:.5f}")
    print(f"lowest_balance_usd={best['low_usd']:.2f}")
    if best["low_trade"]:
        lt = best["low_trade"]
        print(f"low_trade_id={lt['id']}")
        print(f"low_monitor={lt['monitor']}")
        print(f"low_created_at={lt['created_at']}")
        print(f"low_date={lt['date']}")
        print(f"low_time={lt['time']}")
        print(f"low_ticker={lt['ticker']}")

    print(f"TOP{args.top}_BY_PNL")
    for i, r in enumerate(results[: args.top], start=1):
        alloc_s = " ".join(f"{m.split('_')[-1]}={a*100:.0f}%" for m, a in r["alloc_pct"].items())
        print(
            f"#{i}: {alloc_s} pnl=${r['pnl_usd']:.2f} final=${r['final_usd']:.2f} "
            f"ret={r['ret_pct']:.5f}% low=${r['low_usd']:.2f}"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
