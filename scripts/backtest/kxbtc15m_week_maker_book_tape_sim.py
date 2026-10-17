#!/usr/bin/env python3
"""
Week maker sim: rest 2000@0.01 on YES and NO at cycle open, join behind opening
book depth, fill from public tape at exact 0.01, cancel the other side on first fill.

Uses cycle packages (opening book depth) + day public-trade CSVs.
"""
from __future__ import annotations

import argparse
import csv
import json
import statistics
import tarfile
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from scripts.backtest.helpers.kalshi_ticker_construct import (
    kalshi_15m_market_tickers_for_eastern_date,
)

_UTC = timezone.utc
PKG_ROOT = Path("backend/data/historical_data/backtesting_data/KXBTC15M/2026")
TAPE_ROOT = Path("backend/data/historical_data/kalshi_public_trades")
MON_FOLDER = {
    1: "2026_01_JAN",
    2: "2026_02_FEB",
    3: "2026_03_MAR",
    4: "2026_04_APR",
    5: "2026_05_MAY",
    6: "2026_06_JUN",
    7: "2026_07_JUL",
    8: "2026_08_AUG",
    9: "2026_09_SEP",
    10: "2026_10_OCT",
    11: "2026_11_NOV",
    12: "2026_12_DEC",
}


def _parse_ts(raw: str) -> Optional[datetime]:
    s = (raw or "").strip()
    if not s:
        return None
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_UTC)
    return dt.astimezone(_UTC)


def _depth_at_01(book: Dict[str, Any]) -> float:
    total = 0.0
    for k, v in (book or {}).items():
        try:
            if abs(float(k) - 0.01) < 1e-9:
                total += float(v)
        except (TypeError, ValueError):
            continue
    return total


def _pkg_path(ticker: str, d: date) -> Path:
    return PKG_ROOT / MON_FOLDER[d.month] / f"{ticker}.tar.xz"


def opening_depth_01(pkg_path: Path) -> Tuple[float, float, datetime, Optional[str]]:
    """Return (yes_01, no_01, open_utc, market_result) from package without full delta replay."""
    with tarfile.open(pkg_path, "r:xz") as tar:
        meta_raw = tar.extractfile("meta.json")
        mm_raw = tar.extractfile("market_meta.json")
        snap_raw = tar.extractfile("snapshot.csv")
        meta = json.loads(meta_raw.read().decode()) if meta_raw else {}
        mm = json.loads(mm_raw.read().decode()) if mm_raw else {}
        open_utc = _parse_ts(meta["cycle_open_utc"])
        mr = (mm.get("market_result") or meta.get("market_result") or "")
        mr = str(mr).strip().lower() if mr else None
        if mr not in ("yes", "no"):
            mr = None
        text = snap_raw.read().decode() if snap_raw else ""
    rows = list(csv.DictReader(text.splitlines())) if text else []
    yes_d = no_d = 0.0
    for s in rows:
        yes = json.loads(s["yes"] or "{}") if isinstance(s.get("yes"), str) else (s.get("yes") or {})
        no = json.loads(s["no"] or "{}") if isinstance(s.get("no"), str) else (s.get("no") or {})
        if not yes and not no:
            continue
        yes_d = _depth_at_01(yes)
        no_d = _depth_at_01(no)
        break
    assert open_utc is not None
    return yes_d, no_d, open_utc, mr


def load_day_tape(d: date) -> Dict[str, List[dict]]:
    p = TAPE_ROOT / f"KXBTC15M_public_trades_{d.isoformat()}_et.csv"
    by: Dict[str, List[dict]] = defaultdict(list)
    if not p.is_file():
        return by
    with p.open() as f:
        for r in csv.DictReader(f):
            by[r["ticker"]].append(r)
    return by


@dataclass
class SimResult:
    ticker: str
    date_et: str
    won: Optional[bool]
    side: Optional[str]
    fill_qty: float
    outlay: float
    pnl: float
    ahead_yes: float
    ahead_no: float
    ahead_fill_side: float
    t_open_to_first_fill: Optional[float]
    t_first_to_full: Optional[float]
    ttc_at_full: Optional[float]
    ttc_at_first: Optional[float]
    cum_01_after_ahead: float
    burst_contracts_1s: float
    burst_contracts_5s: float
    full_2000: bool
    any_fill: bool
    close_utc: datetime
    notes: str = ""
    flags: Dict[str, Any] = field(default_factory=dict)


def simulate_market(
    ticker: str,
    d: date,
    trades: List[dict],
    *,
    contracts: float,
    limit: float,
    mr: Optional[str],
    ahead_yes: float,
    ahead_no: float,
    open_utc: datetime,
    close_utc: datetime,
) -> SimResult:
    # Rest both sides at open behind opening depth.
    ahead = {"yes": max(0.0, ahead_yes), "no": max(0.0, ahead_no)}
    filled = {"yes": 0.0, "no": 0.0}
    resting = {"yes": contracts, "no": contracts}
    active = {"yes": True, "no": True}
    first_fill_ts: Optional[datetime] = None
    full_ts: Optional[datetime] = None
    fill_side: Optional[str] = None
    cum_after_ahead = 0.0
    fill_events: List[Tuple[datetime, float]] = []

    ordered = sorted(trades, key=lambda r: (r.get("created_time") or "", r.get("trade_id") or ""))
    for r in ordered:
        ts = _parse_ts(r.get("created_time") or "")
        if ts is None or ts < open_utc:
            continue
        try:
            y = round(float(r["yes_price_dollars"]), 2)
            n = round(float(r["no_price_dollars"]), 2)
            qty = float(r.get("count_fp") or r.get("count") or 0)
        except (TypeError, ValueError):
            continue
        if qty <= 0:
            continue
        side = None
        if abs(y - limit) < 1e-9:
            side = "yes"
        elif abs(n - limit) < 1e-9:
            side = "no"
        else:
            continue
        if not active[side]:
            continue
        # Consume depth ahead of us, then our resting size.
        eat_ahead = min(qty, ahead[side])
        ahead[side] -= eat_ahead
        rem = qty - eat_ahead
        if rem <= 0:
            continue
        take = min(rem, resting[side])
        if take <= 0:
            continue
        filled[side] += take
        resting[side] -= take
        cum_after_ahead += take
        fill_events.append((ts, take))
        if first_fill_ts is None:
            first_fill_ts = ts
            fill_side = side
            # Cancel opposite side immediately on first fill.
            other = "no" if side == "yes" else "yes"
            active[other] = False
            resting[other] = 0.0
        if full_ts is None and filled[side] >= contracts - 1e-9:
            full_ts = ts
            # Stop once flat-size filled on the active side.
            active[side] = False

    side = fill_side
    fill_qty = filled[side] if side else 0.0
    outlay = fill_qty * limit
    won: Optional[bool] = None
    pnl = 0.0
    if side and mr in ("yes", "no") and fill_qty > 0:
        won = mr == side
        pnl = (fill_qty if won else 0.0) - outlay
    elif fill_qty > 0:
        pnl = -outlay  # unknown result: count premium only as note

    t_open_first = (first_fill_ts - open_utc).total_seconds() if first_fill_ts else None
    t_first_full = (full_ts - first_fill_ts).total_seconds() if (full_ts and first_fill_ts) else None
    ttc_full = (close_utc - full_ts).total_seconds() if full_ts else None
    ttc_first = (close_utc - first_fill_ts).total_seconds() if first_fill_ts else None

    burst_1 = burst_5 = 0.0
    if first_fill_ts and fill_events:
        for ts, q in fill_events:
            dt = (ts - first_fill_ts).total_seconds()
            if dt <= 1.0 + 1e-9:
                burst_1 += q
            if dt <= 5.0 + 1e-9:
                burst_5 += q

    ahead_side = ahead_yes if side == "yes" else (ahead_no if side == "no" else 0.0)
    return SimResult(
        ticker=ticker,
        date_et=d.isoformat(),
        won=won,
        side=side,
        fill_qty=fill_qty,
        outlay=outlay,
        pnl=pnl,
        ahead_yes=ahead_yes,
        ahead_no=ahead_no,
        ahead_fill_side=ahead_side,
        t_open_to_first_fill=t_open_first,
        t_first_to_full=t_first_full,
        ttc_at_full=ttc_full,
        ttc_at_first=ttc_first,
        cum_01_after_ahead=cum_after_ahead,
        burst_contracts_1s=burst_1,
        burst_contracts_5s=burst_5,
        full_2000=fill_qty >= contracts - 1e-9,
        any_fill=fill_qty > 1e-9,
        close_utc=close_utc,
        flags={
            "partial": 0 < fill_qty < contracts - 1e-9,
            "no_fill": fill_qty <= 1e-9,
            "ttc_full_lt_30": (ttc_full is not None and ttc_full < 30),
            "ttc_first_lt_30": (ttc_first is not None and ttc_first < 30),
            "ahead_gt_5k": ahead_side > 5000,
            "ahead_gt_10k": ahead_side > 10000,
            "burst1_ge_2000": burst_1 >= contracts - 1e-9,
            "open_to_first_lt_60": (t_open_first is not None and t_open_first < 60),
            "open_to_first_gt_600": (t_open_first is not None and t_open_first > 600),
        },
    )


def _pct(xs: List[float], p: float) -> Optional[float]:
    if not xs:
        return None
    xs = sorted(xs)
    return xs[int(p / 100 * (len(xs) - 1))]


def _summarize(label: str, rows: List[SimResult], contracts: float, limit: float) -> None:
    n = len(rows)
    fills = [r for r in rows if r.any_fill]
    full = [r for r in fills if r.full_2000]
    partial = [r for r in fills if not r.full_2000]
    scored = [r for r in fills if r.won is not None]
    wins = [r for r in scored if r.won]
    losses = [r for r in scored if not r.won]
    pnl = sum(r.pnl for r in scored)
    # equity path chronological
    bank = 10_000.0
    peak = min_eq = bank
    max_dd = 0.0
    for r in sorted(scored, key=lambda x: (x.date_et, x.ticker)):
        bank += r.pnl
        peak = max(peak, bank)
        max_dd = max(max_dd, peak - bank)
        min_eq = min(min_eq, bank)
    print(f"\n=== {label} ===")
    print(
        f"markets={n} any_fill={len(fills)} full_{contracts:.0f}={len(full)} "
        f"partial={len(partial)} no_fill={n - len(fills)}"
    )
    if scored:
        print(
            f"scored={len(scored)} wins={len(wins)} losses={len(losses)} "
            f"wr={100 * len(wins) / len(scored):.2f}% pnl=${pnl:,.2f}"
        )
        print(f"equity_end=${bank:,.2f} min_eq=${min_eq:,.2f} max_dd=${max_dd:,.2f}")
    for name, xs in [("wins", wins), ("losses", losses), ("full", full), ("partial", partial)]:
        if not xs:
            print(f"  {name}: empty")
            continue
        aq = [r.fill_qty for r in xs]
        ah = [r.ahead_fill_side for r in xs]
        t0 = [r.t_open_to_first_fill for r in xs if r.t_open_to_first_fill is not None]
        tf = [r.t_first_to_full for r in xs if r.t_first_to_full is not None]
        print(
            f"  {name} n={len(xs)} fill_qty p50={_pct(aq,50):.1f} mean={statistics.mean(aq):.1f} "
            f"ahead p50={_pct(ah,50):.1f} mean={statistics.mean(ah):.1f}"
        )
        if t0:
            print(
                f"    open→first_fill s: p50={_pct(t0,50):.1f} p90={_pct(t0,90):.1f} mean={statistics.mean(t0):.1f}"
            )
        if tf:
            print(
                f"    first→full s: p50={_pct(tf,50):.1f} p90={_pct(tf,90):.1f} mean={statistics.mean(tf):.1f}"
            )


def _flag_table(scored: List[SimResult]) -> None:
    wins = [r for r in scored if r.won]
    losses = [r for r in scored if not r.won]
    keys = sorted({k for r in scored for k in r.flags})
    print("\n=== flag rates (among scored fills) ===")
    print(f"{'flag':28} {'wins':>10} {'losses':>10} {'lift_loss':>10}")
    for k in keys:
        ww = sum(1 for r in wins if r.flags.get(k)) / max(1, len(wins))
        ll = sum(1 for r in losses if r.flags.get(k)) / max(1, len(losses))
        lift = (ll / ww) if ww > 1e-12 else float("inf") if ll else 0.0
        print(f"{k:28} {100*ww:9.1f}% {100*ll:9.1f}% {lift:10.2f}x")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2026-08-30")
    ap.add_argument("--end", default="2026-09-05")
    ap.add_argument("--contracts", type=float, default=2000.0)
    ap.add_argument("--limit", type=float, default=0.01)
    ap.add_argument(
        "--out",
        default="backend/data/historical_data/kalshi_public_trades/"
        "KXBTC15M_week_maker_book_tape_2026-08-30_2026-09-05.csv",
    )
    args = ap.parse_args()
    start = date.fromisoformat(args.start)
    end = date.fromisoformat(args.end)
    contracts = float(args.contracts)
    limit = float(args.limit)

    results: List[SimResult] = []
    miss_pkg = miss_tape = miss_mr = 0
    d = start
    while d <= end:
        tape = load_day_tape(d)
        day_n = 0
        for t in kalshi_15m_market_tickers_for_eastern_date("KXBTC15M", d):
            pp = _pkg_path(t, d)
            if not pp.is_file():
                miss_pkg += 1
                continue
            rows = tape.get(t) or []
            if not rows:
                miss_tape += 1
                continue
            try:
                ay, an, open_utc, mr = opening_depth_01(pp)
            except Exception as e:
                print(f"PKG_FAIL {t}: {e}", flush=True)
                miss_pkg += 1
                continue
            # close from meta via opening_depth path — re-read close cheaply
            with tarfile.open(pp, "r:xz") as tar:
                meta = json.loads(tar.extractfile("meta.json").read().decode())
            close_utc = _parse_ts(meta["cycle_close_utc"])
            assert close_utc is not None
            if mr is None:
                # fall back to cache
                miss_mr += 0
            sim = simulate_market(
                t,
                d,
                rows,
                contracts=contracts,
                limit=limit,
                mr=mr,
                ahead_yes=ay,
                ahead_no=an,
                open_utc=open_utc,
                close_utc=close_utc,
            )
            if sim.won is None and sim.any_fill:
                # try cache
                cache_p = TAPE_ROOT / ".cache_market_result_by_ticker.json"
                if cache_p.is_file():
                    cache = json.loads(cache_p.read_text())
                    mr2 = (cache.get(t) or {}).get("mr")
                    if mr2 in ("yes", "no") and sim.side:
                        sim.won = mr2 == sim.side
                        sim.pnl = (sim.fill_qty if sim.won else 0.0) - sim.outlay
            results.append(sim)
            day_n += 1
        print(f"{d.isoformat()} simulated={day_n}", flush=True)
        d += timedelta(days=1)

    print(
        f"\ncoverage miss_pkg={miss_pkg} miss_tape={miss_tape} total_sim={len(results)}",
        flush=True,
    )
    _summarize(f"{start}..{end} maker join-behind-open depth @ {limit}", results, contracts, limit)
    scored = [r for r in results if r.any_fill and r.won is not None]
    _flag_table(scored)

    # Counterfactual: only full 2000 fills
    full_only = [r for r in results if r.full_2000 and r.won is not None]
    if full_only:
        pnl = sum(r.pnl for r in full_only)
        w = sum(1 for r in full_only if r.won)
        print(
            f"\n--- full-{contracts:.0f} only --- scored={len(full_only)} wr={100*w/len(full_only):.2f}% pnl=${pnl:,.2f}"
        )

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="") as f:
        fields = [
            "date_et",
            "ticker",
            "side",
            "won",
            "fill_qty",
            "outlay",
            "pnl",
            "ahead_yes",
            "ahead_no",
            "ahead_fill_side",
            "t_open_to_first_fill",
            "t_first_to_full",
            "ttc_at_first",
            "ttc_at_full",
            "burst_contracts_1s",
            "burst_contracts_5s",
            "full_2000",
            "any_fill",
        ] + sorted({k for r in results for k in r.flags})
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in results:
            row = {
                "date_et": r.date_et,
                "ticker": r.ticker,
                "side": r.side or "",
                "won": "" if r.won is None else int(r.won),
                "fill_qty": f"{r.fill_qty:.4f}",
                "outlay": f"{r.outlay:.4f}",
                "pnl": f"{r.pnl:.4f}",
                "ahead_yes": f"{r.ahead_yes:.4f}",
                "ahead_no": f"{r.ahead_no:.4f}",
                "ahead_fill_side": f"{r.ahead_fill_side:.4f}",
                "t_open_to_first_fill": ""
                if r.t_open_to_first_fill is None
                else f"{r.t_open_to_first_fill:.3f}",
                "t_first_to_full": "" if r.t_first_to_full is None else f"{r.t_first_to_full:.3f}",
                "ttc_at_first": "" if r.ttc_at_first is None else f"{r.ttc_at_first:.3f}",
                "ttc_at_full": "" if r.ttc_at_full is None else f"{r.ttc_at_full:.3f}",
                "burst_contracts_1s": f"{r.burst_contracts_1s:.4f}",
                "burst_contracts_5s": f"{r.burst_contracts_5s:.4f}",
                "full_2000": int(r.full_2000),
                "any_fill": int(r.any_fill),
            }
            for k, v in r.flags.items():
                row[k] = int(bool(v))
            w.writerow(row)
    print(f"wrote {out}", flush=True)
    print("DONE", flush=True)


if __name__ == "__main__":
    main()
