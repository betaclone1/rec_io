#!/usr/bin/env python3
"""
Exact-cent first-touch longshot over a date span.

- Limit L on yes/no (exact cent)
- No TTC cutoff
- Require cumulative tape volume at L on the chosen side >= contracts
  (else skip — cannot support full size)
- Score full contracts * L outlay; win pays contracts

Stdout: overall FINAL results only (use --print-breakdowns for month/week tables).
Always writes durable CSVs so week/month slices need no re-run:
  --out (events): date_et, year_month, iso_week, week_start_et, …
  {stem}_by_month.csv / {stem}_by_week.csv / {stem}_totals.csv
"""
from __future__ import annotations

import argparse
import csv
import json
import time
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence, Tuple

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


def _week_keys(d: date) -> Tuple[str, str]:
    """Return (iso_week like 2026-W36, week_start_et Monday ISO date)."""
    iso = d.isocalendar()
    week_start = date.fromisocalendar(iso.year, iso.week, 1)
    return f"{iso.year}-W{iso.week:02d}", week_start.isoformat()


def _trade_pnl(won: bool, contracts: float, outlay: float) -> float:
    return (contracts - outlay) if won else (-outlay)


def _rollup(
    events: Sequence[Dict[str, Any]],
    *,
    key: str,
    bankroll0: float,
) -> List[Dict[str, Any]]:
    buckets: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for e in events:
        buckets[str(e[key])].append(e)
    rows: List[Dict[str, Any]] = []
    for k in sorted(buckets):
        es = buckets[k]
        w = sum(1 for e in es if e["won"])
        l = len(es) - w
        pnl = sum(float(e["trade_pnl"]) for e in es)
        rows.append(
            {
                key: k,
                "week_start_et": es[0].get("week_start_et", "") if key == "iso_week" else "",
                "year_month": es[0].get("year_month", "") if key == "year_month" else "",
                "scored": len(es),
                "winners": w,
                "losers": l,
                "win_rate_pct": round(100.0 * w / len(es), 4) if es else 0.0,
                "pnl": pnl,
                "equity_end_if_isolated": bankroll0 + pnl,
                "outlay_total": sum(float(e["outlay"]) for e in es),
                "first_date_et": min(e["date_et"] for e in es),
                "last_date_et": max(e["date_et"] for e in es),
            }
        )
    return rows


def _write_csv(path: Path, fieldnames: Sequence[str], rows: Iterable[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        wr = csv.DictWriter(f, fieldnames=list(fieldnames), extrasaction="ignore")
        wr.writeheader()
        for r in rows:
            wr.writerow(r)


def _print_table(title: str, rows: Sequence[Dict[str, Any]], key: str) -> None:
    print(f"\n======== {title} ========", flush=True)
    if not rows:
        print("(empty)", flush=True)
        return
    hdr = (
        f"{key:>12} {'scored':>7} {'W':>5} {'L':>6} {'wr%':>7} "
        f"{'pnl':>14} {'dates':>23}"
    )
    print(hdr, flush=True)
    for r in rows:
        dates = f"{r['first_date_et']}..{r['last_date_et']}"
        print(
            f"{str(r[key]):>12} {int(r['scored']):7d} {int(r['winners']):5d} "
            f"{int(r['losers']):6d} {float(r['win_rate_pct']):7.2f} "
            f"{float(r['pnl']):14,.2f} {dates:>23}",
            flush=True,
        )


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--start", required=True)
    ap.add_argument("--end", required=True)
    ap.add_argument(
        "--series",
        default="KXBTC15M",
        help="Kalshi 15m series ticker (e.g. KXBTC15M, KXETH15M).",
    )
    ap.add_argument("--limit", type=float, default=0.01)
    ap.add_argument("--contracts", type=float, default=2500.0)
    ap.add_argument("--bankroll", type=float, default=10_000.0)
    ap.add_argument(
        "--out",
        default="",
        help="Events CSV path. Sibling *_by_month / *_by_week / *_totals written next to it.",
    )
    ap.add_argument(
        "--print-breakdowns",
        action="store_true",
        help="Also print month/week summary tables (always written to CSV either way).",
    )
    args = ap.parse_args()

    start = date.fromisoformat(args.start)
    end = date.fromisoformat(args.end)
    series = str(args.series).strip().upper()
    L = round(float(args.limit), 2)
    contracts = float(args.contracts)
    outlay = contracts * L
    need = contracts
    bankroll0 = float(args.bankroll)

    cache_p = OUT / ".cache_market_result_by_ticker.json"
    cache = json.loads(cache_p.read_text()) if cache_p.is_file() else {}

    events: List[Dict[str, Any]] = []
    empty = no_touch = short = unk = 0
    t0 = time.time()
    d = start
    while d <= end:
        by: Dict[str, List[dict]] = defaultdict(list)
        p = OUT / f"{series}_public_trades_{d.isoformat()}_et.csv"
        if p.is_file():
            with p.open() as f:
                for r in csv.DictReader(f):
                    by[r["ticker"]].append(r)
        day_keep = 0
        iso_week, week_start = _week_keys(d)
        year_month = f"{d.year}-{d.month:02d}"
        for t in kalshi_15m_market_tickers_for_eastern_date(series, d):
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
            won = mr == side
            tpnl = _trade_pnl(won, contracts, outlay)
            events.append(
                {
                    "date_et": d.isoformat(),
                    "year_month": year_month,
                    "iso_week": iso_week,
                    "week_start_et": week_start,
                    "ticker": t,
                    "side": side,
                    "t": trade.get("created_time") or "",
                    "won": won,
                    "vol_at_L": vol,
                    "limit_px": L,
                    "contracts": contracts,
                    "outlay": outlay,
                    "trade_pnl": tpnl,
                    "market_result": mr,
                }
            )
            day_keep += 1
        print(f"{d.isoformat()} kept={day_keep}", flush=True)
        d += timedelta(days=1)

    events.sort(key=lambda e: (e["t"], e["ticker"]))
    equity = peak = min_eq = bankroll0
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
        e["equity_after"] = equity
        e["peak_equity"] = peak
        e["drawdown_from_peak"] = peak - equity

    n = len(events)
    pnl_total = equity - bankroll0
    load_s = time.time() - t0

    print(
        f"\n======== FINAL {series} {start}..{end} limit={L} contracts={contracts:.0f} "
        f"cum_vol>={need:.0f} no TTC ========",
        flush=True,
    )
    print(
        f"load_s={load_s:.1f} empty={empty} no_touch={no_touch} "
        f"short_tape={short} unk={unk}",
        flush=True,
    )
    if n:
        print(f"scored={n} winners={w} losers={l} wr={100 * w / n:.2f}%", flush=True)
        print(f"pnl=${pnl_total:,.2f}", flush=True)
        print(f"equity_end=${equity:,.2f} min_equity=${min_eq:,.2f}", flush=True)
        print(f"max_dd_peak_to_trough=${max_dd:,.2f}", flush=True)
    else:
        print("scored=0", flush=True)

    by_month = _rollup(events, key="year_month", bankroll0=bankroll0)
    by_week = _rollup(events, key="iso_week", bankroll0=bankroll0)
    for r in by_month:
        r.pop("week_start_et", None)
    for r in by_week:
        r.pop("year_month", None)

    if args.print_breakdowns:
        _print_table("BY MONTH (sum trade_pnl — slice without re-run)", by_month, "year_month")
        _print_table("BY ISO WEEK (Mon-start week_start_et in CSV)", by_week, "iso_week")

    out = Path(args.out) if args.out else (
        OUT / f"{series}_exact_cent_cum{int(need)}_limit{L:.2f}_{start}_{end}_et.csv"
    )
    stem = out.with_suffix("")  # strip .csv
    # if user passed foo_et.csv, siblings foo_et_by_month.csv is awkward;
    # use: events at out, siblings {stem}_by_month.csv etc.
    events_path = out
    month_path = Path(str(stem) + "_by_month.csv")
    week_path = Path(str(stem) + "_by_week.csv")
    totals_path = Path(str(stem) + "_totals.csv")

    event_fields = [
        "date_et",
        "year_month",
        "iso_week",
        "week_start_et",
        "ticker",
        "side",
        "t",
        "won",
        "market_result",
        "vol_at_L",
        "limit_px",
        "contracts",
        "outlay",
        "trade_pnl",
        "equity_after",
        "peak_equity",
        "drawdown_from_peak",
    ]
    # serialize won as 0/1 for easy spreadsheets
    event_rows = []
    for e in events:
        row = dict(e)
        row["won"] = 1 if e["won"] else 0
        event_rows.append(row)
    _write_csv(events_path, event_fields, event_rows)

    month_fields = [
        "year_month",
        "scored",
        "winners",
        "losers",
        "win_rate_pct",
        "pnl",
        "equity_end_if_isolated",
        "outlay_total",
        "first_date_et",
        "last_date_et",
    ]
    _write_csv(month_path, month_fields, by_month)

    week_fields = [
        "iso_week",
        "week_start_et",
        "scored",
        "winners",
        "losers",
        "win_rate_pct",
        "pnl",
        "equity_end_if_isolated",
        "outlay_total",
        "first_date_et",
        "last_date_et",
    ]
    _write_csv(week_path, week_fields, by_week)

    totals = [
        {
            "series": series,
            "span_start": start.isoformat(),
            "span_end": end.isoformat(),
            "limit_px": L,
            "contracts": contracts,
            "cum_vol_min": need,
            "bankroll0": bankroll0,
            "scored": n,
            "winners": w,
            "losers": l,
            "win_rate_pct": round(100.0 * w / n, 4) if n else 0.0,
            "pnl": pnl_total,
            "equity_end": equity,
            "min_equity": min_eq,
            "max_dd_peak_to_trough": max_dd,
            "empty_slots": empty,
            "no_touch": no_touch,
            "short_tape": short,
            "unknown_result": unk,
            "load_s": round(load_s, 3),
            "events_csv": str(events_path),
            "by_month_csv": str(month_path),
            "by_week_csv": str(week_path),
        }
    ]
    _write_csv(totals_path, list(totals[0].keys()), totals)

    print(f"\nwrote events  {events_path}", flush=True)
    print(f"wrote month   {month_path}", flush=True)
    print(f"wrote week    {week_path}", flush=True)
    print(f"wrote totals  {totals_path}", flush=True)
    print("DONE", flush=True)


if __name__ == "__main__":
    main()
