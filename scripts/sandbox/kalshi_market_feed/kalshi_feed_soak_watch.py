#!/usr/bin/env python3
"""
Log feed-level disturbances from Redis pub/sub (no poll interval).

Run alongside ws master + monitor:
  python scripts/sandbox/kalshi_market_feed/kalshi_feed_soak_watch.py

Env:
  SANDBOX_KALSHI_REDIS_PREFIX  default sandbox:kalshi:
  SANDBOX_KALSHI_SOAK_LOG      default <this_dir>/kalshi_feed_soak.jsonl
"""

from __future__ import annotations

import json
import os
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

SANDBOX_DIR = Path(__file__).resolve().parent
REDIS_PREFIX = os.getenv("SANDBOX_KALSHI_REDIS_PREFIX", "sandbox:kalshi:").strip()
SOAK_LOG = Path(
    os.getenv("SANDBOX_KALSHI_SOAK_LOG", str(SANDBOX_DIR / "kalshi_feed_soak.jsonl"))
)
HEALTH_URL = os.getenv("SANDBOX_KALSHI_SOAK_URL", "http://127.0.0.1:8791/api/health").strip()


def _ts() -> str:
    return datetime.now(timezone.utc).isoformat()


def _push_channel() -> str:
    return f"{REDIS_PREFIX}push:v1"


def _redis():
    import redis

    url = os.getenv("REDIS_URL", "").strip()
    if url:
        return redis.from_url(url, decode_responses=True)
    return redis.Redis(
        host=os.getenv("REDIS_HOST", "localhost"),
        port=int(os.getenv("REDIS_PORT", "6379")),
        password=os.getenv("REDIS_PASSWORD") or None,
        decode_responses=True,
    )


def _write(rec: dict) -> None:
    SOAK_LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(SOAK_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, default=str) + "\n")
    print(json.dumps(rec, default=str), flush=True)


def _health_snapshot() -> dict:
    try:
        with urllib.request.urlopen(HEALTH_URL, timeout=10) as resp:
            data = json.loads(resp.read().decode())
    except Exception as e:
        return {"overall": "unreachable", "fetch_error": str(e)}
    health = data.get("health") or {}
    meta = data.get("meta") or {}
    counts = health.get("counts") or {}
    return {
        "overall": health.get("overall"),
        "feed_issues": tuple(health.get("feed_issues") or []),
        "ws_connected": bool(meta.get("ws_connected")),
        "resync": bool(health.get("resync_in_progress")),
        "ok": int(counts.get("ok") or 0),
        "warn": int(counts.get("warn") or 0),
        "dead": int(counts.get("dead") or 0),
        "subs": len(meta.get("orderbook_subscribed") or []),
    }


def _is_disturbance(snap: dict) -> bool:
    if snap.get("overall") in ("dead", "unreachable"):
        return True
    if snap.get("dead", 0) > 0:
        return True
    issues = snap.get("feed_issues") or ()
    if "ws_down" in issues or "no_meta" in issues:
        return True
    if snap.get("warn", 0) > 8 and not snap.get("resync"):
        return True
    return False


def main() -> None:
    last: dict | None = None
    last_check = 0.0
    _write({"type": "soak_start", "ts": _ts(), "channel": _push_channel()})
    r = _redis()
    pubsub = r.pubsub(ignore_subscribe_messages=True)
    pubsub.subscribe(_push_channel())
    for msg in pubsub.listen():
        if msg.get("type") != "message":
            continue
        now = time.monotonic()
        if now - last_check < 2.0:
            continue
        last_check = now
        snap = _health_snapshot()
        if last is not None and snap != last and _is_disturbance(snap):
            _write({"type": "soak_disturbance", "ts": _ts(), "prev": last, "cur": snap})
        last = snap


if __name__ == "__main__":
    main()
