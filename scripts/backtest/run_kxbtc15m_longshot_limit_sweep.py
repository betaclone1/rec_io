#!/usr/bin/env python3
"""
Multi-month KXBTC15M first-≤limit longshot sweep across day CSVs already on disk.

Default: 2026-06-01 .. 2026-09-30, limit prices $0.90..$0.99 step $0.01,
bankroll $10k, 2000 contracts. Reports PNL, peak-to-trough DD, and min equity
(lowest bankroll) per limit.

Example:
  .venv/bin/python3 scripts/backtest/run_kxbtc15m_longshot_limit_sweep.py
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import requests

from backend.core.kalshi_event_market_fetch import normalize_market_result_field
from scripts.backtest.helpers.kalshi_ticker_construct import (
    kalshi_15m_market_tickers_for_eastern_date,
)

OUT_DIR = _ROOT / "backend" / "data" / "historical_data" / "kalshi_public_trades"
RESULT_CACHE = OUT_DIR / ".cache_market_result_by_ticker.json"
API_BASE = "https://external-api.kalshi.com/trade-api/v2"
_HEADERS = {"Accept": "application/json", "User-Agent": "rec_io_limit_sweep/1.0"}


def daterange(start: date, end: date) -> list[date]:
    out: list[date] = []
    d = start
    while d <= end:
        out.append(d)
        d += timedelta(days=1)
    return out


def load_result_cache() -> dict[str, dict[str, Any]]:
    if not RESULT_CACHE.is_file():
        return {}
    try:
        raw = json.loads(RESULT_CACHE.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {}
    except Exception:
        return {}


def save_result_cache(cache: dict[str, dict[str, Any]]) -> None:
    tmp = RESULT_CACHE.with_suffix(".partial.json")
    tmp.write_text(json.dumps(cache, separators=(",", ":"), sort_keys=True), encoding="utf-8")
    tmp.replace(RESULT_CACHE)


def first_hit_by_limit(
    rows: list[dict[str, Any]], limits: list[float]
) -> dict[float, tuple[str, dict[str, Any]] | None]:
    """
    One chronological pass: for each limit, first print with yes≤limit or no≤limit.

    Higher limits hit earlier (looser). Side preference matches the month scanner:
    check yes first, then no, on the same print.
    """
    ordered = sorted(
        rows, key=lambda r: (r.get("created_time") or "", r.get("trade_id") or "")
    )
    out: dict[float, tuple[str, dict[str, Any]] | None] = {lim: None for lim in limits}
    remaining = set(limits)
    for r in ordered:
        if not remaining:
            break
        y = float(r["yes_price_dollars"])
        n = float(r["no_price_dollars"])
        for lim in list(remaining):
            if y <= lim + 1e-12:
                out[lim] = ("yes", r)
                remaining.discard(lim)
            elif n <= lim + 1e-12:
                out[lim] = ("no", r)
                remaining.discard(lim)
    return out


def _get_json(url: str, *, max_attempts: int = 10) -> tuple[int, dict[str, Any] | None]:
    last_status = 0
    for attempt in range(max_attempts):
        try:
            r = requests.get(url, headers=_HEADERS, timeout=30)
            last_status = r.status_code
            if r.status_code in (429, 500, 502, 503, 504):
                time.sleep(min(30.0, 0.5 * (2**attempt)))
                continue
            if r.status_code == 404:
                return 404, None
            r.raise_for_status()
            data = r.json()
            return r.status_code, data if isinstance(data, dict) else None
        except Exception:
            time.sleep(min(30.0, 0.5 * (2**attempt)))
    return last_status, None


def fetch_market_result_direct(ticker: str) -> tuple[str | None, str | None]:
    """
    Prefer archived market, then live. One endpoint family — avoids stacking
    /events + /markets + /historical under rate limits.
    """
    for path in (f"/historical/markets/{ticker}", f"/markets/{ticker}"):
        status, data = _get_json(f"{API_BASE}{path}")
        if status == 404 or not data:
            continue
        market = data.get("market")
        if not isinstance(market, dict):
            continue
        raw = market.get("result")
        out = normalize_market_result_field(raw)
        if out is not None:
            return out, None
        if raw is None:
            return None, "result_null"
        return None, f"non_binary_result:{raw!r}"
    return None, "fetch_failed"


def resolve_results(tickers: list[str], *, workers: int) -> dict[str, tuple[str | None, str | None]]:
    cache = load_result_cache()
    out: dict[str, tuple[str | None, str | None]] = {}
    todo: list[str] = []
    for t in tickers:
        hit = cache.get(t)
        if isinstance(hit, dict) and hit.get("mr") in ("yes", "no"):
            out[t] = (hit.get("mr"), hit.get("err"))
        else:
            todo.append(t)
    print(f"market_result cache_hit={len(out)} todo={len(todo)}", flush=True)
    if not todo:
        return out

    done = 0
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futs = {pool.submit(fetch_market_result_direct, t): t for t in todo}
        for fut in as_completed(futs):
            t = futs[fut]
            mr, err = fut.result()
            out[t] = (mr, err)
            # Only persist authoritative yes/no — retry unknowns next run.
            if mr in ("yes", "no"):
                cache[t] = {"mr": mr, "err": err}
            done += 1
            if done % 100 == 0 or done == len(todo):
                print(
                    f"  results {done}/{len(todo)} ok={sum(1 for v in out.values() if v[0] in ('yes','no'))} "
                    f"elapsed={time.time()-t0:.1f}s",
                    flush=True,
                )
                save_result_cache(cache)
    save_result_cache(cache)
    return out


def simulate(
    events: list[dict[str, Any]],
    *,
    bankroll0: float,
    contracts: float,
    limit_px: float,
) -> dict[str, Any]:
    outlay = contracts * limit_px
    payout = contracts * 1.0
    equity = bankroll0
    peak = bankroll0
    min_equity = bankroll0
    max_dd = 0.0
    winners = losers = 0
    for e in events:
        equity -= outlay
        if e["won"]:
            equity += payout
            winners += 1
        else:
            losers += 1
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)
        min_equity = min(min_equity, equity)
    return {
        "limit_px": limit_px,
        "outlay_per": outlay,
        "scored": len(events),
        "winners": winners,
        "losers": losers,
        "win_rate": (winners / len(events) * 100.0) if events else 0.0,
        "pnl": equity - bankroll0,
        "equity_end": equity,
        "min_equity": min_equity,
        "max_dd_peak_to_trough": max_dd,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2026-06-01")
    ap.add_argument("--end", default="2026-09-30")
    ap.add_argument("--limit-min", type=float, default=0.90)
    ap.add_argument("--limit-max", type=float, default=0.99)
    ap.add_argument("--limit-step", type=float, default=0.01)
    ap.add_argument("--bankroll", type=float, default=10_000.0)
    ap.add_argument("--allocation-pct", type=float, default=20.0)
    ap.add_argument("--workers", type=int, default=8)
    args = ap.parse_args()

    start = date.fromisoformat(args.start)
    end = date.fromisoformat(args.end)
    days = daterange(start, end)
    contracts = (args.bankroll * (args.allocation_pct / 100.0)) / 1.0
    limits: list[float] = []
    x = args.limit_min
    while x <= args.limit_max + 1e-12:
        limits.append(round(x, 2))
        x += args.limit_step

    print(
        f"SWEEP {start}..{end} days={len(days)} limits={limits} "
        f"bankroll={args.bankroll} contracts={contracts:.0f}",
        flush=True,
    )

    # candidates[limit] = list of {ticker, side, first_time, date_et}
    candidates: dict[float, list[dict[str, Any]]] = {lim: [] for lim in limits}
    tickers_needed: set[str] = set()
    tape_cycles = empty_cycles = 0
    no_hit = {lim: 0 for lim in limits}

    for day in days:
        csv_path = OUT_DIR / f"KXBTC15M_public_trades_{day.isoformat()}_et.csv"
        tickers = kalshi_15m_market_tickers_for_eastern_date("KXBTC15M", day)
        by: dict[str, list[dict[str, Any]]] = defaultdict(list)
        if csv_path.is_file():
            with csv_path.open(encoding="utf-8") as f:
                for r in csv.DictReader(f):
                    by[r["ticker"]].append(r)
        else:
            print(f"WARN missing CSV {csv_path.name}", flush=True)

        day_tape = 0
        for t in tickers:
            rows = by.get(t) or []
            if not rows:
                empty_cycles += 1
                continue
            tape_cycles += 1
            day_tape += 1
            hits = first_hit_by_limit(rows, limits)
            for lim in limits:
                hit = hits[lim]
                if hit is None:
                    no_hit[lim] += 1
                    continue
                side, trade = hit
                candidates[lim].append(
                    {
                        "date_et": day.isoformat(),
                        "ticker": t,
                        "first_side": side,
                        "first_time": trade.get("created_time") or "",
                    }
                )
                tickers_needed.add(t)
        print(f"{day.isoformat()} tape={day_tape}/{len(tickers)}", flush=True)

    print(
        f"tape_cycles={tape_cycles} empty={empty_cycles} "
        f"unique_tickers_needing_result={len(tickers_needed)}",
        flush=True,
    )
    results = resolve_results(sorted(tickers_needed), workers=args.workers)

    summary_rows: list[dict[str, Any]] = []
    print("\n======== LIMIT SWEEP RESULTS ========", flush=True)
    hdr = (
        f"{'limit':>6} {'scored':>7} {'win':>5} {'lose':>6} {'wr%':>6} "
        f"{'pnl':>12} {'end':>10} {'min_eq':>10} {'max_dd':>10} {'unk':>5}"
    )
    print(hdr, flush=True)
    for lim in limits:
        scored_events: list[dict[str, Any]] = []
        unknown = 0
        for c in candidates[lim]:
            mr, err = results.get(c["ticker"], (None, "missing"))
            if mr is None:
                unknown += 1
                continue
            scored_events.append(
                {
                    **c,
                    "market_result": mr,
                    "won": mr == c["first_side"],
                }
            )
        scored_events.sort(key=lambda r: (r["first_time"], r["ticker"]))
        sim = simulate(
            scored_events,
            bankroll0=args.bankroll,
            contracts=contracts,
            limit_px=lim,
        )
        sim["unknown"] = unknown
        sim["candidates"] = len(candidates[lim])
        sim["no_hit"] = no_hit[lim]
        summary_rows.append(sim)
        print(
            f"{lim:6.2f} {sim['scored']:7d} {sim['winners']:5d} {sim['losers']:6d} "
            f"{sim['win_rate']:6.2f} {sim['pnl']:12,.2f} {sim['equity_end']:10,.2f} "
            f"{sim['min_equity']:10,.2f} {sim['max_dd_peak_to_trough']:10,.2f} "
            f"{unknown:5d}",
            flush=True,
        )

    out_csv = OUT_DIR / f"KXBTC15M_longshot_limit_sweep_{start}_{end}_et.csv"
    with out_csv.open("w", newline="", encoding="utf-8") as f:
        fields = [
            "limit_px",
            "outlay_per",
            "candidates",
            "no_hit",
            "unknown",
            "scored",
            "winners",
            "losers",
            "win_rate",
            "pnl",
            "equity_end",
            "min_equity",
            "max_dd_peak_to_trough",
        ]
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for row in summary_rows:
            w.writerow({k: row.get(k, "") for k in fields})
    print(f"\nwrote {out_csv}", flush=True)
    print("SWEEP_DONE", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
