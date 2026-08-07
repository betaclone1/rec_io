#!/usr/bin/env python3
"""
Print tradeflow-relevant env / Redis / live_state parity knobs for side-by-side host compare.

Read-only. Does not change trading behavior.

Usage (from repo root):
  python3 scripts/diagnostics/check_tradeflow_env_parity.py
  python3 scripts/diagnostics/check_tradeflow_env_parity.py --json
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(os.path.dirname(SCRIPT_DIR))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# (env_name, default_if_unset_for_display)
ENV_KEYS: List[Tuple[str, str]] = [
    ("LIVE_STATE_CACHE_ENABLED", "(default on)"),
    ("TRADEFLOW_LIVE_STATE_TRIGGER", "1"),
    ("TRADEFLOW_LIVE_STATE_TRIGGER_MIN_SEC", "0.2"),
    ("TRADEFLOW_ORDERBOOK_TRIGGER_MIN_SEC", "0.05"),
    ("TRADEFLOW_LIVE_STATE_MAX_AGE_SEC", "(falls back to REC_STRIKE_SNAPSHOT_MAX_AGE_SEC)"),
    ("REC_STRIKE_SNAPSHOT_MAX_AGE_SEC", "3"),
    ("AES_FAILSAFE_POLL_SEC", "1"),
    ("ATS_MONITOR_SAFETY_WAKE_SEC", "30"),
    ("USE_TRADING_REDIS_COMMS", "(see trading_redis_comms)"),
    ("TRADEFLOW_MONITOR_SETTINGS_CACHE_TTL_SEC", "3"),
    ("SYMBOL_HOT_PUBLISH_MAX_HZ", "1"),
    ("STRIKE_PIPELINE_HEALTH_STRICT_MODE", "(see strike_pipeline_health)"),
    ("STRIKE_REGEN_MIN_INTERVAL_SEC", "0.25"),
    ("AES_UNIFIED_PROFILE", "0"),
    ("TRADEFLOW_DECISION_TRACE", "0"),
    ("TRADEFLOW_DECISION_TRACE_VERBOSE", "0"),
    ("REDIS_HOST", "localhost"),
    ("REDIS_PORT", "6379"),
    ("REDIS_URL", "(unset)"),
    ("REC_ENVIRONMENT", "(unset)"),
    ("REC_USER_SCHEMA", "(unset)"),
]


def _env_display(name: str, default_hint: str) -> Dict[str, Any]:
    raw = os.getenv(name)
    return {
        "name": name,
        "set": raw is not None,
        "value": raw if raw is not None else None,
        "effective_hint": raw if raw is not None else default_hint,
    }


def _redis_ping() -> Dict[str, Any]:
    try:
        from backend.core.live_state_cache import redis_client_optional

        r = redis_client_optional()
        if not r:
            return {"ok": False, "error": "no client"}
        pong = r.ping()
        info = {"ok": bool(pong)}
        try:
            # Sample ladder / symbol keys if present (names only)
            keys = list(r.scan_iter(match="rec_io:live_state:v1:strike_ladder:*", count=20))
            info["strike_ladder_key_sample_n"] = len(keys)
            info["strike_ladder_key_sample"] = sorted(keys)[:8]
        except Exception as e:
            info["scan_error"] = str(e)[:120]
        return info
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


def _live_state_flags() -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    try:
        from backend.core.live_state_config import live_state_cache_enabled

        out["live_state_cache_enabled"] = live_state_cache_enabled()
    except Exception as e:
        out["live_state_cache_enabled_error"] = str(e)[:120]
    try:
        from backend.core.tradeflow_live_state_trigger import (
            tradeflow_live_state_trigger_enabled,
            tradeflow_orderbook_trigger_min_interval_sec,
            tradeflow_trigger_min_interval_sec,
        )

        out["live_state_trigger_enabled"] = tradeflow_live_state_trigger_enabled()
        out["trigger_min_sec"] = tradeflow_trigger_min_interval_sec()
        out["orderbook_trigger_min_sec"] = tradeflow_orderbook_trigger_min_interval_sec()
    except Exception as e:
        out["trigger_error"] = str(e)[:120]
    try:
        from backend.core.tradeflow_live_reads import tradeflow_live_state_max_age_sec

        out["max_age_sec"] = tradeflow_live_state_max_age_sec()
    except Exception:
        # function name may differ — best-effort
        try:
            from backend.core import tradeflow_live_reads as tlr

            fn = getattr(tlr, "tradeflow_live_state_max_age_sec", None) or getattr(
                tlr, "_max_age_sec", None
            )
            out["max_age_sec"] = fn() if callable(fn) else None
        except Exception as e:
            out["max_age_error"] = str(e)[:120]
    try:
        from backend.core.trading_redis_comms import use_trading_redis_comms

        out["use_trading_redis_comms"] = use_trading_redis_comms()
    except Exception as e:
        out["trading_redis_error"] = str(e)[:120]
    try:
        from backend.core.strike_pipeline_health import strike_pipeline_health_strict_mode_enabled

        out["pipeline_strict_mode"] = strike_pipeline_health_strict_mode_enabled()
    except Exception:
        raw = os.getenv("STRIKE_PIPELINE_HEALTH_STRICT_MODE")
        out["pipeline_strict_mode_env"] = raw
    return out


def collect() -> Dict[str, Any]:
    return {
        "host": socket.gethostname(),
        "utc_now": datetime.now(timezone.utc).isoformat(),
        "cwd": os.getcwd(),
        "project_root": PROJECT_ROOT,
        "env": [_env_display(n, d) for n, d in ENV_KEYS],
        "resolved": _live_state_flags(),
        "redis": _redis_ping(),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Tradeflow env / Redis parity checklist")
    ap.add_argument("--json", action="store_true", help="Emit JSON")
    args = ap.parse_args()
    data = collect()
    if args.json:
        print(json.dumps(data, indent=2, default=str))
        return 0

    print(f"tradeflow env parity @ {data['host']}  {data['utc_now']}")
    print(f"project_root={data['project_root']}")
    print()
    print("ENV (set vs effective hint)")
    for row in data["env"]:
        flag = "SET" if row["set"] else "def"
        print(f"  [{flag}] {row['name']}={row['effective_hint']}")
    print()
    print("RESOLVED")
    for k, v in sorted(data["resolved"].items()):
        print(f"  {k}={v}")
    print()
    print("REDIS")
    for k, v in sorted(data["redis"].items()):
        print(f"  {k}={v}")
    print()
    print(
        "Compare this output across hosts (or with --json). "
        "Enable TRADEFLOW_DECISION_TRACE=1 on AES/ATS to correlate decision logs."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
