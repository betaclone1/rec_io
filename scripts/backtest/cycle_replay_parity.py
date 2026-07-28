#!/usr/bin/env python3
"""
Replay a sealed cycle package and compare to a live trades_* row shape.

Example (trade 31246 / Expiration Scalp):

  python3 scripts/backtest/cycle_replay_parity.py \\
    --package …/KXBTC15M-26JUL272045-45.tar.xz \\
    --strategy "Expiration Scalp" \\
    --settings-json '{…,"order_type":"market","time_in_force":"immediate_or_cancel","total_position":3312}' \\
    --compare-live-json '{
      "side":"N","buy_price":0.969554,"initial_price":0.9800,"initial_proj_price":0.96636883,
      "initial_proj_fees":7.54,"position":3312,"fees":6.84345,"sell_price":1.0,
      "status":"closed","market_result":"no","win_loss":"W","close_method":"expired",
      "time":"20:44:04","date":"2026-07-27"
    }'
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.util.cycle_replay.runner import run_cycle_replay
from backend.util.cycle_replay.trade_shape import (
    normalize_trade_side,
    trade_row_from_position,
)


COMPARE_FIELDS = (
    "entry_time",
    "closed_at",
    "side",
    "buy_price",
    "initial_price",
    "initial_proj_price",
    "initial_proj_fees",
    "position",
    "fees",
    "prob",
    "diff",
    "sell_price",
    "status",
    "close_method",
    "market_result",
    "win_loss",
    "ticker",
    "strike",
    "symbol",
    "contract",
    "monitor",
    "trade_strategy",
    "entry_method",
)


def _parse_ts(raw: str) -> datetime:
    s = str(raw).strip().replace("Z", "+00:00")
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _fmt_trade_time(v: Any) -> str:
    """Display as ``HH:MM:SS ET`` plus UTC when we have a full datetime."""
    if v is None or v == "":
        return "—"
    if isinstance(v, datetime):
        dt = v if v.tzinfo else v.replace(tzinfo=timezone.utc)
        est = dt.astimezone(ZoneInfo("America/New_York"))
        return f"{est.strftime('%H:%M:%S')} ET ({dt.astimezone(timezone.utc).strftime('%H:%M:%S')}Z)"
    s = str(v).strip()
    # Already a wall clock from trades.time / closed_at
    if len(s) <= 12 and ":" in s and "T" not in s and "Z" not in s:
        return f"{s} ET"
    try:
        return _fmt_trade_time(_parse_ts(s))
    except (TypeError, ValueError):
        return s


def _fmt(v: Any) -> str:
    if v is None:
        return "—"
    if isinstance(v, float):
        return f"{v:.6f}".rstrip("0").rstrip(".") if abs(v) < 1000 else f"{v:.4f}"
    return str(v)


def _num(v: Any) -> Optional[float]:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _live_entry_time(live: Dict[str, Any], entry_utc_override: Optional[str]) -> Optional[str]:
    if entry_utc_override:
        return entry_utc_override
    for key in ("entry_time_utc", "entry_time", "created_at"):
        if live.get(key):
            return str(live[key])
    # trades_* stores Eastern wall ``date`` + ``time``
    d, t = live.get("date"), live.get("time")
    if d and t:
        try:
            naive = datetime.strptime(f"{d} {t}", "%Y-%m-%d %H:%M:%S")
            est = naive.replace(tzinfo=ZoneInfo("America/New_York"))
            return est.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
        except ValueError:
            return f"{t} ET"
    if t:
        return f"{t} ET"
    return None


def _live_closed_at(live: Dict[str, Any]) -> Optional[str]:
    for key in ("closed_at_utc", "exit_time_utc"):
        if live.get(key):
            return str(live[key])
    # trades_* closed_at is often HH:MM:SS Eastern only — combine with date
    d, t = live.get("date"), live.get("closed_at")
    if d and t and ":" in str(t) and "T" not in str(t) and "Z" not in str(t):
        try:
            naive = datetime.strptime(f"{d} {t}", "%Y-%m-%d %H:%M:%S")
            est = naive.replace(tzinfo=ZoneInfo("America/New_York"))
            return est.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
        except ValueError:
            return f"{t} ET"
    if live.get("closed_at"):
        return str(live["closed_at"])
    return None


def _time_delta_note(replay_raw: Any, live_raw: Any) -> str:
    try:
        if replay_raw is None or live_raw is None:
            return ""
        rt = replay_raw if isinstance(replay_raw, datetime) else _parse_ts(str(replay_raw))
        # live may be "HH:MM:SS ET" only — skip delta
        ls = str(live_raw)
        if "T" not in ls and "Z" not in ls and "+" not in ls and ls.endswith("ET"):
            return ""
        if "T" not in ls and "Z" not in ls and len(ls) <= 12:
            return ""
        lt = live_raw if isinstance(live_raw, datetime) else _parse_ts(ls)
        d = (rt - lt).total_seconds()
        return f"Δ={d:+.0f}s"
    except (TypeError, ValueError):
        return ""


def _print_side_by_side(replay: Dict[str, Any], live: Dict[str, Any]) -> None:
    print(f"{'field':<22} {'replay':<36} {'live':<36} note")
    print("-" * 110)
    for key in COMPARE_FIELDS:
        rv = replay.get(key)
        lv = live.get(key)
        note = ""
        if key in ("entry_time", "closed_at"):
            note = _time_delta_note(rv, lv)
            print(
                f"{key:<22} {_fmt_trade_time(rv):<36} {_fmt_trade_time(lv):<36} {note}"
            )
            continue
        if key == "side":
            rv = normalize_trade_side(rv) if rv is not None else None
            lv = normalize_trade_side(lv) if lv is not None else None
            if rv is not None and lv is not None and rv != lv:
                note = "MISMATCH"
        elif key in (
            "buy_price",
            "initial_price",
            "initial_proj_price",
            "initial_proj_fees",
            "fees",
            "sell_price",
            "position",
        ):
            rn, ln = _num(rv), _num(lv)
            if rn is not None and ln is not None:
                d = abs(rn - ln)
                if key in ("buy_price", "initial_price", "initial_proj_price") and d > 0.01:
                    note = f"Δ={d:.6f}"
                elif key in ("fees", "initial_proj_fees") and d > 0.05:
                    note = f"Δ={d:.4f}"
                elif key == "position" and d >= 1:
                    note = f"Δ={d:.0f}"
                elif key == "sell_price" and d > 1e-6:
                    note = f"Δ={d:.6f}"
        else:
            rs = str(rv).strip().lower() if rv is not None else None
            ls = str(lv).strip().lower() if lv is not None else None
            if rs is not None and ls is not None and rs != ls:
                note = "MISMATCH"
        print(f"{key:<22} {_fmt(rv):<36} {_fmt(lv):<36} {note}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--package", required=True, help="Path to cycle .tar.xz package")
    ap.add_argument("--strategy", default="Expiration Scalp")
    ap.add_argument("--settings-json", required=True, help="Frozen monitor/strategy settings JSON")
    ap.add_argument("--settings-file", default=None)
    ap.add_argument(
        "--compare-live-json",
        default=None,
        help="Live trades_* row JSON (preferred: same field names as DB)",
    )
    ap.add_argument("--compare-entry-utc", default=None, help="Optional live entry UTC override")
    ap.add_argument("--json-out", default=None)
    args = ap.parse_args()

    if args.settings_file:
        settings = json.loads(Path(args.settings_file).read_text())
    else:
        settings = json.loads(args.settings_json)

    live: Dict[str, Any] = {}
    if args.compare_live_json:
        live = json.loads(args.compare_live_json)

    result = run_cycle_replay(args.package, settings, strategy=args.strategy)
    payload = result.to_dict()

    print(f"package: {result.market_ticker}")
    print(f"strategy: {result.strategy}")
    print(f"ticks_scanned: {result.ticks_scanned}")
    print(f"market_result: {result.market_result}")
    print("--- settings ---")
    print(json.dumps(result.settings, indent=2, default=str))

    if not result.positions:
        print("FAIL: replay produced no position")
        print("--- full replay payload ---")
        print(json.dumps(payload, indent=2, default=str))
        if args.json_out:
            Path(args.json_out).write_text(json.dumps(payload, indent=2, default=str))
        return 2

    replay_row = trade_row_from_position(
        ticker=result.market_ticker,
        position=result.positions[0],
        market_result=result.market_result,
    )
    # Carry entry detail fields into the compare row when present.
    detail = (result.positions[0].entry.detail or {}) if result.positions else {}
    if replay_row.get("diff") is None and detail.get("diff") is not None:
        replay_row["diff"] = detail.get("diff")
    if replay_row.get("strike") is None and detail.get("strike") is not None:
        replay_row["strike"] = detail.get("strike")
    payload["replay_trade"] = replay_row

    if live:
        # Normalize live times into the same keys the table prints first.
        live = dict(live)
        live["entry_time"] = _live_entry_time(live, args.compare_entry_utc) or live.get(
            "entry_time"
        )
        live["closed_at"] = _live_closed_at(live) or live.get("closed_at")
        payload["live_trade"] = live

        print("--- side-by-side (trades_* fields) ---")
        _print_side_by_side(replay_row, live)

        print("--- replay first_entry (full) ---")
        print(json.dumps(payload.get("first_entry"), indent=2, default=str))
        print("--- replay exit (full) ---")
        print(json.dumps(payload["positions"][0].get("exit"), indent=2, default=str))
        print("--- rejected_entries ---")
        print(json.dumps(payload.get("rejected_entries") or [], indent=2, default=str))
        print("--- live trade (input) ---")
        print(json.dumps(live, indent=2, default=str))
        print("--- full replay payload ---")
        print(json.dumps(payload, indent=2, default=str))

        side_ok = normalize_trade_side(replay_row.get("side")) == normalize_trade_side(live.get("side"))
        exit_ok = (
            str(replay_row.get("close_method") or "").lower()
            == str(live.get("close_method") or "").lower()
            and str(replay_row.get("status") or "").lower() == str(live.get("status") or "").lower()
            and str(replay_row.get("win_loss") or "").upper() == str(live.get("win_loss") or "").upper()
            and str(replay_row.get("market_result") or "").lower()
            == str(live.get("market_result") or "").lower()
        )
        ticket_r = _num(replay_row.get("initial_price"))
        ticket_l = _num(live.get("initial_price"))
        ticket_ok = (
            ticket_r is not None and ticket_l is not None and abs(ticket_r - ticket_l) <= 0.01
        )
        ok = side_ok and exit_ok and ticket_ok
        print(
            f"parity: {'PASS' if ok else 'FAIL'} "
            f"(side={side_ok} exit={exit_ok} initial_price<=0.01={ticket_ok})"
        )
        if args.json_out:
            Path(args.json_out).write_text(json.dumps(payload, indent=2, default=str))
        return 0 if ok else 1

    # No live row: dump full replay
    print("--- replay trade ---")
    print(json.dumps(replay_row, indent=2, default=str))
    print("--- full replay payload ---")
    print(json.dumps(payload, indent=2, default=str))
    if args.json_out:
        Path(args.json_out).write_text(json.dumps(payload, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
