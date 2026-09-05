#!/usr/bin/env python3
"""
Phase 2 / BTC 15m HWS trading-health monitor (read-only).

Watches for adverse effects after shared probability mmap (B1):
  - live_data.strike_pipeline_health for kalshi/15m/BTC
  - High Water* BTC 15m monitors (auto_trade, auto_trade_status)
  - Recent opens on those monitors
  - Shared mmap files under var/prob_lookup_mmap (or PROB_LOOKUP_MMAP_DIR)
  - Optional process PSS for STG/ATS (true shared-RAM signal; RSS overcounts mmap)

Does not mutate trading state.

Usage (repo root / prod):
  PYTHONPATH=. venv/bin/python scripts/diagnostics/monitor_phase2_trading_health.py --once
  PYTHONPATH=. venv/bin/python scripts/diagnostics/monitor_phase2_trading_health.py \\
      --hours 12 --interval 60 --log logs/phase2_trading_health.log

Exit codes (--once):
  0 = ok
  1 = warn (soft anomalies)
  2 = critical (15m BTC pipeline unhealthy / HWS auto_trade ACTIVE but pipeline dead)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _log(line: str, log_fp=None) -> None:
    msg = f"{_now_iso()} {line}"
    print(msg, flush=True)
    if log_fp is not None:
        log_fp.write(msg + "\n")
        log_fp.flush()


def _mmap_dir() -> str:
    raw = os.getenv("PROB_LOOKUP_MMAP_DIR", "").strip()
    if raw:
        return raw
    return os.path.join(_ROOT, "var", "prob_lookup_mmap")


def _collect_mmap_status() -> Dict[str, Any]:
    d = _mmap_dir()
    out: Dict[str, Any] = {"dir": d, "exists": os.path.isdir(d), "btc_files": []}
    if not out["exists"]:
        return out
    for name in sorted(os.listdir(d)):
        if not name.startswith("btc_"):
            continue
        path = os.path.join(d, name)
        try:
            st = os.stat(path)
            out["btc_files"].append(
                {
                    "name": name,
                    "bytes": st.st_size,
                    "mtime_age_sec": round(time.time() - st.st_mtime, 1),
                }
            )
        except OSError:
            continue
    out["btc_meta_ok"] = any(f["name"].endswith(".meta.json") for f in out["btc_files"])
    out["btc_bin_ok"] = any(f["name"].endswith(".npy") for f in out["btc_files"])
    return out


def _pipeline_btc_15m(conn) -> Dict[str, Any]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT pipeline_healthy, pipeline_health_reason,
                   EXTRACT(EPOCH FROM (NOW() - pipeline_health_checked_at)) AS checked_age_sec,
                   EXTRACT(EPOCH FROM (NOW() - ws_transport_ok_at)) AS transport_age_sec
            FROM live_data.strike_pipeline_health
            WHERE lower(exchange) = 'kalshi'
              AND lower(market) = '15m'
              AND upper(symbol) = 'BTC'
            """
        )
        row = cur.fetchone()
    if not row:
        return {
            "present": False,
            "healthy": False,
            "reason": "missing_health_row",
            "checked_age_sec": None,
            "transport_age_sec": None,
        }
    return {
        "present": True,
        "healthy": bool(row[0]),
        "reason": str(row[1] or ""),
        "checked_age_sec": float(row[2]) if row[2] is not None else None,
        "transport_age_sec": float(row[3]) if row[3] is not None else None,
    }


def _hws_monitors(conn, user_no: str) -> List[Dict[str, Any]]:
    schema = f"users_{user_no}"
    table = f"monitor_list_{user_no}"
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT id, name, strategy, symbol, market, auto_trade, auto_trade_status,
                   COALESCE(limit_close_price, 0), COALESCE(limit_close_offset, 0),
                   COALESCE(stop_loss_offset, 0)
            FROM {schema}.{table}
            WHERE upper(symbol) = 'BTC'
              AND lower(COALESCE(market, '')) = '15m'
              AND (
                strategy ILIKE '%%High Water%%'
                OR strategy ILIKE '%%HWS%%'
              )
            ORDER BY id
            """
        )
        rows = cur.fetchall()
    out = []
    for r in rows:
        out.append(
            {
                "id": str(r[0]),
                "name": r[1],
                "strategy": r[2],
                "symbol": r[3],
                "market": r[4],
                "auto_trade": bool(r[5]),
                "auto_trade_status": str(r[6] or ""),
                "limit_close_price": float(r[7] or 0),
                "limit_close_offset": float(r[8] or 0),
                "stop_loss_offset": float(r[9] or 0),
            }
        )
    return out


def _recent_opens(
    conn, user_no: str, monitor_ids: List[str], hours: float
) -> Dict[str, Any]:
    """Per-monitor: open/active count + rows touched in lookback (updated_at)."""
    if not monitor_ids:
        return {}
    schema = f"users_{user_no}"
    table = f"trades_{user_no}"
    out: Dict[str, Any] = {
        mid: {"active_open": 0, "touched_recent": 0} for mid in monitor_ids
    }
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT monitor::text,
                   COUNT(*) FILTER (
                     WHERE lower(COALESCE(status::text, '')) IN
                       ('active', 'pending', 'open', 'closing')
                   ) AS active_open,
                   COUNT(*) FILTER (
                     WHERE updated_at >= NOW() - (%s || ' hours')::interval
                   ) AS touched_recent
            FROM {schema}.{table}
            WHERE monitor::text = ANY(%s)
            GROUP BY monitor::text
            """,
            (str(hours), monitor_ids),
        )
        for mid, active_open, touched in cur.fetchall():
            out[str(mid)] = {
                "active_open": int(active_open or 0),
                "touched_recent": int(touched or 0),
            }
    return out


def _pss_mb(pid: int) -> Optional[float]:
    try:
        with open(f"/proc/{pid}/smaps_rollup", "r", encoding="utf-8") as f:
            for line in f:
                if line.startswith("Pss:"):
                    # kB
                    return float(line.split()[1]) / 1024.0
    except OSError:
        return None
    return None


def _process_memory_sample() -> Dict[str, Any]:
    """Sample RSS/PSS for STG + ATS (PSS is Linux-only via smaps_rollup)."""
    import subprocess

    try:
        out = subprocess.check_output(["ps", "-ax", "-o", "pid=,rss=,command="], text=True)
    except (OSError, subprocess.CalledProcessError):
        try:
            out = subprocess.check_output(
                ["ps", "-eo", "pid,rss,cmd", "--no-headers"],
                text=True,
            )
        except (OSError, subprocess.CalledProcessError):
            return {"ok": False, "procs": []}
    needles = (
        "strike_table_generator_ws.py",
        "active_trade_supervisor.py",
    )
    procs = []
    for line in out.splitlines():
        line = line.strip()
        if not line or not any(n in line for n in needles):
            continue
        parts = line.split(None, 2)
        if len(parts) < 3:
            continue
        try:
            pid = int(parts[0])
            rss_mb = float(parts[1]) / 1024.0
        except ValueError:
            continue
        cmd = parts[2]
        label = "other"
        if "strike_table_generator_ws" in cmd:
            label = "stg_15m" if "--market 15m" in cmd else (
                "stg_hourly" if "--market hourly" in cmd else "stg"
            )
        elif "active_trade_supervisor" in cmd:
            label = "ats_btc15m" if "btc15m" in cmd else (
                "ats_unified" if "unified" in cmd else "ats"
            )
        pss = _pss_mb(pid)
        procs.append(
            {
                "label": label,
                "pid": pid,
                "rss_mb": round(rss_mb, 1),
                "pss_mb": None if pss is None else round(pss, 1),
                "cmd": cmd[:120],
            }
        )
    pss_vals = [p["pss_mb"] for p in procs if p.get("pss_mb") is not None]
    return {
        "ok": True,
        "procs": procs,
        "pss_sum_mb": round(sum(pss_vals), 1) if pss_vals else None,
        "rss_sum_mb": round(sum(p["rss_mb"] for p in procs), 1),
    }


def _mem_available_mb() -> Optional[float]:
    try:
        with open("/proc/meminfo", "r", encoding="utf-8") as f:
            for line in f:
                if line.startswith("MemAvailable:"):
                    return float(line.split()[1]) / 1024.0
    except OSError:
        return None
    return None


def evaluate_snapshot(
    *,
    user_no: str,
    recent_hours: float,
    writer_dead_sec: float = 900.0,
) -> Tuple[Dict[str, Any], int]:
    """
    Returns (snapshot, severity) where severity is 0 ok / 1 warn / 2 critical.
    """
    from backend.core.config.database import get_system_postgresql_connection

    conn = get_system_postgresql_connection()
    try:
        pipe = _pipeline_btc_15m(conn)
        mons = _hws_monitors(conn, user_no)
        mids = [m["id"] for m in mons]
        opens = _recent_opens(conn, user_no, mids, recent_hours)
        for m in mons:
            stats = opens.get(m["id"]) or {}
            m["active_open"] = int(stats.get("active_open") or 0)
            m["touched_recent"] = int(stats.get("touched_recent") or 0)
    finally:
        conn.close()

    mmap = _collect_mmap_status()
    mem = {
        "mem_available_mb": None
        if _mem_available_mb() is None
        else round(_mem_available_mb(), 1),
        "stg_ats": _process_memory_sample(),
    }

    snap: Dict[str, Any] = {
        "ts": _now_iso(),
        "user_no": user_no,
        "pipeline_btc_15m": pipe,
        "hws_btc_15m_monitors": mons,
        "mmap": mmap,
        "memory": mem,
    }

    severity = 0
    alerts: List[str] = []

    if not pipe.get("present"):
        severity = max(severity, 2)
        alerts.append("btc_15m_pipeline_missing")
    elif not pipe.get("healthy"):
        severity = max(severity, 2)
        alerts.append(f"btc_15m_pipeline_unhealthy:{pipe.get('reason')}")
    else:
        age = pipe.get("checked_age_sec")
        if age is not None and age > writer_dead_sec:
            severity = max(severity, 2)
            alerts.append(f"btc_15m_pipeline_stale_checked_age={age:.0f}s")

    active_hws = [
        m
        for m in mons
        if m.get("auto_trade")
        and str(m.get("auto_trade_status", "")).upper() in ("ACTIVE", "INACTIVE")
    ]
    if active_hws and not pipe.get("healthy"):
        severity = max(severity, 2)
        alerts.append("hws_auto_trade_on_while_pipeline_unhealthy")

    if not mmap.get("btc_bin_ok") or not mmap.get("btc_meta_ok"):
        # Soft until processes warm; critical only if HWS ACTIVE and still missing after note.
        severity = max(severity, 1)
        alerts.append("btc_prob_mmap_missing")

    # DISABLED while auto_trade true is a product signal worth warning.
    for m in mons:
        if m.get("auto_trade") and str(m.get("auto_trade_status", "")).upper() == "DISABLED":
            severity = max(severity, 1)
            alerts.append(f"hws_monitor_{m['id']}_DISABLED")

    snap["alerts"] = alerts
    snap["severity"] = severity
    snap["severity_label"] = {0: "ok", 1: "warn", 2: "critical"}[severity]
    return snap, severity


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--user-no", default="0001", help="Tenant slot (default 0001)")
    ap.add_argument("--once", action="store_true", help="Single snapshot then exit")
    ap.add_argument("--hours", type=float, default=12.0, help="Run duration when looping")
    ap.add_argument("--interval", type=float, default=60.0, help="Seconds between samples")
    ap.add_argument("--recent-hours", type=float, default=2.0, help="Trade open lookback")
    ap.add_argument("--log", default="", help="Append JSONL snapshots to this file")
    ap.add_argument("--json", action="store_true", help="Print full JSON each sample")
    args = ap.parse_args()

    user_no = str(args.user_no).strip()
    if user_no.isdigit():
        user_no = f"{int(user_no):04d}"

    log_fp = open(args.log, "a", encoding="utf-8") if args.log else None
    try:
        deadline = time.monotonic() + max(0.0, float(args.hours) * 3600.0)
        last_sev = 0
        while True:
            snap, sev = evaluate_snapshot(
                user_no=user_no, recent_hours=float(args.recent_hours)
            )
            last_sev = sev
            if args.json:
                line = json.dumps(snap, separators=(",", ":"))
                _log(line, log_fp)
            else:
                pipe = snap["pipeline_btc_15m"]
                mons = snap["hws_btc_15m_monitors"]
                mmap = snap["mmap"]
                mem = snap["memory"]
                active = sum(
                    1
                    for m in mons
                    if m.get("auto_trade")
                    and str(m.get("auto_trade_status", "")).upper() == "ACTIVE"
                )
                opens = sum(int(m.get("touched_recent") or 0) for m in mons)
                active_open = sum(int(m.get("active_open") or 0) for m in mons)
                pss = (mem.get("stg_ats") or {}).get("pss_sum_mb")
                _log(
                    f"sev={snap['severity_label']} "
                    f"pipe_healthy={pipe.get('healthy')} age={pipe.get('checked_age_sec')} "
                    f"reason={pipe.get('reason')!r} "
                    f"hws_monitors={len(mons)} hws_ACTIVE={active} "
                    f"active_open={active_open} touched_{args.recent_hours:g}h={opens} "
                    f"mmap_btc={bool(mmap.get('btc_bin_ok'))} "
                    f"mem_avail_mb={mem.get('mem_available_mb')} pss_stg_ats_mb={pss} "
                    f"alerts={snap.get('alerts')}",
                    log_fp,
                )
                if log_fp is not None:
                    log_fp.write(json.dumps(snap, separators=(",", ":")) + "\n")
                    log_fp.flush()

            if args.once:
                return sev
            if time.monotonic() >= deadline:
                return last_sev
            time.sleep(max(1.0, float(args.interval)))
    finally:
        if log_fp is not None:
            log_fp.close()


if __name__ == "__main__":
    sys.exit(main())
