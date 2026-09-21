#!/usr/bin/env python3
"""
Pull Kalshi public tape for all KXBTC15M markets on one Eastern calendar day → CSV.

Example:
  .venv/bin/python3 scripts/backtest/pull_kxbtc15m_public_trades_day_csv.py --date 2026-09-14
"""

from __future__ import annotations

import argparse
import csv
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import requests

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from scripts.backtest.helpers.kalshi_ticker_construct import (
    kalshi_15m_market_tickers_for_eastern_date,
)

BASE = "https://external-api.kalshi.com/trade-api/v2/markets/trades"
PREFERRED_COLS = [
    "trade_id",
    "ticker",
    "created_time",
    "taker_side",
    "taker_outcome_side",
    "taker_book_side",
    "yes_price",
    "no_price",
    "yes_price_dollars",
    "no_price_dollars",
    "count",
    "count_fp",
    "is_block_trade",
    "ts",
]


def fetch_ticker(ticker: str, *, sleep_s: float = 0.02) -> tuple[str, list[dict[str, Any]]]:
    trades: list[dict[str, Any]] = []
    cursor: str | None = None
    while True:
        params: dict[str, Any] = {"ticker": ticker, "limit": 1000}
        if cursor:
            params["cursor"] = cursor
        url = f"{BASE}?{urlencode(params)}"
        last_err: Exception | None = None
        body: dict[str, Any] | None = None
        for attempt in range(8):
            try:
                r = requests.get(
                    url,
                    timeout=60,
                    headers={
                        "Accept": "application/json",
                        "User-Agent": "rec_io_public_trades_csv/1.0",
                    },
                )
                if r.status_code in (429, 500, 502, 503, 504):
                    time.sleep(min(12.0, 0.4 * (2**attempt)))
                    continue
                r.raise_for_status()
                raw = r.json()
                if not isinstance(raw, dict):
                    raise RuntimeError(f"unexpected JSON type: {type(raw)}")
                body = raw
                break
            except Exception as e:
                last_err = e
                time.sleep(min(12.0, 0.4 * (2**attempt)))
        if body is None:
            raise RuntimeError(f"failed {ticker}: {last_err}")
        batch = body.get("trades") or []
        if not isinstance(batch, list):
            batch = []
        trades.extend(batch)
        cursor = body.get("cursor") or None
        if not cursor or not batch:
            break
        if sleep_s:
            time.sleep(sleep_s)
    return ticker, trades


def column_order(rows: list[dict[str, Any]]) -> list[str]:
    keys: list[str] = []
    seen: set[str] = set()
    for k in PREFERRED_COLS:
        if any(k in r for r in rows):
            keys.append(k)
            seen.add(k)
    for r in rows:
        for k in r.keys():
            if k not in seen:
                keys.append(k)
                seen.add(k)
    return keys


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", required=True, help="Eastern calendar day YYYY-MM-DD")
    ap.add_argument("--series", default="KXBTC15M")
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument(
        "--out",
        default="",
        help="CSV path (default under backend/data/historical_data/kalshi_public_trades/)",
    )
    args = ap.parse_args()
    day = date.fromisoformat(args.date)
    tickers = kalshi_15m_market_tickers_for_eastern_date(args.series, day)
    out = Path(args.out) if args.out else (
        _ROOT
        / "backend"
        / "data"
        / "historical_data"
        / "kalshi_public_trades"
        / f"{args.series}_public_trades_{day.isoformat()}_et.csv"
    )
    out.parent.mkdir(parents=True, exist_ok=True)

    print(f"series={args.series} day_et={day} tickers={len(tickers)} workers={args.workers}", flush=True)
    print(f"first={tickers[0]} last={tickers[-1]}", flush=True)
    print(f"out={out}", flush=True)

    by_ticker: dict[str, list[dict[str, Any]]] = {}
    t0 = time.time()
    done = 0
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        futs = {pool.submit(fetch_ticker, t): t for t in tickers}
        for fut in as_completed(futs):
            ticker, rows = fut.result()
            by_ticker[ticker] = rows
            done += 1
            if done % 8 == 0 or done == len(tickers):
                total = sum(len(v) for v in by_ticker.values())
                empty = sum(1 for v in by_ticker.values() if not v)
                print(
                    f"[{done:3d}/{len(tickers)}] latest={ticker} n={len(rows)} "
                    f"total={total} empty={empty} elapsed={time.time()-t0:.1f}s",
                    flush=True,
                )

    all_rows: list[dict[str, Any]] = []
    for t in tickers:
        all_rows.extend(by_ticker.get(t) or [])
    all_rows.sort(
        key=lambda r: (str(r.get("created_time") or ""), str(r.get("trade_id") or ""))
    )
    keys = column_order(all_rows) if all_rows else PREFERRED_COLS
    with out.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=keys, extrasaction="ignore")
        w.writeheader()
        for r in all_rows:
            w.writerow({k: r.get(k, "") for k in keys})

    empty = sum(1 for t in tickers if not by_ticker.get(t))
    print(
        f"DONE rows={len(all_rows)} empty_tickers={empty}/{len(tickers)} "
        f"bytes={out.stat().st_size} wrote_at={datetime.utcnow().isoformat()}Z",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
