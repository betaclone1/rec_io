#!/usr/bin/env python3
"""
Fetch Kalshi market trades for one ticker and upsert into ``backtest.kalshi_historical_trades_api``.

**Default endpoint:** ``GET /trade-api/v2/markets/trades`` (public tape; same ``Trade`` shape as historical).

Use ``--endpoint historical`` for ``GET /historical/trades`` only when the market is past Kalshi's
historical cutoff; until then that API often returns an empty ``trades`` array.

- Markets trades: https://docs.kalshi.com/api-reference/market/get-trades
- Historical trades: https://docs.kalshi.com/api-reference/historical/get-historical-trades

Uses prod credentials for signed requests (optional; public ``markets/trades`` works unsigned —
we still sign for consistency with rate limits).

Example:
  .venv/bin/python3 scripts/backtest/fetch_kalshi_historical_trades_to_backtest.py \\
    --ticker KXBTC15M-26APR120945-45
"""

from __future__ import annotations

import argparse
import base64
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import requests
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from dotenv import dotenv_values

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from backend.core.config.database import get_system_postgresql_connection
from backend.util.paths import get_kalshi_credentials_dir

BASE_URL = "https://api.elections.kalshi.com/trade-api/v2"
# Path suffix only; full sign path is /trade-api/v2 + path
ENDPOINT_PATHS = {
    "markets": "/markets/trades",
    "historical": "/historical/trades",
}


def load_kalshi_credentials() -> tuple[str, Path]:
    d = Path(get_kalshi_credentials_dir()) / "prod"
    env = dotenv_values(d / ".env")
    key_id = env.get("KALSHI_API_KEY_ID")
    rel = env.get("KALSHI_PRIVATE_KEY_PATH") or "kalshi.pem"
    key_path = d / Path(rel).name
    return str(key_id or ""), key_path


def generate_kalshi_signature(method: str, full_path: str, timestamp: str, key_path: str) -> str:
    with open(key_path, "rb") as key_file:
        private_key = serialization.load_pem_private_key(
            key_file.read(), password=None, backend=default_backend()
        )
    message = f"{timestamp}{method.upper()}{full_path}".encode("utf-8")
    signature = private_key.sign(
        message,
        padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.DIGEST_LENGTH),
        hashes.SHA256(),
    )
    return base64.b64encode(signature).decode("utf-8")


def _parse_created_time(s: str) -> datetime:
    if not s:
        raise ValueError("created_time missing")
    s = s.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def fetch_all_pages(
    ticker: str,
    *,
    api_path: str,
    limit: int,
    min_ts: int | None,
    max_ts: int | None,
    key_id: str,
    key_path: str,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Return (trades, cursors_seen_for_debug)."""
    sign_path = f"/trade-api/v2{api_path}"
    out: list[dict[str, Any]] = []
    cursors: list[str] = []
    cursor: str | None = None
    page = 0
    while True:
        page += 1
        params: list[tuple[str, str]] = [
            ("ticker", ticker),
            ("limit", str(min(max(1, limit), 1000))),
        ]
        if min_ts is not None:
            params.append(("min_ts", str(min_ts)))
        if max_ts is not None:
            params.append(("max_ts", str(max_ts)))
        if cursor:
            params.append(("cursor", cursor))

        q = urlencode(params)
        url = f"{BASE_URL}{api_path}?{q}"

        ts_ms = str(int(time.time() * 1000))
        sig = generate_kalshi_signature("GET", sign_path, ts_ms, key_path)
        headers = {
            "Accept": "application/json",
            "User-Agent": "rec_io_backtest_historical_trades/1.0",
            "KALSHI-ACCESS-KEY": key_id,
            "KALSHI-ACCESS-TIMESTAMP": ts_ms,
            "KALSHI-ACCESS-SIGNATURE": sig,
        }
        r = requests.get(url, headers=headers, timeout=60)
        r.raise_for_status()
        data = r.json()
        if not isinstance(data, dict):
            raise RuntimeError(f"unexpected JSON type: {type(data)}")
        trades = data.get("trades") or []
        out.extend(trades)
        cursor = data.get("cursor") or None
        if cursor:
            cursors.append(cursor)
        if not cursor:
            break
        if page > 10_000:
            raise RuntimeError("pagination exceeded safety limit (10000 pages)")
    return out, cursors


def upsert_rows(trades: list[dict[str, Any]]) -> tuple[int, int]:
    """Returns (inserted, skipped_or_unchanged)."""
    conn = get_system_postgresql_connection()
    if conn is None:
        raise RuntimeError("Could not connect to PostgreSQL")
    inserted = 0
    skipped = 0
    try:
        with conn.cursor() as cur:
            for t in trades:
                tid = t.get("trade_id")
                if not tid:
                    skipped += 1
                    continue
                try:
                    ct = _parse_created_time(str(t.get("created_time") or ""))
                except Exception:
                    skipped += 1
                    continue
                row = (
                    str(tid),
                    str(t.get("ticker") or ""),
                    t.get("count_fp"),
                    t.get("yes_price_dollars"),
                    t.get("no_price_dollars"),
                    str(t.get("taker_side") or ""),
                    ct,
                )
                cur.execute(
                    """
                    INSERT INTO backtest.kalshi_historical_trades_api (
                        trade_id, ticker, count_fp, yes_price_dollars, no_price_dollars,
                        taker_side, created_time
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (trade_id) DO NOTHING
                    """,
                    row,
                )
                if cur.rowcount:
                    inserted += 1
                else:
                    skipped += 1
        conn.commit()
    finally:
        conn.close()
    return inserted, skipped


def main() -> int:
    p = argparse.ArgumentParser(description="Fetch Kalshi historical trades into backtest schema.")
    p.add_argument("--ticker", required=True, help="Market ticker, e.g. KXBTC15M-26APR120945-45")
    p.add_argument(
        "--endpoint",
        choices=("markets", "historical"),
        default="markets",
        help="markets=/markets/trades (default, live tape); historical=/historical/trades (archived)",
    )
    p.add_argument("--limit", type=int, default=200, help="Page size (1–1000, default 200)")
    p.add_argument("--min-ts", type=int, default=None, help="Optional Unix seconds filter (API min_ts)")
    p.add_argument("--max-ts", type=int, default=None, help="Optional Unix seconds filter (API max_ts)")
    p.add_argument("--dry-run", action="store_true", help="Fetch only; print JSON sample, do not write DB")
    args = p.parse_args()

    kid, kpath = load_kalshi_credentials()
    if not kid or not kpath.exists():
        print("error: missing Kalshi API credentials (prod .env + kalshi.pem)", file=sys.stderr)
        return 1

    api_path = ENDPOINT_PATHS[args.endpoint]
    trades, cursors = fetch_all_pages(
        args.ticker.strip(),
        api_path=api_path,
        limit=args.limit,
        min_ts=args.min_ts,
        max_ts=args.max_ts,
        key_id=str(kid),
        key_path=str(kpath.resolve()),
    )
    print(f"endpoint: {BASE_URL}{api_path}")
    print(f"fetched {len(trades)} trade row(s); pages with next cursor: {len(cursors)}")
    if trades:
        print("sample (first record):")
        print(json.dumps(trades[0], indent=2, default=str))
    else:
        print("(no trades returned — empty market, before historical cutoff, or filters exclude all rows)")
        print("tip: try another ticker with known volume; API docs: min_ts/max_ts in Unix seconds.")

    if args.dry_run:
        return 0

    ins, sk = upsert_rows(trades)
    print(f"db: inserted {ins} new row(s); duplicate or skipped {sk}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
