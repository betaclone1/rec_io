#!/usr/bin/env python3
"""Continuous live OB hot-path gap monitor (Redis pubsub + book age).

Run on prod (background)::

    nohup venv/bin/python scripts/diagnostics/ob_hotpath_gap_monitor.py \\
      >> logs/ob_hotpath_gap_monitor.nohup.out 2>&1 &

Writes:
  logs/ob_hotpath_gap_monitor.log   — minute summaries + stall ALERTs
  logs/ob_hotpath_gap_events.jsonl  — one JSON line per notable event

Primary stall signals (ALERT):
  - global orderbook pubsub gap >= OB_GAP_GLOBAL_ALERT_SEC (default 1.0)
  - KXBTC15M per-ticker gap >= OB_GAP_BTC15M_ALERT_SEC (default 1.0)
  - KXBTC15M Redis book age >= OB_GAP_BOOK_AGE_ALERT_SEC (default 2.0)

Quieter tickers (ETH/SOL/hourly) are summarized only; natural 1–3s silence
is not treated as an ingest stall.
"""
from __future__ import annotations

import json
import os
import signal
import statistics
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

import redis

from backend.core import live_state_cache
from backend.core.trade_monitor_orderbook_keys import trade_monitor_orderbook_redis_key

LOG_DIR = ROOT / "logs"
LOG_PATH = LOG_DIR / "ob_hotpath_gap_monitor.log"
EVENT_PATH = LOG_DIR / "ob_hotpath_gap_events.jsonl"

SUMMARY_PREFIXES = tuple(
    p.strip().upper()
    for p in os.getenv(
        "OB_GAP_SUMMARY_PREFIXES",
        "KXBTC15M,KXETH15M,KXSOL15M,KXBTCD,KXETHD,KXSOLD",
    ).split(",")
    if p.strip()
)
GLOBAL_ALERT_SEC = float(os.getenv("OB_GAP_GLOBAL_ALERT_SEC", "1.0"))
BTC15M_ALERT_SEC = float(os.getenv("OB_GAP_BTC15M_ALERT_SEC", "1.0"))
BOOK_AGE_ALERT_SEC = float(os.getenv("OB_GAP_BOOK_AGE_ALERT_SEC", "2.0"))
SUMMARY_SEC = float(os.getenv("OB_GAP_SUMMARY_SEC", "60"))

_stop = False


def _log(msg: str) -> None:
    line = f"{datetime.now(timezone.utc).isoformat()} {msg}"
    print(line, flush=True)
    with LOG_PATH.open("a") as f:
        f.write(line + "\n")


def _event(obj: dict) -> None:
    payload = dict(obj)
    payload["ts"] = datetime.now(timezone.utc).isoformat()
    with EVENT_PATH.open("a") as f:
        f.write(json.dumps(payload, default=str) + "\n")


def _handle(sig, frame) -> None:  # noqa: ARG001
    global _stop
    _stop = True


def _is_summary(mt: str) -> bool:
    u = (mt or "").upper()
    return any(u.startswith(p) for p in SUMMARY_PREFIXES)


def _stat(xs: list[float]) -> str:
    if not xs:
        return "n=0"
    ordered = sorted(xs)
    p95 = ordered[int(0.95 * (len(ordered) - 1))]
    return (
        f"n={len(xs)} min={min(xs):.4f} p50={statistics.median(xs):.4f} "
        f"p95={p95:.4f} max={max(xs):.4f}"
    )


def main() -> int:
    signal.signal(signal.SIGTERM, _handle)
    signal.signal(signal.SIGINT, _handle)
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    r = redis.Redis(host="127.0.0.1", port=6379, decode_responses=True)
    ch = live_state_cache.UPDATED_CHANNEL
    ps = r.pubsub(ignore_subscribe_messages=True)
    ps.subscribe(ch)
    _log(
        f"START channel={ch} summary_sec={SUMMARY_SEC} "
        f"global_alert={GLOBAL_ALERT_SEC}s btc15m_alert={BTC15M_ALERT_SEC}s "
        f"book_age_alert={BOOK_AGE_ALERT_SEC}s summary_prefixes={SUMMARY_PREFIXES}"
    )

    last_global: float | None = None
    last_by_mt: dict[str, float] = {}
    last_btc15m: dict[str, float] = {}
    win_start = time.time()
    n_hints = 0
    n_summary = 0
    n_btc15m = 0
    gaps_global: list[float] = []
    gaps_by_mt: dict[str, list[float]] = defaultdict(list)
    gaps_btc15m: list[float] = []
    alerts: dict[str, int] = defaultdict(int)
    max_global = 0.0
    max_btc15m = 0.0
    max_btc15m_mt = ""
    book_ages: list[float] = []
    live_btc15m: str | None = None

    while not _stop:
        msg = ps.get_message(timeout=0.5)
        now = time.time()
        if msg and msg.get("type") == "message":
            try:
                body = json.loads(msg["data"])
            except Exception:
                body = None
            if body and body.get("kind") == "orderbook":
                mt = str(body.get("market_ticker") or "")
                n_hints += 1

                if last_global is not None:
                    g = now - last_global
                    gaps_global.append(g)
                    if g > max_global:
                        max_global = g
                    if g >= GLOBAL_ALERT_SEC:
                        alerts[f"global>={GLOBAL_ALERT_SEC}"] += 1
                        _event({"type": "global_gap", "gap_sec": round(g, 4), "mt": mt})
                        _log(f"ALERT global_gap={g:.3f}s after mt={mt}")
                    if g >= 2.0:
                        alerts["global>=2"] += 1
                    if g >= 5.0:
                        alerts["global>=5"] += 1
                last_global = now

                if _is_summary(mt):
                    n_summary += 1
                    prev = last_by_mt.get(mt)
                    if prev is not None:
                        gaps_by_mt[mt].append(now - prev)
                    last_by_mt[mt] = now

                if mt.upper().startswith("KXBTC15M"):
                    n_btc15m += 1
                    live_btc15m = mt
                    btc_prev = last_btc15m.get(mt)
                    if btc_prev is not None:
                        g = now - btc_prev
                        gaps_btc15m.append(g)
                        if g > max_btc15m:
                            max_btc15m = g
                            max_btc15m_mt = mt
                        if g >= BTC15M_ALERT_SEC:
                            alerts[f"btc15m>={BTC15M_ALERT_SEC}"] += 1
                            _event(
                                {
                                    "type": "btc15m_gap",
                                    "gap_sec": round(g, 4),
                                    "mt": mt,
                                }
                            )
                            _log(f"ALERT btc15m_gap={g:.3f}s mt={mt}")
                        if g >= 2.0:
                            alerts["btc15m>=2"] += 1
                        if g >= 5.0:
                            alerts["btc15m>=5"] += 1
                    last_btc15m[mt] = now

                    try:
                        raw = r.get(trade_monitor_orderbook_redis_key(mt))
                        if raw:
                            d = json.loads(raw)
                            ts_ms = d.get("ts_ms")
                            if ts_ms is not None:
                                age = now - float(ts_ms) / 1000.0
                                book_ages.append(age)
                                if age >= BOOK_AGE_ALERT_SEC:
                                    alerts[f"btc15m_book_age>={BOOK_AGE_ALERT_SEC}"] += 1
                                    _event(
                                        {
                                            "type": "book_age",
                                            "age_sec": round(age, 4),
                                            "mt": mt,
                                            "seq": d.get("seq"),
                                        }
                                    )
                                    _log(
                                        f"ALERT book_age={age:.3f}s mt={mt} seq={d.get('seq')}"
                                    )
                    except Exception as e:
                        _log(f"book_age_err {e}")

        if now - win_start >= SUMMARY_SEC:
            top = sorted(
                gaps_by_mt.items(), key=lambda kv: len(kv[1]), reverse=True
            )[:6]
            top_s = " | ".join(f"{mt}:{_stat(gs)}" for mt, gs in top)
            _log(
                f"SUMMARY hints={n_hints} summary_hints={n_summary} btc15m_hints={n_btc15m} "
                f"global_gaps[{_stat(gaps_global)}] max_global={max_global:.4f} "
                f"btc15m_gaps[{_stat(gaps_btc15m)}] max_btc15m={max_btc15m:.4f}@{max_btc15m_mt} "
                f"alerts={dict(alerts)} btc15m_book_age[{_stat(book_ages)}] "
                f"live_btc15m={live_btc15m} top=[{top_s}]"
            )
            win_start = now
            n_hints = 0
            n_summary = 0
            n_btc15m = 0
            gaps_global.clear()
            gaps_by_mt.clear()
            gaps_btc15m.clear()
            alerts.clear()
            max_global = 0.0
            max_btc15m = 0.0
            max_btc15m_mt = ""
            book_ages.clear()

    ps.close()
    _log("STOP")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
