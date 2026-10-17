#!/usr/bin/env python3
"""
Bulk-fetch KXBTC15M market_result via list endpoints (not per-ticker).

  1) GET /historical/markets?series_ticker=KXBTC15M  (archived / past cutoff)
  2) GET /markets?series_ticker=KXBTC15M&status=settled  (still on live tier)

Merges by ticker, writes JSON cache + CSV for offline longshot sweeps.

See https://docs.kalshi.com/getting_started/historical_data
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import requests

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from backend.core.kalshi_event_market_fetch import normalize_market_result_field

API_BASE = "https://external-api.kalshi.com/trade-api/v2"
HEADERS = {"Accept": "application/json", "User-Agent": "rec_io_market_results_bulk/1.0"}
OUT_DIR = _ROOT / "backend" / "data" / "historical_data" / "kalshi_public_trades"
CACHE_JSON = OUT_DIR / ".cache_market_result_by_ticker.json"
CSV_OUT = OUT_DIR / "KXBTC15M_market_results_bulk.csv"


def _get(path: str, params: dict[str, Any], *, max_attempts: int = 12) -> dict[str, Any]:
    url = f"{API_BASE}{path}?{urlencode(params)}"
    last_err: Exception | None = None
    for attempt in range(max_attempts):
        try:
            r = requests.get(url, headers=HEADERS, timeout=90)
            if r.status_code in (429, 500, 502, 503, 504):
                time.sleep(min(30.0, 0.5 * (2**attempt)))
                last_err = RuntimeError(f"HTTP {r.status_code}")
                continue
            r.raise_for_status()
            data = r.json()
            if not isinstance(data, dict):
                raise RuntimeError(f"bad JSON type {type(data)}")
            return data
        except Exception as e:
            last_err = e
            time.sleep(min(30.0, 0.5 * (2**attempt)))
    raise RuntimeError(f"failed {path}: {last_err}")


def paginate(path: str, base_params: dict[str, Any], *, label: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    cursor: str | None = None
    page = 0
    t0 = time.time()
    while True:
        page += 1
        params = dict(base_params)
        if cursor:
            params["cursor"] = cursor
        body = _get(path, params)
        batch = body.get("markets") or []
        if not isinstance(batch, list):
            batch = []
        out.extend([m for m in batch if isinstance(m, dict)])
        cursor = body.get("cursor") or None
        print(
            f"[{label}] page={page} batch={len(batch)} total={len(out)} "
            f"elapsed={time.time()-t0:.1f}s",
            flush=True,
        )
        if not cursor or not batch:
            break
        time.sleep(0.05)
    return out


def ingest(
    markets: list[dict[str, Any]],
    *,
    source: str,
    into: dict[str, dict[str, Any]],
) -> int:
    added = 0
    for m in markets:
        t = str(m.get("ticker") or "").strip()
        if not t:
            continue
        mr = normalize_market_result_field(m.get("result"))
        if mr not in ("yes", "no"):
            continue
        # Prefer first authoritative result; do not overwrite yes/no with another.
        if t in into and into[t].get("mr") in ("yes", "no"):
            continue
        into[t] = {
            "mr": mr,
            "err": None,
            "source": source,
            "status": m.get("status"),
            "close_time": m.get("close_time"),
        }
        added += 1
    return added


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--series", default="KXBTC15M")
    ap.add_argument("--limit", type=int, default=1000)
    args = ap.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    by_ticker: dict[str, dict[str, Any]] = {}

    # Load existing yes/no cache so we only fill gaps if re-run.
    if CACHE_JSON.is_file():
        try:
            prev = json.loads(CACHE_JSON.read_text(encoding="utf-8"))
            if isinstance(prev, dict):
                for t, v in prev.items():
                    if isinstance(v, dict) and v.get("mr") in ("yes", "no"):
                        by_ticker[str(t)] = {
                            "mr": v["mr"],
                            "err": v.get("err"),
                            "source": v.get("source") or "cache",
                            "status": v.get("status"),
                            "close_time": v.get("close_time"),
                        }
        except Exception:
            pass
    print(f"seed_cache={len(by_ticker)}", flush=True)

    hist = paginate(
        "/historical/markets",
        {"series_ticker": args.series, "limit": min(max(1, args.limit), 1000)},
        label="historical",
    )
    n_hist = ingest(hist, source="historical/markets", into=by_ticker)
    print(f"ingested_from_historical={n_hist} cache_size={len(by_ticker)}", flush=True)

    live = paginate(
        "/markets",
        {
            "series_ticker": args.series,
            "status": "settled",
            "limit": min(max(1, args.limit), 1000),
        },
        label="live_settled",
    )
    n_live = ingest(live, source="markets/settled", into=by_ticker)
    print(f"ingested_from_live={n_live} cache_size={len(by_ticker)}", flush=True)

    # Persist JSON in the shape the limit sweep already reads.
    cache_out = {
        t: {"mr": v["mr"], "err": v.get("err"), "source": v.get("source")}
        for t, v in sorted(by_ticker.items())
    }
    tmp = CACHE_JSON.with_suffix(".partial.json")
    tmp.write_text(json.dumps(cache_out, separators=(",", ":"), sort_keys=True), encoding="utf-8")
    tmp.replace(CACHE_JSON)

    with CSV_OUT.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(
            f,
            fieldnames=["ticker", "market_result", "source", "status", "close_time"],
        )
        w.writeheader()
        for t, v in sorted(by_ticker.items()):
            w.writerow(
                {
                    "ticker": t,
                    "market_result": v.get("mr"),
                    "source": v.get("source"),
                    "status": v.get("status") or "",
                    "close_time": v.get("close_time") or "",
                }
            )

    # Coverage for Jun–Sep 2026 synthetic tickers that have day CSVs.
    from datetime import date, timedelta
    from scripts.backtest.helpers.kalshi_ticker_construct import (
        kalshi_15m_market_tickers_for_eastern_date,
    )

    start, end = date(2026, 6, 1), date(2026, 9, 30)
    need = 0
    have = 0
    d = start
    while d <= end:
        csv_path = OUT_DIR / f"{args.series}_public_trades_{d.isoformat()}_et.csv"
        if csv_path.is_file():
            for t in kalshi_15m_market_tickers_for_eastern_date(args.series, d):
                need += 1
                if t in by_ticker:
                    have += 1
        d += timedelta(days=1)

    print(f"wrote {CACHE_JSON}", flush=True)
    print(f"wrote {CSV_OUT}", flush=True)
    print(
        f"jun_sep_ticker_slots_with_csv={need} with_result={have} "
        f"missing={need - have}",
        flush=True,
    )
    print("BULK_RESULTS_DONE", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
