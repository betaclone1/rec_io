#!/usr/bin/env python3
"""Measure orderbook latency stages (venue ts → hot Redis → fanout → WS)."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

import redis

try:
    import websockets
except ImportError:
    websockets = None  # type: ignore

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from backend.core.trade_monitor_orderbook_keys import trade_monitor_orderbook_redis_key
from backend.core.trade_monitor_orderbook_watch import get_trade_monitor_orderbook_watch


def _pct(sorted_vals: list[int], p: float) -> Optional[int]:
    n = len(sorted_vals)
    if not n:
        return None
    return sorted_vals[min(n - 1, max(0, int(n * p)))]


def _summarize(name: str, samples: list[int]) -> None:
    if not samples:
        print(f"  {name}: no samples")
        return
    s = sorted(samples)
    print(
        f"  {name}: n={len(s)} min={s[0]}ms p50={_pct(s, 0.5)}ms "
        f"p90={_pct(s, 0.9)}ms p95={_pct(s, 0.95)}ms max={s[-1]}ms"
    )


def _summarize_delta(name: str, samples: list[int]) -> None:
    if not samples:
        print(f"  {name}: no samples")
        return
    s = sorted(samples)
    print(f"  {name}: n={len(s)} p50={_pct(s, 0.5)}ms p90={_pct(s, 0.9)}ms")


def _event_ts(ob_or_hint: dict) -> Optional[int]:
    for key in ("venue_ts_ms", "ts_ms"):
        raw = ob_or_hint.get(key)
        if raw is None:
            continue
        try:
            return int(raw)
        except (TypeError, ValueError):
            continue
    return None


def redis_worker(
    r: redis.Redis,
    live_state_ch: str,
    db_ch: str,
    watch_mt: str,
    stop_at: float,
    hot_samples: list[int],
    hot_apply_samples: list[int],
    venue_send_samples: list[int],
    hint_inline_samples: list[int],
    fanout_samples: list[int],
    by_seq: dict,
) -> None:
    pubsub = r.pubsub(ignore_subscribe_messages=True)
    pubsub.subscribe(live_state_ch, db_ch)
    while time.time() < stop_at:
        msg = pubsub.get_message(timeout=0.25)
        if not msg or msg.get("type") != "message":
            continue
        channel = msg.get("channel")
        raw = msg.get("data")
        if not raw:
            continue
        now_ms = int(time.time() * 1000)
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue

        if channel == live_state_ch and data.get("kind") == "orderbook":
            mt = str(data.get("market_ticker") or "").strip()
            if watch_mt and mt != watch_mt:
                continue
            inline = data.get("yes") is not None and data.get("no") is not None
            if inline:
                ts_i = _event_ts(data)
                if ts_i is None:
                    continue
                lat = now_ms - ts_i
                hot_samples.append(lat)
                hint_inline_samples.append(lat)
                rw = data.get("redis_written_ms")
                apply_ms = data.get("t_apply_ms")
                if rw is not None and apply_ms is not None:
                    try:
                        hot_apply_samples.append(int(rw) - int(apply_ms))
                    except (TypeError, ValueError):
                        pass
                venue = data.get("venue_ts_ms")
                send = data.get("sending_ts_ms")
                if venue is not None and send is not None:
                    try:
                        venue_send_samples.append(int(send) - int(venue))
                    except (TypeError, ValueError):
                        pass
                seq = data.get("book_seq")
                rec = by_seq.setdefault(seq, {})
                rec["hot"] = lat
                rec["inline"] = True
                continue

            blob = r.get(trade_monitor_orderbook_redis_key(mt))
            if not blob:
                continue
            ob = json.loads(blob)
            ts_i = _event_ts(ob)
            if ts_i is None:
                continue
            lat = now_ms - ts_i
            hot_samples.append(lat)
            rw = ob.get("redis_written_ms")
            apply_ms = ob.get("t_apply_ms")
            if rw is not None and apply_ms is not None:
                try:
                    hot_apply_samples.append(int(rw) - int(apply_ms))
                except (TypeError, ValueError):
                    pass
            elif rw is not None:
                try:
                    hot_apply_samples.append(int(rw) - ts_i)
                except (TypeError, ValueError):
                    pass
            venue = ob.get("venue_ts_ms")
            send = ob.get("sending_ts_ms")
            if venue is not None and send is not None:
                try:
                    venue_send_samples.append(int(send) - int(venue))
                except (TypeError, ValueError):
                    pass
            seq = ob.get("seq")
            rec = by_seq.setdefault(seq, {})
            rec["hot"] = lat
            rec["inline"] = False

        elif channel == db_ch and data.get("type") == "live_orderbook":
            mt = str(data.get("market_ticker") or "").strip()
            if watch_mt and mt != watch_mt:
                continue
            ts_i = _event_ts(data)
            if ts_i is None:
                continue
            lat = now_ms - ts_i
            fanout_samples.append(lat)
            seq = data.get("book_seq")
            by_seq.setdefault(seq, {})["fanout"] = lat


async def ws_worker(
    url: str,
    watch_mt: str,
    stop_at: float,
    ws_samples: list[int],
    by_seq: dict,
) -> None:
    if websockets is None:
        print("websockets package not installed; skipping WS stage", file=sys.stderr)
        return
    async with websockets.connect(url, ping_interval=20, open_timeout=15) as ws:
        while time.time() < stop_at:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=1.0)
            except asyncio.TimeoutError:
                continue
            recv_ms = int(time.time() * 1000)
            data = json.loads(raw)
            if data.get("type") != "live_orderbook":
                continue
            mt = str(data.get("market_ticker") or "").strip()
            if watch_mt and mt != watch_mt:
                continue
            ts_i = _event_ts(data)
            if ts_i is None:
                continue
            lat = recv_ms - ts_i
            ws_samples.append(lat)
            seq = data.get("book_seq")
            by_seq.setdefault(seq, {})["ws"] = lat


async def run_probe(duration_s: int, ws_url: str, watch_mt: str) -> int:
    host = os.getenv("REC_REDIS_HOST", "localhost")
    port = int(os.getenv("REC_REDIS_PORT", "6379"))
    password = os.getenv("REC_REDIS_PASSWORD") or None
    live_state_ch = os.getenv("LIVE_STATE_UPDATED_CHANNEL", "rec_io:live_state:updated")
    db_ch = os.getenv("REDIS_CHANNEL_DB_CHANGES", "rec_io:db_changes")

    r = redis.Redis(host=host, port=port, password=password, decode_responses=True)
    stop_at = time.time() + duration_s

    hot_samples: list[int] = []
    hot_apply_samples: list[int] = []
    venue_send_samples: list[int] = []
    hint_inline_samples: list[int] = []
    fanout_samples: list[int] = []
    ws_samples: list[int] = []
    by_seq: dict = {}

    print(f"Watched ticker: {watch_mt or '(all orderbook hints)'}")
    print(f"Duration: {duration_s}s\n")

    loop = asyncio.get_running_loop()
    with ThreadPoolExecutor(max_workers=1) as pool:
        redis_fut = loop.run_in_executor(
            pool,
            redis_worker,
            r,
            live_state_ch,
            db_ch,
            watch_mt,
            stop_at,
            hot_samples,
            hot_apply_samples,
            venue_send_samples,
            hint_inline_samples,
            fanout_samples,
            by_seq,
        )
        try:
            await ws_worker(ws_url, watch_mt, stop_at, ws_samples, by_seq)
        except OSError as e:
            # Local probe often runs without main_app WS (:3000). Redis stages still count.
            print(f"WS stage skipped ({e})", file=sys.stderr)
            # Keep redis_worker sampling until stop_at.
            remaining = max(0.0, stop_at - time.time())
            if remaining > 0:
                await asyncio.sleep(remaining)
        finally:
            await redis_fut

    print("=== ms from venue/event ts_ms ===")
    _summarize("1_ob_hot (hint±GET)", hot_samples)
    _summarize("1a_ob_hot_inline_hint", hint_inline_samples)
    _summarize_delta("1b_apply_to_hot (redis_written - t_apply)", hot_apply_samples)
    _summarize_delta("1c_venue_to_send (sending_ts - venue_ts)", venue_send_samples)
    _summarize("2_fanout (db_changes live_orderbook)", fanout_samples)
    _summarize("3_ws (/ws/live_market)", ws_samples)

    both = [v for v in by_seq.values() if "hot" in v and "fanout" in v]
    if both:
        d = sorted(v["fanout"] - v["hot"] for v in both)
        print(f"  fanout minus hot (paired seq): p50={_pct(d, 0.5)}ms p90={_pct(d, 0.9)}ms")
    both3 = [v for v in by_seq.values() if "hot" in v and "fanout" in v and "ws" in v]
    if both3:
        d2 = sorted(v["ws"] - v["fanout"] for v in both3)
        print(f"  ws minus fanout (paired seq): p50={_pct(d2, 0.5)}ms p90={_pct(d2, 0.9)}ms")

    return 0 if hot_samples else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Orderbook latency probe")
    parser.add_argument("--duration", type=int, default=40, help="Seconds to sample")
    parser.add_argument(
        "--ticker",
        default="",
        help="Filter to market_ticker (default: trade monitor watch)",
    )
    parser.add_argument(
        "--ws-url",
        default="ws://127.0.0.1:3000/ws/live_market?symbol=BTC&market=15m",
        help="WebSocket URL for stage 3",
    )
    args = parser.parse_args()
    watch_mt = str(args.ticker or "").strip() or (get_trade_monitor_orderbook_watch() or "")
    return asyncio.run(run_probe(args.duration, args.ws_url, watch_mt))


if __name__ == "__main__":
    raise SystemExit(main())
