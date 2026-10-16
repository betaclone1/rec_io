#!/usr/bin/env python3
"""
Pull KXBTC15M public tape for a month of Eastern days, then score first-≤$0.02
longshot winners and bankroll PNL / max drawdown.

Example:
  .venv/bin/python3 scripts/backtest/run_kxbtc15m_longshot_month.py --year 2026 --month 9
"""

from __future__ import annotations

import argparse
import calendar
import csv
import sys
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timezone
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from backend.core.kalshi_event_market_fetch import market_result_for_ticker
from scripts.backtest.helpers.kalshi_ticker_construct import (
    kalshi_15m_market_tickers_for_eastern_date,
)
from scripts.backtest.pull_kxbtc15m_public_trades_day_csv import main as pull_day_main

THRESH = 0.02 + 1e-12
OUT_DIR = _ROOT / "backend" / "data" / "historical_data" / "kalshi_public_trades"


def month_days(year: int, month: int) -> list[date]:
    last = calendar.monthrange(year, month)[1]
    return [date(year, month, d) for d in range(1, last + 1)]


def first_longshot(rows: list[dict]) -> tuple[str, dict] | None:
    rows = sorted(rows, key=lambda r: (r.get("created_time") or "", r.get("trade_id") or ""))
    for r in rows:
        y = float(r["yes_price_dollars"])
        n = float(r["no_price_dollars"])
        if y <= THRESH:
            return "yes", r
        if n <= THRESH:
            return "no", r
    return None


def pull_month(days: list[date], workers: int) -> None:
    for day in days:
        print(f"\n======== PULL {day.isoformat()} ========", flush=True)
        sys.argv = [
            "pull_kxbtc15m_public_trades_day_csv.py",
            "--date",
            day.isoformat(),
            "--series",
            "KXBTC15M",
            "--workers",
            str(workers),
        ]
        t0 = time.time()
        rc = pull_day_main()
        print(f"PULL_DONE {day.isoformat()} rc={rc} elapsed={time.time()-t0:.1f}s", flush=True)
        if rc != 0:
            raise SystemExit(rc)


def scan_month(
    days: list[date],
    *,
    bankroll0: float,
    contracts: float,
    limit_px: float,
) -> dict:
    outlay_per = contracts * limit_px
    payout_win = contracts * 1.0

    events: list[dict] = []  # chronological longshot cycles
    tape_cycles = 0
    empty_cycles = 0
    no_longshot = 0
    unknown = 0

    for day in days:
        csv_path = OUT_DIR / f"KXBTC15M_public_trades_{day.isoformat()}_et.csv"
        tickers = kalshi_15m_market_tickers_for_eastern_date("KXBTC15M", day)
        by: dict[str, list[dict]] = defaultdict(list)
        if csv_path.is_file():
            with csv_path.open() as f:
                for r in csv.DictReader(f):
                    by[r["ticker"]].append(r)

        candidates: list[tuple[str, str, dict]] = []
        for t in tickers:
            rows = by.get(t) or []
            if not rows:
                empty_cycles += 1
                continue
            tape_cycles += 1
            hit = first_longshot(rows)
            if hit is None:
                no_longshot += 1
                continue
            candidates.append((t, hit[0], hit[1]))

        results: dict[str, tuple[str | None, str | None]] = {}
        with ThreadPoolExecutor(max_workers=8) as pool:
            futs = {pool.submit(market_result_for_ticker, t): t for t, _, _ in candidates}
            for fut in as_completed(futs):
                t = futs[fut]
                try:
                    results[t] = fut.result()
                except Exception as e:
                    results[t] = (None, str(e))

        day_w = day_l = day_u = 0
        for t, side, trade in candidates:
            mr, err = results.get(t, (None, "missing"))
            won = mr is not None and mr == side
            row = {
                "date_et": day.isoformat(),
                "ticker": t,
                "first_side": side,
                "first_time": trade.get("created_time") or "",
                "yes": trade.get("yes_price_dollars"),
                "no": trade.get("no_price_dollars"),
                "market_result": mr or "",
                "err": err or "",
                "won": won,
            }
            if mr is None:
                unknown += 1
                day_u += 1
                # exclude from PNL path (no authoritative result)
            else:
                events.append(row)
                if won:
                    day_w += 1
                else:
                    day_l += 1
        print(
            f"{day.isoformat()} tape={sum(1 for t in tickers if by.get(t))} "
            f"longshot={len(candidates)} winners={day_w} losers={day_l} unknown={day_u}",
            flush=True,
        )

    events.sort(key=lambda r: (r["first_time"], r["ticker"]))
    winners = sum(1 for e in events if e["won"])
    losers = sum(1 for e in events if not e["won"])

    # Equity path: each scored longshot cycle fills once at limit_px
    equity = bankroll0
    peak = bankroll0
    max_dd = 0.0
    max_dd_from_start = 0.0
    min_equity = bankroll0
    for e in events:
        equity -= outlay_per
        if e["won"]:
            equity += payout_win
        peak = max(peak, equity)
        dd = peak - equity
        max_dd = max(max_dd, dd)
        max_dd_from_start = max(max_dd_from_start, bankroll0 - equity)
        min_equity = min(min_equity, equity)

    pnl = equity - bankroll0
    ret_pct = (pnl / bankroll0) * 100.0 if bankroll0 else 0.0
    total_outlay = outlay_per * len(events)

    return {
        "tape_cycles": tape_cycles,
        "empty_cycles": empty_cycles,
        "no_longshot": no_longshot,
        "scored_cycles": len(events),
        "winners": winners,
        "losers": losers,
        "unknown": unknown,
        "outlay_per": outlay_per,
        "total_outlay": total_outlay,
        "pnl": pnl,
        "ret_pct_bankroll": ret_pct,
        "equity_end": equity,
        "min_equity": min_equity,
        "max_drawdown": max_dd,
        "max_drawdown_from_start": max_dd_from_start,
        "events": events,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, required=True)
    ap.add_argument("--month", type=int, required=True)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--skip-pull", action="store_true")
    ap.add_argument("--bankroll", type=float, default=10_000.0)
    ap.add_argument("--allocation-pct", type=float, default=20.0)
    ap.add_argument("--limit-px", type=float, default=0.02)
    args = ap.parse_args()

    # 20% of bankroll at $1/contract settlement capacity → contracts
    contracts = (args.bankroll * (args.allocation_pct / 100.0)) / 1.0
    days = month_days(args.year, args.month)
    print(
        f"MONTH {args.year}-{args.month:02d} days={len(days)} "
        f"bankroll={args.bankroll} allocation={args.allocation_pct}% "
        f"contracts={contracts:.0f} limit={args.limit_px} "
        f"outlay_per={contracts*args.limit_px:.2f}",
        flush=True,
    )
    t0 = time.time()
    if not args.skip_pull:
        pull_month(days, args.workers)
    else:
        print("skip-pull: using existing day CSVs", flush=True)

    print("\n======== SCAN + PNL ========", flush=True)
    res = scan_month(
        days,
        bankroll0=args.bankroll,
        contracts=contracts,
        limit_px=args.limit_px,
    )

    tag = f"{args.year}-{args.month:02d}"
    win_path = OUT_DIR / f"KXBTC15M_longshot_winners_{tag}_et.csv"
    with win_path.open("w", newline="") as f:
        fields = [
            "date_et",
            "ticker",
            "first_side",
            "first_time",
            "yes",
            "no",
            "market_result",
            "err",
            "won",
        ]
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for e in res["events"]:
            if e["won"]:
                w.writerow({k: e.get(k, "") for k in fields})

    print("\n======== RESULTS ========", flush=True)
    print(f"cycles_with_full_tape={res['tape_cycles']}", flush=True)
    print(f"empty_slots={res['empty_cycles']} no_longshot={res['no_longshot']} unknown_result={res['unknown']}", flush=True)
    print(f"scored_longshot_cycles={res['scored_cycles']} winners={res['winners']} losers={res['losers']}", flush=True)
    print(f"win_rate={res['winners']/res['scored_cycles']*100:.2f}%" if res["scored_cycles"] else "win_rate=n/a", flush=True)
    print(f"total_outlay=${res['total_outlay']:,.2f}", flush=True)
    print(f"pnl=${res['pnl']:,.2f}", flush=True)
    print(f"return_pct_on_bankroll={res['ret_pct_bankroll']:.2f}%", flush=True)
    print(f"equity_end=${res['equity_end']:,.2f} min_equity=${res['min_equity']:,.2f}", flush=True)
    print(f"max_drawdown_peak_to_trough=${res['max_drawdown']:,.2f}", flush=True)
    print(f"max_drawdown_from_start_10k=${res['max_drawdown_from_start']:,.2f}", flush=True)
    print(f"wrote {win_path}", flush=True)
    print(f"MONTH_DONE elapsed_min={(time.time()-t0)/60:.1f}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
