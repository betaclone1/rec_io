#!/usr/bin/env python3
"""
Long-running OB hot-path gap monitor (prod ops).

Subscribes to Redis ``rec_io:live_state:updated`` (kind=orderbook) and records:
  - global interarrival gaps
  - per-ticker gaps for live BTC/ETH/SOL 15m + tracked hourly
  - Redis book age at each hint for focus tickers
  - minute + hourly rollups to a log file

Does not mutate trading state. Safe to leave running for hours.

Usage (on prod host):
  cd /opt/rec_io_server && nohup venv/bin/python scripts/diagnostics/monitor_ob_hotpath_gaps.py \\
    --hours 12 --log logs/ob_hotpath_gaps.log > logs/ob_hotpath_gaps.nohup.out 2>&1 &
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

# Allow running from repo root without PYTHONPATH dance when cwd is project root.
_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _pct(sorted_vals: List[float], p: float) -> Optional[float]:
    if not sorted_vals:
        return None
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    idx = int(round((p / 100.0) * (len(sorted_vals) - 1)))
    idx = max(0, min(len(sorted_vals) - 1, idx))
    return sorted_vals[idx]


@dataclass
class GapBucket:
    n: int = 0
    gaps: List[float] = field(default_factory=list)
    ages: List[float] = field(default_factory=list)
    ge_0_5: int = 0
    ge_1: int = 0
    ge_2: int = 0
    ge_5: int = 0
    ge_10: int = 0
    max_gap: float = 0.0
    max_age: float = 0.0
    last_mono: Optional[float] = None
    last_wall: Optional[float] = None

    def observe_gap(self, gap: float) -> None:
        self.n += 1
        self.gaps.append(gap)
        # Cap memory: keep last 50k gaps for percentile; counters are exact.
        if len(self.gaps) > 50000:
            self.gaps = self.gaps[-25000:]
        self.max_gap = max(self.max_gap, gap)
        if gap >= 0.5:
            self.ge_0_5 += 1
        if gap >= 1.0:
            self.ge_1 += 1
        if gap >= 2.0:
            self.ge_2 += 1
        if gap >= 5.0:
            self.ge_5 += 1
        if gap >= 10.0:
            self.ge_10 += 1

    def observe_age(self, age: float) -> None:
        self.ages.append(age)
        if len(self.ages) > 50000:
            self.ages = self.ages[-25000:]
        self.max_age = max(self.max_age, age)

    def summary(self) -> Dict[str, Any]:
        sg = sorted(self.gaps) if self.gaps else []
        sa = sorted(self.ages) if self.ages else []
        return {
            "events": self.n,
            "gap_p50": _pct(sg, 50),
            "gap_p95": _pct(sg, 95),
            "gap_p99": _pct(sg, 99),
            "gap_max": self.max_gap if self.n else None,
            "gaps_ge_0_5": self.ge_0_5,
            "gaps_ge_1": self.ge_1,
            "gaps_ge_2": self.ge_2,
            "gaps_ge_5": self.ge_5,
            "gaps_ge_10": self.ge_10,
            "age_p50": _pct(sa, 50),
            "age_p99": _pct(sa, 99),
            "age_max": self.max_age if self.ages else None,
        }


def _live_15m_tickers(r) -> List[str]:
    out: List[str] = []
    for sym in ("BTC", "ETH", "SOL"):
        key = f"rec_io:live_state:v1:market:kalshi:15m:{sym}"
        raw = r.get(key)
        if not raw:
            continue
        try:
            env = json.loads(raw)
            markets = (env.get("data") or {}).get("markets") or []
            for m in markets:
                t = m.get("ticker") or m.get("market_ticker")
                if t:
                    out.append(str(t))
        except Exception:
            continue
    return out


def _log(fp, obj: Dict[str, Any]) -> None:
    line = json.dumps(obj, separators=(",", ":"), default=str)
    fp.write(line + "\n")
    fp.flush()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--hours", type=float, default=12.0)
    ap.add_argument("--log", default="logs/ob_hotpath_gaps.log")
    ap.add_argument("--minute-summary-sec", type=float, default=60.0)
    ap.add_argument("--hour-summary-sec", type=float, default=3600.0)
    ap.add_argument(
        "--alert-gap-sec",
        type=float,
        default=2.0,
        help="Emit immediate ALERT line when global or focus-ticker gap exceeds this",
    )
    ap.add_argument(
        "--focus-alert-gap-sec",
        type=float,
        default=1.0,
        help="Alert threshold for BTC15m specifically",
    )
    args = ap.parse_args()

    import redis
    from backend.core import live_state_cache
    from backend.core.trade_monitor_orderbook_keys import trade_monitor_orderbook_redis_key

    log_path = args.log
    if not os.path.isabs(log_path):
        log_path = os.path.join(_ROOT, log_path)
    os.makedirs(os.path.dirname(log_path) or ".", exist_ok=True)

    stop = {"flag": False}

    def _sig(_signum, _frame):
        stop["flag"] = True

    signal.signal(signal.SIGTERM, _sig)
    signal.signal(signal.SIGINT, _sig)

    r = redis.Redis(host="127.0.0.1", port=6379, decode_responses=True)
    channel = live_state_cache.UPDATED_CHANNEL
    ps = r.pubsub(ignore_subscribe_messages=True)
    ps.subscribe(channel)

    global_b = GapBucket()
    by_mt: Dict[str, GapBucket] = defaultdict(GapBucket)
    focus_set = set(_live_15m_tickers(r))
    last_focus_refresh = time.monotonic()

    started = time.time()
    end_at = started + max(60.0, args.hours * 3600.0)
    last_min = started
    last_hour = started
    minute_b = GapBucket()
    hour_b = GapBucket()
    minute_focus: Dict[str, GapBucket] = defaultdict(GapBucket)
    alerts = 0

    with open(log_path, "a", encoding="utf-8") as fp:
        _log(
            fp,
            {
                "type": "monitor_start",
                "ts": _now_iso(),
                "hours": args.hours,
                "channel": channel,
                "focus_15m": sorted(focus_set),
                "pid": os.getpid(),
            },
        )
        print(
            f"[ob_gap_monitor] started pid={os.getpid()} log={log_path} hours={args.hours}",
            flush=True,
        )

        while not stop["flag"] and time.time() < end_at:
            now_wall = time.time()
            now_mono = time.monotonic()

            if now_mono - last_focus_refresh >= 30.0:
                focus_set = set(_live_15m_tickers(r))
                last_focus_refresh = now_mono

            msg = ps.get_message(timeout=0.5)
            if msg and msg.get("type") == "message":
                try:
                    body = json.loads(msg["data"])
                except Exception:
                    body = None
                if isinstance(body, dict) and body.get("kind") == "orderbook":
                    mt = str(body.get("market_ticker") or "")
                    # global
                    if global_b.last_mono is not None:
                        gap = now_mono - global_b.last_mono
                        global_b.observe_gap(gap)
                        minute_b.observe_gap(gap)
                        hour_b.observe_gap(gap)
                        if gap >= args.alert_gap_sec:
                            alerts += 1
                            _log(
                                fp,
                                {
                                    "type": "ALERT_GLOBAL_GAP",
                                    "ts": _now_iso(),
                                    "gap_sec": round(gap, 4),
                                    "market_ticker": mt,
                                },
                            )
                    global_b.last_mono = now_mono
                    global_b.last_wall = now_wall
                    global_b.n  # ensure dataclass used
                    # count events even before first gap
                    if global_b.last_mono is not None and global_b.n == 0 and len(global_b.gaps) == 0:
                        pass

                    # per ticker
                    b = by_mt[mt]
                    if b.last_mono is not None:
                        gap = now_mono - b.last_mono
                        b.observe_gap(gap)
                        if mt in focus_set:
                            minute_focus[mt].observe_gap(gap)
                            # BTC15m is the high-churn proof ticker (1s).
                            # ETH/SOL 15m are naturally quieter — only alert on
                            # true stalls (10s+), not normal 2–3s venue silence.
                            mt_u = mt.upper()
                            if mt_u.startswith("KXBTC15M"):
                                thresh = args.focus_alert_gap_sec
                            elif mt_u.startswith("KXETH15M") or mt_u.startswith("KXSOL15M"):
                                thresh = 10.0
                            else:
                                thresh = args.alert_gap_sec
                            if gap >= thresh:
                                alerts += 1
                                _log(
                                    fp,
                                    {
                                        "type": "ALERT_TICKER_GAP",
                                        "ts": _now_iso(),
                                        "market_ticker": mt,
                                        "gap_sec": round(gap, 4),
                                        "threshold": thresh,
                                    },
                                )
                    else:
                        # first event — count as event without gap
                        b.n += 0
                    b.last_mono = now_mono
                    b.last_wall = now_wall
                    # bump event count for first observation
                    if not b.gaps and b.n == 0:
                        b.n = 0  # gaps counted on subsequent

                    # book age for focus tickers
                    if mt in focus_set:
                        try:
                            raw = r.get(trade_monitor_orderbook_redis_key(mt))
                            if raw:
                                d = json.loads(raw)
                                ts_ms = d.get("ts_ms")
                                if ts_ms is not None:
                                    age = now_wall - (float(ts_ms) / 1000.0)
                                    b.observe_age(age)
                                    minute_focus[mt].observe_age(age)
                                    if age >= args.alert_gap_sec:
                                        alerts += 1
                                        _log(
                                            fp,
                                            {
                                                "type": "ALERT_BOOK_AGE",
                                                "ts": _now_iso(),
                                                "market_ticker": mt,
                                                "age_sec": round(age, 4),
                                            },
                                        )
                        except Exception:
                            pass

                    # Fix event counting: GapBucket.n increments on observe_gap only.
                    # Track raw hint counts separately via a side counter on first hit.
                    if not hasattr(b, "_hints"):
                        setattr(b, "_hints", 0)
                    setattr(b, "_hints", getattr(b, "_hints") + 1)

            # minute summary
            if now_wall - last_min >= args.minute_summary_sec:
                focus_sum = {
                    mt: minute_focus[mt].summary()
                    for mt in sorted(focus_set)
                    if mt in minute_focus
                }
                _log(
                    fp,
                    {
                        "type": "minute_summary",
                        "ts": _now_iso(),
                        "elapsed_sec": round(now_wall - started, 1),
                        "global": minute_b.summary(),
                        "focus_15m": focus_sum,
                        "alerts_total": alerts,
                        "focus_tickers": sorted(focus_set),
                    },
                )
                print(
                    f"[ob_gap_monitor] minute global={minute_b.summary()} alerts={alerts}",
                    flush=True,
                )
                minute_b = GapBucket()
                minute_focus = defaultdict(GapBucket)
                last_min = now_wall

            # hour summary
            if now_wall - last_hour >= args.hour_summary_sec:
                top_bad = []
                for mt, b in by_mt.items():
                    if b.ge_2 or b.ge_5:
                        top_bad.append(
                            {
                                "market_ticker": mt,
                                "gaps_ge_2": b.ge_2,
                                "gaps_ge_5": b.ge_5,
                                "gaps_ge_10": b.ge_10,
                                "gap_max": b.max_gap,
                                "hints": getattr(b, "_hints", b.n),
                            }
                        )
                top_bad.sort(key=lambda x: (x["gaps_ge_10"], x["gaps_ge_5"], x["gaps_ge_2"]), reverse=True)
                _log(
                    fp,
                    {
                        "type": "hour_summary",
                        "ts": _now_iso(),
                        "elapsed_sec": round(now_wall - started, 1),
                        "global": hour_b.summary(),
                        "global_lifetime": global_b.summary(),
                        "top_bad_tickers": top_bad[:20],
                        "alerts_total": alerts,
                    },
                )
                print(
                    f"[ob_gap_monitor] HOUR global={hour_b.summary()} lifetime={global_b.summary()} alerts={alerts}",
                    flush=True,
                )
                hour_b = GapBucket()
                last_hour = now_wall

        # final
        _log(
            fp,
            {
                "type": "monitor_stop",
                "ts": _now_iso(),
                "elapsed_sec": round(time.time() - started, 1),
                "global_lifetime": global_b.summary(),
                "alerts_total": alerts,
                "reason": "signal" if stop["flag"] else "duration",
            },
        )
        print(f"[ob_gap_monitor] stopped alerts={alerts}", flush=True)

    try:
        ps.close()
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
