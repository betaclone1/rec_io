#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from scripts.backtest.helpers.aes_hourly_tick_replay import run_exact_hourly_cycle_aes_replay
from scripts.backtest.helpers.db import get_connection


def _cycle_prefix(symbol: str, date_et: str, hour_et: int) -> str:
    d = datetime.strptime(date_et, "%Y-%m-%d")
    return f"KX{symbol}D-{d.strftime('%y').upper()}{d.strftime('%b').upper()}{d.strftime('%d')}{int(hour_et):02d}-T"


def _window_for_hourly_close(date_et: str, hour_et: int) -> tuple[datetime, datetime]:
    d = datetime.strptime(date_et, "%Y-%m-%d")
    end_et = d.replace(hour=int(hour_et), minute=0, second=0, microsecond=0, tzinfo=ZoneInfo("America/New_York"))
    return end_et - timedelta(hours=1), end_et


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Exact-style AES replay for one hourly contract cycle.")
    p.add_argument("--symbol", required=True, choices=("BTC", "ETH", "SOL", "XRP"))
    p.add_argument("--date-et", required=True, help="ET date YYYY-MM-DD for contract close day.")
    p.add_argument("--hour-et", required=True, type=int, help="ET close hour (0-23).")
    p.add_argument("--monitor-id", required=True, type=int)
    p.add_argument("--monitor-user", default="0001")
    p.add_argument("--bankroll", type=float, default=10_000.0)
    p.add_argument("--allocation-pct", type=float, default=20.0)
    p.add_argument("--json-out", action="store_true")
    args = p.parse_args(argv)

    if not str(args.monitor_user).isdigit():
        print("error: --monitor-user must be digits only", file=sys.stderr)
        return 2
    if not (0 <= int(args.hour_et) <= 23):
        print("error: --hour-et must be 0..23", file=sys.stderr)
        return 2

    pref = _cycle_prefix(str(args.symbol), str(args.date_et), int(args.hour_et))
    t0, t1 = _window_for_hourly_close(str(args.date_et), int(args.hour_et))
    monitor_table = f"monitor_list_{args.monitor_user}"

    conn = get_connection()
    try:
        out = run_exact_hourly_cycle_aes_replay(
            conn,
            monitor_table=monitor_table,
            monitor_id=int(args.monitor_id),
            cycle_prefix=pref,
            timestamp_start=t0,
            timestamp_end_exclusive=t1,
            bankroll=float(args.bankroll),
            allocation_pct=float(args.allocation_pct),
            spike_alert_active=False,
        )
    finally:
        conn.close()

    payload = {
        "cycle_prefix": pref,
        "window": {"start": t0.isoformat(), "end_exclusive": t1.isoformat()},
        **out,
    }
    if args.json_out:
        print(json.dumps(payload, indent=2, default=str))
        return 0

    s = payload["summary"]
    print(f"Cycle {pref}  window={payload['window']['start']}..{payload['window']['end_exclusive']}")
    print(
        f"markets={s['markets']} entries={s['entries']} wins={s['wins']} losses={s['losses']} "
        f"sum_pnl={s['sum_pnl']:.2f} final_equity={s['final_equity']:.2f}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

