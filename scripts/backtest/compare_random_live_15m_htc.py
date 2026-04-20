#!/usr/bin/env python3
"""
Sample random live **15m HTC** (``trade_strategy`` ``15m HTC`` or ``Hourly HTC``) auto entries from prod ``users.trades_<default pool slot>``,
run ``backtest_market_simulator`` per ticker/date, and print deltas vs recorded trades.

Pulls trades from **prod** (SSH). Runs the sim with ``REC_IO_BACKTEST_DB`` = **local** by default
(so ``btc_price_history`` / analytics match typical dev backtests); use ``--sim-db prod`` to
run the sim on prod (often missing historical BTC rows → no entries). Infers ``--symbol eth``
from ``KXETH…`` tickers.

Usage::

  REC_IO_BACKTEST_QUIET=1 .venv/bin/python3 scripts/backtest/compare_random_live_15m_htc.py \\
    [--seed 42] [--limit 10] [--sim-db local] [--max-date YYYY-MM-DD]
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from typing import Any, Optional

try:
    from zoneinfo import ZoneInfo
except ImportError:
    ZoneInfo = None  # type: ignore

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)


def _parse_live_strike(s: Optional[str]) -> Optional[int]:
    if not s:
        return None
    cleaned = str(s).replace("$", "").replace(",", "").strip()
    try:
        return int(float(cleaned))
    except (TypeError, ValueError):
        return None


def _live_entry_et(created_at: Any, date_s: str, time_s: str) -> Optional[datetime]:
    if ZoneInfo is None:
        raise RuntimeError("zoneinfo required")
    if created_at is not None:
        if isinstance(created_at, datetime):
            ca = created_at
            if ca.tzinfo is None:
                ca = ca.replace(tzinfo=timezone.utc)
            return ca.astimezone(ZoneInfo("America/New_York"))
    try:
        naive = datetime.strptime(f"{date_s.strip()} {time_s.strip()}", "%Y-%m-%d %H:%M:%S")
        return naive.replace(tzinfo=ZoneInfo("America/New_York"))
    except (TypeError, ValueError):
        return None


def _parse_sim_summary(blob: str) -> Optional[dict[str, Any]]:
    for line in blob.splitlines():
        s = line.strip()
        if s.startswith("SIM_SUMMARY_JSON "):
            try:
                return json.loads(s[len("SIM_SUMMARY_JSON ") :])
            except json.JSONDecodeError:
                return None
    return None


def _infer_symbol_from_ticker(ticker: str) -> str:
    u = ticker.strip().upper()
    if u.startswith("KXETH"):
        return "eth"
    return "btc"


def main() -> int:
    ap = argparse.ArgumentParser(description="Compare random prod 15m HTC trades to market sim")
    ap.add_argument("--seed", type=int, default=42, help="Random seed for ORDER BY (default 42)")
    ap.add_argument("--limit", type=int, default=10, help="Number of trades to sample (default 10)")
    ap.add_argument(
        "--sim-db",
        choices=("local", "prod"),
        default="local",
        help="DB target for each sim run (default local: historical BTC/ETH rows for backtests)",
    )
    ap.add_argument(
        "--max-date",
        metavar="YYYY-MM-DD",
        default=None,
        help="Only trades with ``date`` (text) <= this day (ISO); e.g. 2026-03-19 excludes 3/20+",
    )
    args = ap.parse_args()

    if ZoneInfo is None:
        print("zoneinfo is required", file=sys.stderr)
        return 1

    from scripts.backtest.helpers.constants import TRADES_TABLE  # noqa: E402
    from scripts.backtest.helpers.db import get_connection  # noqa: E402

    _prev_db = os.environ.get("REC_IO_BACKTEST_DB")
    os.environ["REC_IO_BACKTEST_DB"] = "prod"
    try:
        conn = get_connection()
        try:
            with conn.cursor() as cur:
                seedf = ((args.seed % 999983) / 999983.0) * 2.0 - 1.0
                cur.execute("SELECT setseed(%s)", (seedf,))
                max_d = (args.max_date or "").strip()
                extra = " AND date <= %s" if max_d else ""
                qparams: list[Any] = []
                if max_d:
                    qparams.append(max_d)
                qparams.append(args.limit)
                cur.execute(
                    f"""
                    SELECT id, ticker, date, time, created_at, buy_price, strike, symbol_open, side
                    FROM {TRADES_TABLE}
                    WHERE (paper_trade IS NULL OR paper_trade = false)
                      AND ticker IS NOT NULL
                      AND ticker ILIKE '%%15M%%'
                      AND COALESCE(trade_strategy, '') IN ('15m HTC', 'Hourly HTC')
                      AND COALESCE(entry_method, '') = 'auto_entry'
                      AND buy_price IS NOT NULL
                      AND date IS NOT NULL
                      AND time IS NOT NULL
                      {extra}
                    ORDER BY random()
                    LIMIT %s
                    """,
                    tuple(qparams),
                )
                rows = cur.fetchall()
                colnames = [d[0] for d in cur.description]
        finally:
            conn.close()
    finally:
        if _prev_db is None:
            os.environ.pop("REC_IO_BACKTEST_DB", None)
        else:
            os.environ["REC_IO_BACKTEST_DB"] = _prev_db

    if not rows:
        print("No matching trades in prod (check filters).", file=sys.stderr)
        return 1

    py = sys.executable
    sim_py = os.path.join(_PROJECT_ROOT, "scripts", "backtest", "backtest_market_simulator.py")

    print(
        "| trade_id | ticker | live_entry_ET | sim_entry_ET | d_entry_s | "
        "live_buy | sim_buy | d_buy | live_strike | sim_strike | d_strike | "
        "live_sym_open | sim_spot | d_spot | sim_ok | notes |"
    )
    print("| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |")

    for row in rows:
        t = dict(zip(colnames, row))
        tid = t["id"]
        ticker = str(t["ticker"]).strip()
        date_s = str(t["date"]).strip()
        live_et = _live_entry_et(t.get("created_at"), date_s, str(t["time"]))
        live_buy = float(t["buy_price"])
        live_strike = _parse_live_strike(t.get("strike"))
        live_open = float(t["symbol_open"]) if t.get("symbol_open") is not None else None

        cmd = [
            py,
            sim_py,
            "--storage",
            "scratch",
            "--fetch-candles",
            "--ticker",
            ticker,
            "--as-of",
            date_s,
            "--symbol",
            _infer_symbol_from_ticker(ticker),
            "--emit-summary-json",
            "--no-gate-reasons",
        ]
        env = {**os.environ, "REC_IO_BACKTEST_DB": args.sim_db}
        r = subprocess.run(
            cmd,
            cwd=_PROJECT_ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=240,
        )
        blob = (r.stdout or "") + "\n" + (r.stderr or "")
        summ = _parse_sim_summary(blob)
        notes = []
        if r.returncode != 0 and not summ:
            notes.append(f"exit={r.returncode}")
            if (r.stderr or "").strip():
                es = (r.stderr or "").strip()
                notes.append((es[:120] + "…") if len(es) > 200 else es)
        if summ and summ.get("reason"):
            notes.append(str(summ["reason"]))
        if summ and summ.get("error"):
            notes.append(str(summ["error"])[:80])
        if summ and not summ.get("first_hit"):
            notes.append(f"sim_db={args.sim_db}")

        sim_ok = bool(summ and summ.get("first_hit"))
        sim_ts_s = summ.get("timestamp_et") if summ else None
        sim_et = None
        if sim_ts_s:
            try:
                sim_et = datetime.strptime(sim_ts_s[:19], "%Y-%m-%d %H:%M:%S").replace(
                    tzinfo=ZoneInfo("America/New_York")
                )
            except ValueError:
                pass

        d_entry = ""
        if live_et and sim_et:
            d_entry = f"{(sim_et - live_et).total_seconds():.0f}"

        sim_buy = summ.get("buy_price") if summ else None
        d_buy = ""
        if sim_buy is not None:
            d_buy = f"{float(sim_buy) - live_buy:.4f}"

        sim_strike = summ.get("strike_int") if summ else None
        d_strike = ""
        if live_strike is not None and sim_strike is not None:
            d_strike = str(int(sim_strike) - int(live_strike))

        sim_spot = summ.get("btc_spot") if summ else None
        d_spot = ""
        # Market sim always joins ``btc_price_history`` for spot; ETH tickers still use BTC there.
        if ticker.upper().startswith("KXETH"):
            sim_spot = None
        elif live_open is not None and sim_spot is not None:
            d_spot = f"{float(sim_spot) - live_open:.2f}"

        def _fmt(x: Any) -> str:
            return "" if x is None else str(x)

        print(
            f"| {tid} | `{ticker}` | {_fmt(live_et)} | {_fmt(sim_et)} | {d_entry} | "
            f"{live_buy:.6f} | {_fmt(sim_buy)} | {d_buy} | {_fmt(live_strike)} | {_fmt(sim_strike)} | {d_strike} | "
            f"{_fmt(live_open)} | {_fmt(sim_spot)} | {d_spot} | {sim_ok} | {'; '.join(notes)} |"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
