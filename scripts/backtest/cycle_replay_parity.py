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

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.util.cycle_replay.runner import run_cycle_replay
from backend.util.cycle_replay.trade_shape import (
    normalize_trade_side,
    trade_row_from_position,
)


COMPARE_FIELDS = (
    "side",
    "buy_price",
    "initial_price",
    "initial_proj_price",
    "initial_proj_fees",
    "position",
    "fees",
    "sell_price",
    "status",
    "close_method",
    "market_result",
    "win_loss",
)


def _parse_ts(raw: str) -> datetime:
    s = str(raw).strip().replace("Z", "+00:00")
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


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


def _print_side_by_side(replay: Dict[str, Any], live: Dict[str, Any]) -> None:
    print(f"{'field':<22} {'replay':<18} {'live':<18} note")
    print("-" * 72)
    for key in COMPARE_FIELDS:
        rv = replay.get(key)
        lv = live.get(key)
        note = ""
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
        print(f"{key:<22} {_fmt(rv):<18} {_fmt(lv):<18} {note}")


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

    if not result.positions:
        print("FAIL: replay produced no position")
        if args.json_out:
            Path(args.json_out).write_text(json.dumps(payload, indent=2))
        return 2

    replay_row = trade_row_from_position(
        ticker=result.market_ticker,
        position=result.positions[0],
        market_result=result.market_result,
    )
    payload["replay_trade"] = replay_row

    if live:
        print("--- side-by-side (trades_* fields) ---")
        _print_side_by_side(replay_row, live)

        # Entry timing (informational)
        live_ts = None
        if args.compare_entry_utc:
            live_ts = _parse_ts(args.compare_entry_utc)
        elif live.get("entry_time_utc"):
            live_ts = _parse_ts(str(live["entry_time_utc"]))
        if live_ts is not None and result.first_entry is not None:
            dt_s = (result.first_entry.timestamp - live_ts).total_seconds()
            print(
                f"entry_time_delta_s: {dt_s:+.1f} "
                f"(replay={result.first_entry.timestamp.isoformat().replace('+00:00','Z')} "
                f"live={live_ts.isoformat().replace('+00:00','Z')})"
            )

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
            Path(args.json_out).write_text(json.dumps(payload, indent=2))
        return 0 if ok else 1

    # No live row: dump replay trade shape only
    print("--- replay trade ---")
    for k in COMPARE_FIELDS:
        print(f"  {k}: {replay_row.get(k)}")
    if args.json_out:
        Path(args.json_out).write_text(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
