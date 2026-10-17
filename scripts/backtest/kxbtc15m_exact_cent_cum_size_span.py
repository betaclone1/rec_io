#!/usr/bin/env python3
"""
Exact-cent first-touch longshot over a date span.

- Limit L on yes/no (exact cent)
- No TTC cutoff
- Require cumulative tape volume at L on the chosen side >= contracts
  (else skip — cannot support full size)
- Score full contracts * L outlay; win pays contracts
"""
from __future__ import annotations

import argparse
import csv
import json
import time
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from scripts.backtest.helpers.kalshi_ticker_construct import (
    kalshi_15m_market_tickers_for_eastern_date,
)

OUT = Path("backend/data/historical_data/kalshi_public_trades")


def first_exact_touch(rows, L: float):
    for r in sorted(rows, key=lambda r: (r.get("created_time") or "", r.get("trade_id") or "")):
        y = round(float(r["yes_price_dollars"]), 2)
        n = round(float(r["no_price_dollars"]), 2)
        if y == L:
            return "yes", r
        if n == L:
            return "no", r
    return None


def side_vol_at_L(rows, side: str, L: float) -> float:
    v = 0.0
    for r in rows:
        y = round(float(r["yes_price_dollars"]), 2)
        n = round(float(r["no_price_dollars"]), 2)
        if (side == "yes" and y == L) or (side == "no" and n == L):
            try:
                v += float(r.get("count_fp") or r.get("count") or 0)
            except (TypeError, ValueError):
                pass
    return v


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", required=True)
    ap.add_argument("--end", required=True)
    ap.add_argument("--limit", type=float, default=0.01)
    ap.add_argument("--contracts", type=float, default=2500.0)
    ap.add_argument("--bankroll", type=float, default=10_000.0)
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    start = date.fromisoformat(args.start)
    end = date.fromisoformat(args.end)
    L = round(float(args.limit), 2)
    contracts = float(args.contracts)
    outlay = contracts * L
    need = contracts

    cache_p = OUT / ".cache_market_result_by_ticker.json"
    cache = json.loads(cache_p.read_text()) if cache_p.is_file() else {}

    events = []
    empty = no_touch = short = unk = 0
    t0 = time.time()
    d = start
    while d <= end:
        by = defaultdict(list)
        p = OUT / f"KXBTC15M_public_trades_{d.isoformat()}_et.csv"
        if p.is_file():
            with p.open() as f:
                for r in csv.DictReader(f):
                    by[r["ticker"]].append(r)
        day_keep = 0
        for t in kalshi_15m_market_tickers_for_eastern_date("KXBTC15M", d):
            rows = by.get(t) or []
            if not rows:
                empty += 1
                continue
            hit = first_exact_touch(rows, L)
            if not hit:
                no_touch += 1
                continue
            side, trade = hit
            mr = (cache.get(t) or {}).get("mr")
            if mr not in ("yes", "no"):
                unk += 1
                continue
            vol = side_vol_at_L(rows, side, L)
            if vol < need - 1e-9:
                short += 1
                continue
            events.append(
                {
                    "t": trade.get("created_time") or "",
                    "ticker": t,
                    "side": side,
                    "won": mr == side,
                    "date_et": d.isoformat(),
                    "vol": vol,
                }
            )
            day_keep += 1
        print(f"{d.isoformat()} kept={day_keep}", flush=True)
        d += timedelta(days=1)

    events.sort(key=lambda e: (e["t"], e["ticker"]))
    equity = peak = min_eq = float(args.bankroll)
    max_dd = 0.0
    w = l = 0
    for e in events:
        equity -= outlay
        if e["won"]:
            equity += contracts
            w += 1
        else:
            l += 1
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)
        min_eq = min(min_eq, equity)

    n = len(events)
    print(f"\n======== {start}..{end} limit={L} contracts={contracts:.0f} cum_vol>={need:.0f} no TTC ========")
    print(
        f"load_s={time.time()-t0:.1f} empty={empty} no_touch={no_touch} "
        f"short_tape={short} unk={unk}",
        flush=True,
    )
    if n:
        print(f"scored={n} winners={w} losers={l} wr={100*w/n:.2f}%", flush=True)
        print(f"pnl=${equity-float(args.bankroll):,.2f}", flush=True)
        print(f"equity_end=${equity:,.2f} min_equity=${min_eq:,.2f}", flush=True)
        print(f"max_dd_peak_to_trough=${max_dd:,.2f}", flush=True)
    else:
        print("scored=0", flush=True)

    out = Path(args.out) if args.out else (
        OUT / f"KXBTC15M_exact_cent_cum{int(need)}_limit{L:.2f}_{start}_{end}_et.csv"
    )
    with out.open("w", newline="") as f:
        fields = ["date_et", "ticker", "side", "t", "won", "vol"]
        wr = csv.DictWriter(f, fieldnames=fields)
        wr.writeheader()
        for e in events:
            wr.writerow({k: e.get(k, "") for k in fields})
    print(f"wrote {out}", flush=True)
    print("DONE", flush=True)


if __name__ == "__main__":
    main()
