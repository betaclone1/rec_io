#!/usr/bin/env python3
"""
Pull Kalshi public tape for all KXBTC15M markets on one Eastern calendar day → CSV.

Routes by ``GET /historical/cutoff`` ``trades_created_ts``:
  - fills before cutoff → ``GET /historical/trades``
  - fills after cutoff → ``GET /markets/trades``
  - days that straddle → both, deduped by ``trade_id``

See https://docs.kalshi.com/api-reference/historical/get-historical-trades

Example:
  .venv/bin/python3 scripts/backtest/pull_kxbtc15m_public_trades_day_csv.py --date 2026-09-14
"""

from __future__ import annotations

import argparse
import csv
import json
import shutil
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import requests

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from scripts.backtest.helpers.kalshi_ticker_construct import (
    EST,
    kalshi_15m_market_tickers_for_eastern_date,
)

API_BASE = "https://external-api.kalshi.com/trade-api/v2"
MARKETS_TRADES = f"{API_BASE}/markets/trades"
HISTORICAL_TRADES = f"{API_BASE}/historical/trades"
# https://docs.kalshi.com/api-reference/historical/get-historical-trades
# https://docs.kalshi.com/getting_started/historical_data
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


def cache_path_for(cache_dir: Path, ticker: str) -> Path:
    return cache_dir / f"{ticker}.json"


def fetch_trades_cutoff_utc() -> datetime | None:
    """``trades_created_ts`` from GET /historical/cutoff (UTC). None if unavailable."""
    try:
        r = requests.get(
            f"{API_BASE}/historical/cutoff",
            timeout=30,
            headers={
                "Accept": "application/json",
                "User-Agent": "rec_io_public_trades_csv/1.2",
            },
        )
        r.raise_for_status()
        raw = r.json()
        s = (raw or {}).get("trades_created_ts") if isinstance(raw, dict) else None
        if not s:
            return None
        s = str(s).strip()
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def trade_sources_for_eastern_day(
    day: date, cutoff: datetime | None
) -> list[tuple[str, str]]:
    """
    Return (label, url) sources for this Eastern day vs Kalshi trades cutoff.

    Pre-cutoff fills are only on GET /historical/trades; post-cutoff on /markets/trades.
    Days that straddle the cutoff query both and dedupe by trade_id.
    """
    day_start = datetime(day.year, day.month, day.day, 0, 0, tzinfo=EST).astimezone(
        timezone.utc
    )
    # Last settlement of the Eastern day is 23:45 ET (period ending that minute).
    day_end = datetime(day.year, day.month, day.day, 23, 45, tzinfo=EST).astimezone(
        timezone.utc
    )
    if cutoff is None:
        return [("historical", HISTORICAL_TRADES), ("markets", MARKETS_TRADES)]
    if day_end < cutoff:
        return [("historical", HISTORICAL_TRADES)]
    if day_start >= cutoff:
        return [("markets", MARKETS_TRADES)]
    return [("historical", HISTORICAL_TRADES), ("markets", MARKETS_TRADES)]


def load_cached(
    cache_dir: Path,
    ticker: str,
    *,
    expected_sources: list[str],
) -> list[dict[str, Any]] | None:
    p = cache_path_for(cache_dir, ticker)
    if not p.is_file():
        return None
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(raw, dict) or not raw.get("complete"):
        return None
    cached_sources = raw.get("sources")
    if not isinstance(cached_sources, list):
        # Legacy caches (markets-only) are unsafe across the historical cutoff.
        return None
    if sorted(str(s) for s in cached_sources) != sorted(expected_sources):
        return None
    trades = raw.get("trades")
    return list(trades) if isinstance(trades, list) else None


def save_cached(
    cache_dir: Path,
    ticker: str,
    trades: list[dict[str, Any]],
    *,
    sources: list[str],
) -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    p = cache_path_for(cache_dir, ticker)
    payload = {
        "ticker": ticker,
        "complete": True,
        "sources": list(sources),
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "trade_count": len(trades),
        "trades": trades,
    }
    tmp = p.with_suffix(".partial.json")
    tmp.write_text(json.dumps(payload), encoding="utf-8")
    tmp.replace(p)


def _fetch_trades_from_url(
    ticker: str,
    base_url: str,
    *,
    sleep_s: float = 0.05,
    max_attempts: int = 12,
) -> list[dict[str, Any]]:
    trades: list[dict[str, Any]] = []
    cursor: str | None = None
    while True:
        params: dict[str, Any] = {"ticker": ticker, "limit": 1000}
        if cursor:
            params["cursor"] = cursor
        url = f"{base_url}?{urlencode(params)}"
        last_err: Exception | None = None
        body: dict[str, Any] | None = None
        for attempt in range(max_attempts):
            try:
                r = requests.get(
                    url,
                    timeout=90,
                    headers={
                        "Accept": "application/json",
                        "User-Agent": "rec_io_public_trades_csv/1.2",
                    },
                )
                if r.status_code in (429, 500, 502, 503, 504):
                    last_err = RuntimeError(f"HTTP {r.status_code}")
                    time.sleep(min(20.0, 0.5 * (2**attempt)))
                    continue
                # No market / never listed: same as empty tape (maintenance slots).
                if r.status_code == 404:
                    return []
                r.raise_for_status()
                raw = r.json()
                if not isinstance(raw, dict):
                    raise RuntimeError(f"unexpected JSON type: {type(raw)}")
                body = raw
                break
            except Exception as e:
                last_err = e
                time.sleep(min(20.0, 0.5 * (2**attempt)))
        if body is None:
            raise RuntimeError(f"failed {ticker} via {base_url}: {last_err}")
        batch = body.get("trades") or []
        if not isinstance(batch, list):
            batch = []
        trades.extend(batch)
        cursor = body.get("cursor") or None
        if not cursor or not batch:
            break
        if sleep_s:
            time.sleep(sleep_s)
    return trades


def fetch_ticker(
    ticker: str,
    *,
    sources: list[tuple[str, str]],
    sleep_s: float = 0.05,
    max_attempts: int = 12,
) -> tuple[str, list[dict[str, Any]]]:
    """Paginate configured trade sources; dedupe by trade_id when both are used."""
    by_id: dict[str, dict[str, Any]] = {}
    no_id: list[dict[str, Any]] = []
    for _label, url in sources:
        for row in _fetch_trades_from_url(
            ticker, url, sleep_s=sleep_s, max_attempts=max_attempts
        ):
            tid = str(row.get("trade_id") or "").strip()
            if tid:
                by_id[tid] = row
            else:
                no_id.append(row)
    trades = list(by_id.values()) + no_id
    trades.sort(
        key=lambda r: (str(r.get("created_time") or ""), str(r.get("trade_id") or ""))
    )
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
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument(
        "--out",
        default="",
        help="CSV path (default under backend/data/historical_data/kalshi_public_trades/)",
    )
    ap.add_argument(
        "--force-refresh",
        action="store_true",
        help="Ignore per-ticker JSON cache and refetch",
    )
    ap.add_argument(
        "--keep-cache",
        action="store_true",
        help="Keep per-ticker JSON cache after a successful day CSV write (default: delete it)",
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
    cache_dir = out.parent / f".cache_{args.series}_{day.isoformat()}"

    cutoff = fetch_trades_cutoff_utc()
    sources = trade_sources_for_eastern_day(day, cutoff)
    source_labels = [s[0] for s in sources]

    print(f"series={args.series} day_et={day} tickers={len(tickers)} workers={args.workers}", flush=True)
    print(f"first={tickers[0]} last={tickers[-1]}", flush=True)
    print(f"out={out}", flush=True)
    print(f"cache={cache_dir}", flush=True)
    print(
        f"trades_cutoff={cutoff.isoformat() if cutoff else 'unavailable'} "
        f"sources={','.join(source_labels)}",
        flush=True,
    )

    by_ticker: dict[str, list[dict[str, Any]]] = {}
    todo: list[str] = []
    for t in tickers:
        if not args.force_refresh:
            cached = load_cached(cache_dir, t, expected_sources=source_labels)
            if cached is not None:
                by_ticker[t] = cached
                continue
        todo.append(t)
    print(f"cached={len(by_ticker)} todo={len(todo)}", flush=True)

    t0 = time.time()
    done = len(by_ticker)
    failed: list[tuple[str, str]] = []

    def _one(ticker: str) -> tuple[str, list[dict[str, Any]]]:
        ticker, rows = fetch_ticker(ticker, sources=sources)
        save_cached(cache_dir, ticker, rows, sources=source_labels)
        return ticker, rows

    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        futs = {pool.submit(_one, t): t for t in todo}
        for fut in as_completed(futs):
            t = futs[fut]
            try:
                ticker, rows = fut.result()
                by_ticker[ticker] = rows
                done += 1
                total = sum(len(v) for v in by_ticker.values())
                print(
                    f"[{done:3d}/{len(tickers)}] {ticker} n={len(rows)} "
                    f"total={total} left={len(tickers)-done} elapsed={time.time()-t0:.1f}s",
                    flush=True,
                )
            except Exception as e:
                failed.append((t, str(e)))
                print(f"FAIL {t}: {e}", flush=True)

    # Serial retry for failures (rate-limit friendly)
    still_failed: list[tuple[str, str]] = []
    for t, _err in failed:
        try:
            time.sleep(1.0)
            ticker, rows = _one(t)
            by_ticker[ticker] = rows
            done += 1
            print(f"RETRY_OK [{done:3d}/{len(tickers)}] {ticker} n={len(rows)}", flush=True)
        except Exception as e:
            still_failed.append((t, str(e)))
            print(f"RETRY_FAIL {t}: {e}", flush=True)

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
        f"failed={len(still_failed)} bytes={out.stat().st_size} "
        f"wrote_at={datetime.now(timezone.utc).isoformat()}",
        flush=True,
    )
    if still_failed:
        for t, err in still_failed:
            print(f"  missing {t}: {err}", flush=True)
        # Keep cache so a resume can refill gaps without re-pulling successes.
        return 1
    # Day CSV is the work product; drop duplicate per-ticker JSON to free disk.
    if not args.keep_cache and cache_dir.is_dir():
        try:
            shutil.rmtree(cache_dir)
            print(f"flushed_cache={cache_dir}", flush=True)
        except OSError as e:
            print(f"cache_flush_failed {cache_dir}: {e}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
