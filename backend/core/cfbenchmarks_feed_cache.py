"""
Redis cache for Kalshi cfbenchmarks_value experiment (multi-index → BTC/ETH/SOL/XRP).

Experiment keys only unless cfbenchmarks_publish uses live_state mode (see docs/CFB_PRICE_WATCHDOG_CUTOVER.md).
"""

from __future__ import annotations

import json
import os
import time
from typing import Any, Dict, List, Optional

KEY_PREFIX = os.getenv("CFBENCHMARKS_REDIS_PREFIX", "rec_io:experiment:cfbenchmarks:v1")
UPDATED_CHANNEL = os.getenv(
    "CFBENCHMARKS_UPDATED_CHANNEL", "rec_io:experiment:cfbenchmarks:updated"
)
RECENT_MAX = int(os.getenv("CFBENCHMARKS_RECENT_MAX", "200"))
TTL_SEC = int(os.getenv("CFBENCHMARKS_REDIS_TTL_SEC", "7200"))

# CF Benchmarks index_id → trading symbol label for UI / envelopes
INDEX_TO_SYMBOL: Dict[str, str] = {
    "BRTI": "BTC",
    "ETHUSD_RTI": "ETH",
    "SOLUSD_RTI": "SOL",
    "XRPUSD_RTI": "XRP",
}

DEFAULT_INDEX_IDS: List[str] = ["BRTI", "ETHUSD_RTI", "SOLUSD_RTI", "XRPUSD_RTI"]
DEFAULT_INDEX_IDS_CSV = ",".join(DEFAULT_INDEX_IDS)

# Shorthand → Kalshi index_id (from indexlist / common nicknames)
INDEX_ALIASES: Dict[str, str] = {
    "ERTI": "ETHUSD_RTI",
    "SSOL": "SOLUSD_RTI",
    "SOL": "SOLUSD_RTI",
    "XRP": "XRPUSD_RTI",
}


def resolve_index_id(index_id: str) -> str:
    iid = (index_id or "").strip().upper()
    return INDEX_ALIASES.get(iid, iid)


def symbol_for_index(index_id: str) -> str:
    iid = resolve_index_id(index_id)
    return INDEX_TO_SYMBOL.get(iid, iid)


def parse_index_ids(raw: Optional[str] = None) -> List[str]:
    """Comma-separated index IDs; default all four majors (aliases accepted)."""
    text = (
        raw if raw is not None else os.getenv("CFBENCHMARKS_INDEX_IDS", DEFAULT_INDEX_IDS_CSV)
    ).strip()
    if text.upper() in ("ALL", "*"):
        return list(INDEX_TO_SYMBOL.keys())
    out: List[str] = []
    for part in text.split(","):
        iid = resolve_index_id(part)
        if iid and iid not in out:
            out.append(iid)
    return out or ["BRTI"]


def _redis():
    from backend.core.live_state_cache import redis_client_optional

    return redis_client_optional()


def index_key(index_id: str) -> str:
    return f"{KEY_PREFIX}:{(index_id or 'BRTI').strip().upper()}"


def recent_key(index_id: str) -> str:
    return f"{index_key(index_id)}:recent"


def meta_key(index_id: str) -> str:
    return f"{index_key(index_id)}:meta"


def publish_tick(index_id: str, envelope: Dict[str, Any]) -> bool:
    """Store latest + recent ring buffer; pub/sub for main_app WS fanout."""
    r = _redis()
    if not r:
        return False
    iid = (index_id or "BRTI").strip().upper()
    body = json.dumps(envelope, default=str)
    try:
        pipe = r.pipeline()
        pipe.setex(index_key(iid), TTL_SEC, body)
        pipe.lpush(recent_key(iid), body)
        pipe.ltrim(recent_key(iid), 0, RECENT_MAX - 1)
        pipe.expire(recent_key(iid), TTL_SEC)
        pipe.publish(UPDATED_CHANNEL, body)
        pipe.execute()
        return True
    except Exception:
        return False


def set_meta(index_id: str, meta: Dict[str, Any]) -> bool:
    r = _redis()
    if not r:
        return False
    iid = (index_id or "BRTI").strip().upper()
    try:
        r.setex(meta_key(iid), TTL_SEC, json.dumps(meta, default=str))
        return True
    except Exception:
        return False


def get_latest(index_id: str) -> Optional[Dict[str, Any]]:
    r = _redis()
    if not r:
        return None
    raw = r.get(index_key((index_id or "BRTI").strip().upper()))
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None


def get_recent(index_id: str, limit: int = 50) -> List[Dict[str, Any]]:
    r = _redis()
    if not r:
        return []
    lim = max(1, min(int(limit), RECENT_MAX))
    raw_list = r.lrange(recent_key((index_id or "BRTI").strip().upper()), 0, lim - 1)
    out: List[Dict[str, Any]] = []
    for raw in raw_list or []:
        try:
            out.append(json.loads(raw))
        except (json.JSONDecodeError, TypeError):
            continue
    return out


def get_meta(index_id: str) -> Optional[Dict[str, Any]]:
    r = _redis()
    if not r:
        return None
    raw = r.get(meta_key((index_id or "BRTI").strip().upper()))
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None


def build_status(index_id: str = "BRTI") -> Dict[str, Any]:
    latest = get_latest(index_id)
    meta = get_meta(index_id) or {}
    return {
        "index_id": (index_id or "BRTI").strip().upper(),
        "symbol": symbol_for_index(index_id),
        "redis_ok": _redis() is not None,
        "latest": latest,
        "meta": meta,
        "recent_count": len(get_recent(index_id, limit=RECENT_MAX)),
        "checked_at": time.time(),
    }


def build_status_all(index_ids: Optional[List[str]] = None) -> Dict[str, Any]:
    ids = index_ids or parse_index_ids()
    return {
        "index_ids": ids,
        "redis_ok": _redis() is not None,
        "by_index": {iid: build_status(iid) for iid in ids},
        "checked_at": time.time(),
    }
