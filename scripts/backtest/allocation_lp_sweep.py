#!/usr/bin/env python3
"""
Exhaustive combined sweep: monitor allocations + loss-prevention thresholds.

Use when you want a shared-bankroll replay across multiple monitors, while also
testing per-monitor LP win-streak thresholds after losses.

Current implementation supports exactly 3 monitors (the common case in ops) and
uses NumPy vectorization for speed.

Example:
  REC_IO_BACKTEST_DB=prod REC_IO_BACKTEST_QUIET=1 .venv/bin/python3 scripts/backtest/allocation_lp_sweep.py \
    --start 2026-02-20T00:00:00-05:00 \
    --start-bankroll 5000 \
    --monitor mon_0001_10026:20:30:1:10 \
    --monitor mon_0001_10027:20:30:1:10 \
    --monitor mon_0001_10023:5:15:1:10
"""

from __future__ import annotations

import argparse
import math
import os
import sys
from collections import defaultdict
from datetime import datetime
from typing import Any

import numpy as np

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from scripts.backtest.helpers.db import get_connection
from scripts.backtest.helpers.monitor_context import is_cycle_based_strategy

from backend.core.port_config import default_pool_user_number
from backend.core.tenant_legacy_sql import legacy_users_monitor_list, legacy_users_trades
from backend.trading_mode import _norm_slot


def _tenant_slot_from_monitor_key(mon: str) -> str:
    s = str(mon or "").strip()
    if not s.startswith("mon_"):
        return _norm_slot(default_pool_user_number())
    rest = s[4:]
    slot, _, _ = rest.partition("_")
    return _norm_slot(slot) if slot else _norm_slot(default_pool_user_number())


def _parse_spec(raw: str) -> tuple[str, int, int, int, int]:
    parts = [p.strip() for p in raw.split(":")]
    if len(parts) != 5:
        raise ValueError(f"invalid --monitor spec {raw!r}; expected mon:minAlloc:maxAlloc:minLP:maxLP")
    mon, alo, ahi, lpo, lphi = parts
    a_lo, a_hi = int(alo), int(ahi)
    lp_lo, lp_hi = int(lpo), int(lphi)
    if a_lo < 0 or a_hi < a_lo:
        raise ValueError(f"bad alloc range in {raw!r}")
    if lp_lo < 1 or lp_hi < lp_lo:
        raise ValueError(f"bad LP range in {raw!r}")
    return mon, a_lo, a_hi, lp_lo, lp_hi


def main() -> int:
    ap = argparse.ArgumentParser(description="Allocation + LP exhaustive sweep (3 monitors).")
    ap.add_argument("--start", required=True, help="ISO start timestamp, e.g. 2026-02-20T00:00:00-05:00")
    ap.add_argument("--start-bankroll", type=float, default=5000.0, help="Starting bankroll (USD)")
    ap.add_argument(
        "--monitor",
        action="append",
        required=True,
        help="Repeat 3x: mon_0001_10026:20:30:1:10 (alloc%% range + LP threshold range)",
    )
    args = ap.parse_args()

    specs = [_parse_spec(x) for x in args.monitor]
    if len(specs) != 3:
        raise ValueError("this script currently requires exactly 3 --monitor specs")

    monitors = [s[0] for s in specs]
    start_ts = datetime.fromisoformat(args.start)
    start_cents = int(round(args.start_bankroll * 100.0))

    conn = get_connection()
    try:
        with conn.cursor() as cur:
            mon_ids = [int(m.split("_")[-1]) for m in monitors]
            slot = _tenant_slot_from_monitor_key(monitors[0])
            ml = legacy_users_monitor_list(slot)
            tr = legacy_users_trades(slot)
            cur.execute(f"SELECT id, strategy FROM {ml} WHERE id = ANY(%s)", (mon_ids,))
            strat_rows = cur.fetchall()
            strat_by_id = {int(r[0]): (r[1] or "") for r in strat_rows}

            cur.execute(
                f"""
                SELECT id, monitor, created_at, date, time, ticker, contract, status, buy_price, sell_price, win_loss
                FROM {tr}
                WHERE monitor = ANY(%s)
                  AND created_at >= %s
                ORDER BY created_at ASC, id ASC
                """,
                (monitors, start_ts),
            )
            rows = cur.fetchall()
            cols = [d[0] for d in cur.description]
    finally:
        conn.close()

    raw_records = [dict(zip(cols, r)) for r in rows]
    raw_records = [r for r in raw_records if str(r.get("status") or "").strip().lower() in ("closed", "settled")]

    m_to_i = {m: i for i, m in enumerate(monitors)}
    mon_idx: list[int] = []
    buy: list[float] = []
    sell: list[float] = []
    wl: list[str] = []
    records: list[dict[str, Any]] = []
    for r in raw_records:
        m = str(r.get("monitor") or "")
        if m not in m_to_i:
            continue
        try:
            bp = float(r.get("buy_price")) if r.get("buy_price") is not None else None
            sp = float(r.get("sell_price")) if r.get("sell_price") is not None else None
        except Exception:
            continue
        if bp is None or sp is None or bp <= 0 or bp >= 1:
            continue
        records.append(r)
        mon_idx.append(m_to_i[m])
        buy.append(bp)
        sell.append(sp)
        wl.append(str(r.get("win_loss") or "").strip().upper())

    mon_idx_a = np.array(mon_idx, dtype=np.int8)
    buy_a = np.array(buy, dtype=np.float64)
    sell_a = np.array(sell, dtype=np.float64)
    wl_a = np.array(wl, dtype="U1")
    n_trades = len(mon_idx_a)
    if n_trades == 0:
        print("No usable closed trades after filters.")
        return 1

    # Cycle-end events for cycle-based monitors
    cycle_end_has_loss: dict[int, bool] = {}
    for mi, m in enumerate(monitors):
        mid = int(m.split("_")[-1])
        if not is_cycle_based_strategy(strat_by_id.get(mid, "")):
            continue
        idxs = [i for i, mm in enumerate(mon_idx) if mm == mi]
        buckets: dict[str, list[int]] = defaultdict(list)
        for i in idxs:
            r = records[i]
            t = str(r.get("ticker") or "").strip()
            ck = t.rsplit("-", 1)[0] if (t and "-" in t) else f"{r.get('contract') or ''}|{r.get('date') or ''}"
            buckets[ck].append(i)
        for ilist in buckets.values():
            ilist.sort()
            last_i = ilist[-1]
            has_loss = any(wl_a[j] == "L" for j in ilist)
            cycle_end_has_loss[last_i] = has_loss

    # Allocation and LP grids
    alloc_vals = [np.arange(s[1], s[2] + 1, dtype=np.int16) for s in specs]
    lp_vals = [np.arange(s[3], s[4] + 1, dtype=np.int16) for s in specs]

    a0, a1, a2 = np.meshgrid(alloc_vals[0], alloc_vals[1], alloc_vals[2], indexing="ij")
    a0 = a0.ravel().astype(np.float64) / 100.0
    a1 = a1.ravel().astype(np.float64) / 100.0
    a2 = a2.ravel().astype(np.float64) / 100.0
    A = a0.size

    t0, t1, t2 = np.meshgrid(lp_vals[0], lp_vals[1], lp_vals[2], indexing="ij")
    t0 = t0.ravel()
    t1 = t1.ravel()
    t2 = t2.ravel()
    T = t0.size

    N = A * T
    alloc0 = np.tile(a0, T)
    alloc1 = np.tile(a1, T)
    alloc2 = np.tile(a2, T)
    thr0 = np.repeat(t0, A)
    thr1 = np.repeat(t1, A)
    thr2 = np.repeat(t2, A)

    bal = np.full(N, start_cents, dtype=np.int64)
    low = bal.copy()
    win0 = np.zeros(N, dtype=np.int16)
    win1 = np.zeros(N, dtype=np.int16)
    win2 = np.zeros(N, dtype=np.int16)
    lp0 = np.zeros(N, dtype=np.bool_)
    lp1 = np.zeros(N, dtype=np.bool_)
    lp2 = np.zeros(N, dtype=np.bool_)

    cycle_based = [
        is_cycle_based_strategy(strat_by_id.get(int(monitors[0].split("_")[-1]), "")),
        is_cycle_based_strategy(strat_by_id.get(int(monitors[1].split("_")[-1]), "")),
        is_cycle_based_strategy(strat_by_id.get(int(monitors[2].split("_")[-1]), "")),
    ]

    for i in range(n_trades):
        m = int(mon_idx_a[i])
        bp = buy_a[i]
        sp = sell_a[i]

        if m == 0:
            alloc = alloc0
            lpv = lp0
        elif m == 1:
            alloc = alloc1
            lpv = lp1
        else:
            alloc = alloc2
            lpv = lp2

        pos = np.floor((bal.astype(np.float64) / 100.0) * alloc / bp).astype(np.int64)
        pos = np.where(lpv, 1, pos)
        pos = np.maximum(pos, 1)

        ofc = np.ceil(0.07 * pos * bp * (1.0 - bp) * 100.0)
        cp = 1.0 - sp
        cfc = np.ceil(0.07 * pos * cp * (1.0 - cp) * 100.0)
        pnl_d = np.round((sp - bp) * pos - (ofc + cfc) / 100.0, 2)
        pnl_c = np.rint(pnl_d * 100.0).astype(np.int64)

        bal = np.maximum(bal + pnl_c, 1)
        low = np.minimum(low, bal)

        # LP updates
        if m == 0:
            if cycle_based[0]:
                if i in cycle_end_has_loss:
                    if cycle_end_has_loss[i]:
                        win0[:] = 0
                        lp0[:] = True
                    else:
                        win0 += 1
                        lp0 = win0 < thr0
            else:
                w = wl_a[i]
                if w == "L":
                    win0[:] = 0
                    lp0[:] = True
                elif w == "W":
                    win0 += 1
                    lp0 = win0 < thr0
        elif m == 1:
            if cycle_based[1]:
                if i in cycle_end_has_loss:
                    if cycle_end_has_loss[i]:
                        win1[:] = 0
                        lp1[:] = True
                    else:
                        win1 += 1
                        lp1 = win1 < thr1
            else:
                w = wl_a[i]
                if w == "L":
                    win1[:] = 0
                    lp1[:] = True
                elif w == "W":
                    win1 += 1
                    lp1 = win1 < thr1
        else:
            if cycle_based[2]:
                if i in cycle_end_has_loss:
                    if cycle_end_has_loss[i]:
                        win2[:] = 0
                        lp2[:] = True
                    else:
                        win2 += 1
                        lp2 = win2 < thr2
            else:
                w = wl_a[i]
                if w == "L":
                    win2[:] = 0
                    lp2[:] = True
                elif w == "W":
                    win2 += 1
                    lp2 = win2 < thr2

    final_usd = bal.astype(np.float64) / 100.0
    pnl_usd = final_usd - args.start_bankroll
    best_idx = int(np.argmax(pnl_usd))

    best = {
        monitors[0]: int(round(alloc0[best_idx] * 100)),
        monitors[1]: int(round(alloc1[best_idx] * 100)),
        monitors[2]: int(round(alloc2[best_idx] * 100)),
    }
    best_lp = {
        monitors[0]: int(thr0[best_idx]),
        monitors[1]: int(thr1[best_idx]),
        monitors[2]: int(thr2[best_idx]),
    }

    print(f"combos_total={N} (alloc={A} x lp={T})")
    print("BEST_COMBO")
    for m in monitors:
        print(f"alloc_{m}={best[m]}% lp_threshold_{m}={best_lp[m]}")
    print(f"final_balance_usd={final_usd[best_idx]:.2f}")
    print(f"final_pnl_usd={pnl_usd[best_idx]:.2f}")
    print(f"ret_pct={(pnl_usd[best_idx] / args.start_bankroll) * 100.0:.5f}")
    print(f"lowest_balance_usd={low[best_idx] / 100.0:.2f}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
