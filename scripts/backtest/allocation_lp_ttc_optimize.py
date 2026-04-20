#!/usr/bin/env python3
"""
Scalable optimizer for shared-bankroll monitor settings:
- per-monitor allocation %
- per-monitor LP win-streak threshold
- per-monitor max TTC minutes filter

Unlike brute-force cartesian sweeps, this uses large random exploration plus
discrete local refinement, so it can handle very large search spaces.
"""

from __future__ import annotations

import argparse
import math
import os
import random
import sys
from collections import defaultdict
from datetime import datetime
from typing import Any

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from scripts.backtest.helpers.db import get_connection
from scripts.backtest.helpers.hypothetical_trades import open_to_next_boundary_minutes
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


def _parse_monitor(raw: str) -> tuple[str, int, int, int, int, int, int]:
    # mon:minAlloc:maxAlloc:minLP:maxLP:minTTC:maxTTC
    p = [x.strip() for x in raw.split(":")]
    if len(p) != 7:
        raise ValueError(
            f"invalid --monitor {raw!r}; expected mon:minAlloc:maxAlloc:minLP:maxLP:minTTC:maxTTC"
        )
    mon = p[0]
    a_lo, a_hi = int(p[1]), int(p[2])
    lp_lo, lp_hi = int(p[3]), int(p[4])
    t_lo, t_hi = int(p[5]), int(p[6])
    if a_lo < 0 or a_hi < a_lo:
        raise ValueError(f"bad alloc range in {raw!r}")
    if lp_lo < 0 or lp_hi < lp_lo:
        raise ValueError(f"bad LP range in {raw!r}")
    if t_lo < 0 or t_hi < t_lo:
        raise ValueError(f"bad TTC range in {raw!r}")
    return mon, a_lo, a_hi, lp_lo, lp_hi, t_lo, t_hi


def _parse_spec(raw: str) -> tuple[str, int, int, int, int, int, int]:
    return _parse_monitor(raw)


def _fee(position: int, price: float) -> float:
    if position <= 0 or price <= 0 or price >= 1:
        return 0.0
    return math.ceil(0.07 * position * price * (1.0 - price) * 100.0) / 100.0


def _load_rows(monitors: list[str], start_iso: str) -> tuple[list[dict[str, Any]], dict[str, bool]]:
    start_ts = datetime.fromisoformat(start_iso)
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            mids = [int(m.split("_")[-1]) for m in monitors]
            slot = _tenant_slot_from_monitor_key(monitors[0])
            ml = legacy_users_monitor_list(slot)
            tr = legacy_users_trades(slot)
            cur.execute(f"SELECT id, strategy FROM {ml} WHERE id = ANY(%s)", (mids,))
            strategy_rows = cur.fetchall()
            strategy_by_mon = {f"mon_{slot}_{int(r[0])}": (r[1] or "") for r in strategy_rows}

            cur.execute(
                f"""
                SELECT id, monitor, created_at, date, time, ticker, contract, status,
                       buy_price, sell_price, win_loss
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

    out: list[dict[str, Any]] = []
    cycle_based: dict[str, bool] = {}
    for m in monitors:
        cycle_based[m] = is_cycle_based_strategy(strategy_by_mon.get(m, ""))

    for r in rows:
        d = dict(zip(cols, r))
        st = str(d.get("status") or "").strip().lower()
        if st not in ("closed", "settled"):
            continue
        try:
            bp = float(d.get("buy_price")) if d.get("buy_price") is not None else None
            sp = float(d.get("sell_price")) if d.get("sell_price") is not None else None
        except Exception:
            continue
        if bp is None or sp is None or bp <= 0 or bp >= 1:
            continue
        mon = str(d.get("monitor") or "")
        ttc_min = open_to_next_boundary_minutes(
            d.get("created_at"), "America/New_York", grid_15m=("15m" in strategy_by_mon.get(mon, "").lower())
        )
        d["buy_price"] = bp
        d["sell_price"] = sp
        d["ttc_minutes"] = float(ttc_min) if ttc_min is not None else None
        out.append(d)
    return out, cycle_based


def _build_cycle_end_info(rows: list[dict[str, Any]], cycle_based: dict[str, bool]) -> dict[int, tuple[bool, int]]:
    info: dict[int, tuple[bool, int]] = {}
    for mon, is_cycle in cycle_based.items():
        if not is_cycle:
            continue
        subset = [r for r in rows if str(r.get("monitor") or "") == mon]
        buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for r in subset:
            t = str(r.get("ticker") or "").strip()
            ck = t.rsplit("-", 1)[0] if (t and "-" in t) else f"{r.get('contract') or ''}|{r.get('date') or ''}"
            buckets[ck].append(r)
        for lst in buckets.values():
            lst.sort(key=lambda x: (x.get("created_at"), x.get("id")))
            last = lst[-1]
            wls = [str(x.get("win_loss") or "").strip().upper() for x in lst]
            info[int(last["id"])] = (any(w == "L" for w in wls), sum(1 for w in wls if w == "W"))
    return info


def _evaluate(
    rows: list[dict[str, Any]],
    cycle_based: dict[str, bool],
    cycle_end_info: dict[int, tuple[bool, int]],
    monitors: list[str],
    alloc_pct: dict[str, int],
    lp_thr: dict[str, int],
    ttc_max: dict[str, int],
    start_usd: float,
) -> dict[str, Any]:
    bal_c = int(round(start_usd * 100))
    low_c = bal_c
    # LP semantics: throttle only after a loss event until threshold wins recover.
    state = {m: {"win": 0, "lp": False, "armed": False} for m in monitors}
    low_trade = None

    for r in rows:
        m = str(r["monitor"])
        ttc = r.get("ttc_minutes")
        if ttc is None or float(ttc) > float(ttc_max[m]):
            continue

        bp = float(r["buy_price"])
        sp = float(r["sell_price"])
        pct = alloc_pct[m] / 100.0

        throttle = lp_thr[m] > 0 and state[m]["armed"] and state[m]["lp"]
        pos = 1 if throttle else int(math.floor(((bal_c / 100.0) * pct) / bp))
        if pos < 1:
            continue

        pnl = round((sp - bp) * pos - _fee(pos, bp) - _fee(pos, 1.0 - sp), 2)
        bal_c += int(round(pnl * 100))
        if bal_c < 1:
            bal_c = 1

        if bal_c < low_c:
            low_c = bal_c
            low_trade = r

        # LP updates
        if lp_thr[m] > 0:
            if cycle_based.get(m):
                ce = cycle_end_info.get(int(r["id"]))
                if ce:
                    has_loss, win_count = ce
                    if has_loss:
                        state[m]["win"] = 0
                        state[m]["armed"] = True
                        state[m]["lp"] = True
                    elif state[m]["armed"]:
                        state[m]["win"] += 1  # cycle-based: +1 per winning cycle
                        state[m]["lp"] = state[m]["win"] < lp_thr[m]
                        if not state[m]["lp"]:
                            state[m]["armed"] = False
            else:
                wl = str(r.get("win_loss") or "").strip().upper()
                if wl == "L":
                    state[m]["win"] = 0
                    state[m]["armed"] = True
                    state[m]["lp"] = True
                elif wl == "W" and state[m]["armed"]:
                    state[m]["win"] += 1
                    state[m]["lp"] = state[m]["win"] < lp_thr[m]
                    if not state[m]["lp"]:
                        state[m]["armed"] = False

    final_usd = bal_c / 100.0
    pnl_usd = final_usd - start_usd
    return {
        "final_usd": final_usd,
        "pnl_usd": pnl_usd,
        "ret_pct": (pnl_usd / start_usd) * 100.0 if start_usd > 0 else 0.0,
        "low_usd": low_c / 100.0,
        "low_trade": low_trade,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Scalable allocation+LP+TTC optimizer.")
    ap.add_argument("--start", required=True)
    ap.add_argument("--start-bankroll", type=float, default=5000.0)
    ap.add_argument(
        "--monitor",
        action="append",
        required=True,
        help="mon:minAlloc:maxAlloc:minLP:maxLP:minTTC:maxTTC",
    )
    ap.add_argument("--step-alloc", type=int, default=1)
    ap.add_argument("--step-lp", type=int, default=1)
    ap.add_argument("--step-ttc", type=int, default=1)
    ap.add_argument("--random-samples", type=int, default=120000)
    ap.add_argument("--top-seeds", type=int, default=200)
    ap.add_argument("--local-iters", type=int, default=8000)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    specs = [_parse_spec(x) for x in args.monitor]
    monitors = [s[0] for s in specs]
    if len(monitors) != 3:
        raise ValueError("this optimizer currently expects exactly 3 monitors")

    rows, cycle_based = _load_rows(monitors, args.start)
    cycle_end_info = _build_cycle_end_info(rows, cycle_based)
    if not rows:
        print("No usable closed trades for requested monitors/start.")
        return 1

    rng = random.Random(args.seed)

    alloc_choices = {
        s[0]: list(range(s[1], s[2] + 1, args.step_alloc))
        for s in specs
    }
    lp_choices = {
        s[0]: list(range(s[3], s[4] + 1, args.step_lp))
        for s in specs
    }
    ttc_choices = {
        s[0]: list(range(s[5], s[6] + 1, args.step_ttc))
        for s in specs
    }

    seen: set[tuple[int, ...]] = set()
    scored: list[tuple[float, tuple[int, ...], dict[str, Any]]] = []

    def encode(a: dict[str, int], l: dict[str, int], t: dict[str, int]) -> tuple[int, ...]:
        return (
            a[monitors[0]], a[monitors[1]], a[monitors[2]],
            l[monitors[0]], l[monitors[1]], l[monitors[2]],
            t[monitors[0]], t[monitors[1]], t[monitors[2]],
        )

    def decode(v: tuple[int, ...]) -> tuple[dict[str, int], dict[str, int], dict[str, int]]:
        a = {monitors[i]: v[i] for i in range(3)}
        l = {monitors[i]: v[i + 3] for i in range(3)}
        t = {monitors[i]: v[i + 6] for i in range(3)}
        return a, l, t

    def sample_one() -> tuple[int, ...]:
        a = {m: rng.choice(alloc_choices[m]) for m in monitors}
        l = {m: rng.choice(lp_choices[m]) for m in monitors}
        t = {m: rng.choice(ttc_choices[m]) for m in monitors}
        return encode(a, l, t)

    # random exploration
    for _ in range(args.random_samples):
        v = sample_one()
        if v in seen:
            continue
        seen.add(v)
        a, l, t = decode(v)
        res = _evaluate(rows, cycle_based, cycle_end_info, monitors, a, l, t, args.start_bankroll)
        scored.append((res["pnl_usd"], v, res))

    scored.sort(key=lambda x: x[0], reverse=True)
    seed_vectors = [v for _, v, _ in scored[: max(1, args.top_seeds)]]

    # local refinement around top seeds
    dims = list(range(9))
    best = scored[0]
    for _ in range(args.local_iters):
        base = rng.choice(seed_vectors)
        cand = list(base)
        d = rng.choice(dims)
        delta = rng.choice((-1, 1))
        if d <= 2:
            m = monitors[d]
            choices = alloc_choices[m]
        elif d <= 5:
            m = monitors[d - 3]
            choices = lp_choices[m]
        else:
            m = monitors[d - 6]
            choices = ttc_choices[m]
        cur = cand[d]
        nxt = cur + delta * (args.step_alloc if d <= 2 else args.step_lp if d <= 5 else args.step_ttc)
        if nxt not in choices:
            continue
        cand[d] = nxt
        v = tuple(cand)
        if v in seen:
            continue
        seen.add(v)
        a, l, t = decode(v)
        res = _evaluate(rows, cycle_based, cycle_end_info, monitors, a, l, t, args.start_bankroll)
        row = (res["pnl_usd"], v, res)
        if row[0] > best[0]:
            best = row
        scored.append(row)

    scored.sort(key=lambda x: x[0], reverse=True)
    best = scored[0]
    a, l, t = decode(best[1])
    r = best[2]

    print(f"evaluated_combos={len(seen)}")
    print("BEST_COMBO")
    for m in monitors:
        print(f"alloc_{m}={a[m]}% lp_{m}={l[m]} ttc_max_{m}={t[m]}m")
    print(f"final_balance_usd={r['final_usd']:.2f}")
    print(f"final_pnl_usd={r['pnl_usd']:.2f}")
    print(f"ret_pct={r['ret_pct']:.5f}")
    print(f"lowest_balance_usd={r['low_usd']:.2f}")
    lt = r.get("low_trade")
    if lt:
        print(f"low_trade_id={lt.get('id')}")
        print(f"low_monitor={lt.get('monitor')}")
        print(f"low_created_at={lt.get('created_at')}")
        print(f"low_date={lt.get('date')}")
        print(f"low_time={lt.get('time')}")
        print(f"low_ticker={lt.get('ticker')}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
