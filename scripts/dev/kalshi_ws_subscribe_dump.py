#!/usr/bin/env python3
"""Open one Kalshi WS v2 connection, subscribe to ticker + market_lifecycle_v2, print frames.

  venv/bin/python scripts/dev/kalshi_ws_subscribe_dump.py
  venv/bin/python scripts/dev/kalshi_ws_subscribe_dump.py --tickers KXBTCD-... ,KXETHD-...
  venv/bin/python scripts/dev/kalshi_ws_subscribe_dump.py --max 20 --seconds 60
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

# repo root on path
_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import websockets

from backend.core.kalshi_ws_auth import kalshi_ws_connect_headers

WS_URL = "wss://external-api-ws.kalshi.com/trade-api/ws/v2"


async def drain_until_subscribed(ws, channel: str, timeout: float) -> None:
    import time

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        rem = deadline - time.monotonic()
        raw = await asyncio.wait_for(ws.recv(), timeout=max(0.25, min(30.0, rem)))
        data = json.loads(raw)
        if data.get("type") == "subscribed" and (data.get("msg") or {}).get("channel") == channel:
            print(json.dumps(data, indent=2), flush=True)
            return
        print(json.dumps(data, indent=2), flush=True)


async def run(*, tickers: list[str], max_msgs: int | None, seconds: float | None) -> None:
    import time

    headers = kalshi_ws_connect_headers()
    started = time.monotonic()
    n = 0
    async with websockets.connect(
        WS_URL,
        additional_headers=headers,
        ping_interval=25,
        ping_timeout=70,
        close_timeout=10,
        max_size=2**22,
    ) as ws:
        await ws.send(
            json.dumps(
                {
                    "id": 1,
                    "cmd": "subscribe",
                    "params": {"channels": ["ticker"], "market_tickers": tickers},
                }
            )
        )
        await drain_until_subscribed(ws, "ticker", 30.0)

        await ws.send(
            json.dumps(
                {
                    "id": 2,
                    "cmd": "subscribe",
                    "params": {"channels": ["market_lifecycle_v2"]},
                }
            )
        )
        await drain_until_subscribed(ws, "market_lifecycle_v2", 30.0)

        while True:
            if max_msgs is not None and n >= max_msgs:
                break
            if seconds is not None and (time.monotonic() - started) >= seconds:
                break
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=75.0)
            except asyncio.TimeoutError:
                continue
            print(raw, flush=True)
            n += 1


def _default_tickers_from_db() -> list[str]:
    try:
        import psycopg2

        from backend.market_watchdog import DB_CONFIG

        conn = psycopg2.connect(**DB_CONFIG)
        cur = conn.cursor()
        out: list[str] = []
        cur.execute(
            "SELECT market_ticker FROM live_data.market_kalshi_hourly "
            "WHERE market_ticker LIKE 'KXBTC%' ORDER BY updated_at DESC NULLS LAST LIMIT 1"
        )
        r = cur.fetchone()
        if r:
            out.append(r[0])
        cur.execute(
            "SELECT market_ticker FROM live_data.market_kalshi_hourly "
            "WHERE market_ticker LIKE 'KXETH%' ORDER BY updated_at DESC NULLS LAST LIMIT 1"
        )
        r = cur.fetchone()
        if r:
            out.append(r[0])
        conn.close()
        return out
    except Exception:
        return []


def main() -> None:
    p = argparse.ArgumentParser(description="Kalshi WS: subscribe ticker + market_lifecycle_v2, print frames")
    p.add_argument(
        "--tickers",
        type=str,
        default="",
        help="Comma-separated market_tickers (default: two hourly BTC/ETH rows from DB if available)",
    )
    p.add_argument("--max", type=int, default=None, help="Stop after N messages (after subscribe acks)")
    p.add_argument("--seconds", type=float, default=None, help="Stop after this many seconds")
    args = p.parse_args()

    if args.tickers.strip():
        tickers = [t.strip() for t in args.tickers.split(",") if t.strip()]
    else:
        tickers = _default_tickers_from_db()
    if not tickers:
        print(
            "No --tickers and DB default failed; pass e.g. --tickers KXBTCD-...,KXETHD-...",
            file=sys.stderr,
        )
        sys.exit(1)

    asyncio.run(run(tickers=tickers, max_msgs=args.max, seconds=args.seconds))


if __name__ == "__main__":
    main()
