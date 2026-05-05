#!/usr/bin/env python3
"""One-off: rolling W% for users_0001.trades_simulated_0001 (run on prod)."""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

from dotenv import load_dotenv

load_dotenv(".env")

import numpy as np
import psycopg2
from backend.core.config.database import get_database_config

T = "users_0001.trades_simulated_0001"


def is_win(wl) -> float:
    if wl is None:
        return 0.0
    return 1.0 if str(wl).strip().upper() == "W" else 0.0


def summarize_roll(label: str, roll_pct: np.ndarray) -> None:
    if roll_pct.size == 0:
        print(f"  {label}: (no samples)")
        return
    print(
        f"  {label}: n={roll_pct.size} mean={roll_pct.mean():.2f}% "
        f"min={roll_pct.min():.2f}% p25={np.percentile(roll_pct, 25):.2f}% "
        f"p50={np.percentile(roll_pct, 50):.2f}% p75={np.percentile(roll_pct, 75):.2f}% "
        f"max={roll_pct.max():.2f}%"
    )


def main():
    conn = psycopg2.connect(**get_database_config())
    cur = conn.cursor()

    cur.execute(
        f"""
        SELECT win_loss, COUNT(*) FROM {T}
        WHERE status = %s AND win_loss IS NOT NULL
        GROUP BY win_loss ORDER BY 2 DESC
        """,
        ("closed",),
    )
    print("win_loss distribution:", cur.fetchall())

    cur.execute(
        f"""
        SELECT MIN(date), MAX(date), COUNT(*) FROM {T}
        WHERE status = %s AND win_loss IS NOT NULL
        """,
        ("closed",),
    )
    print("closed+wl range:", cur.fetchone())

    cur.execute(
        f"""
        SELECT date::date AS d,
               COUNT(*) AS n,
               SUM(CASE WHEN UPPER(TRIM(COALESCE(win_loss, ''))) = 'W' THEN 1 ELSE 0 END) AS wins
        FROM {T}
        WHERE status = 'closed' AND win_loss IS NOT NULL
          AND date >= '2026-03-01' AND date < '2026-04-22'
        GROUP BY date::date
        ORDER BY d
        """
    )
    print("\n=== DAILY ===")
    print("date\tn_trades\twins\twin_pct")
    for d, n, w in cur.fetchall():
        pct = 100.0 * w / n if n else 0
        print(f"{d}\t{n}\t{w}\t{pct:.2f}")

    cur.execute(
        f"""
        SELECT id, date, time, closed_at, created_at, win_loss
        FROM {T}
        WHERE status = 'closed' AND win_loss IS NOT NULL
          AND date >= '2026-03-01' AND date < '2026-04-22'
        ORDER BY created_at NULLS LAST, date::text, time::text, id
        """
    )
    rows = cur.fetchall()
    dates = np.array([str(r[1]) for r in rows])
    wins = np.array([is_win(r[5]) for r in rows])
    n = len(wins)
    print(f"\n=== ORDERED CHAIN n={n} overall_win_pct={100*wins.mean():.2f}% ===")

    pre = dates < "2026-03-29"
    stress = (dates >= "2026-03-29") & (dates < "2026-04-07")
    post = dates >= "2026-04-07"
    lastw = dates >= "2026-04-13"

    for window in (25, 50, 100, 200):
        if n < window:
            continue
        roll_mean = np.convolve(wins, np.ones(window), mode="valid") / window
        roll_pct = 100.0 * roll_mean
        end_dates = dates[window - 1 :]
        print(f"\n--- rolling window = {window} trades (endpoint date labels) ---")
        summarize_roll("pre_329 (end<2026-03-29)", roll_pct[end_dates < "2026-03-29"])
        summarize_roll("stress_329_407 (end in [29 Mar, 7 Apr))", roll_pct[(end_dates >= "2026-03-29") & (end_dates < "2026-04-07")])
        summarize_roll("post_407 (end>=2026-04-07)", roll_pct[end_dates >= "2026-04-07"])
        summarize_roll("last_week_413 (end>=2026-04-13)", roll_pct[end_dates >= "2026-04-13"])

    # Excerpt: rolling 50 around stress
    window = 50
    if n >= window:
        roll50 = np.convolve(wins, np.ones(window), mode="valid")
        print(f"\n=== roll50 excerpt (end date 2026-03-25 .. 2026-04-10) ===")
        for i in range(len(roll50)):
            end_d = dates[i + window - 1]
            if end_d < "2026-03-25" or end_d > "2026-04-10":
                continue
            if i % 200 != 0 and end_d not in (
                "2026-03-28",
                "2026-03-29",
                "2026-03-30",
                "2026-04-01",
                "2026-04-04",
                "2026-04-07",
            ):
                continue
            print(
                f"  end_idx={i+window-1} end_date={end_d} "
                f"wins_in_last50={roll50[i]:.0f} pct={100*roll50[i]/window:.1f}%"
            )

    conn.close()


if __name__ == "__main__":
    main()
