#!/usr/bin/env python3
"""
Full-history backfill: public-trades day CSVs → ``*_tail_backtest_cycles`` → rolling 7/30/90.

Scores **one ticker at a time** (day CSVs are ticker-contiguous; never loads a full
day tape into RAM). Default is a single process writing upserts as each ticker
is scored. Optional ``--workers`` runs multiple day files in parallel — keep it
low; each worker still only holds one ticker's rows.

Scoring rule (same as charts / live-vs-BT checks): first public print with yes or no
≤ $0.01 (LT) or ≥ $0.99 (UT); W/L vs ``market_result``. After this seeds history,
hourly ``public_trades_drive_sync`` only re-scores the recent lookback (default 2
calendar days).

Example:
  PYTHONPATH=$(pwd) .venv/bin/python scripts/backtest/backfill_tail_backtest_tables.py
  PYTHONPATH=$(pwd) .venv/bin/python scripts/backtest/backfill_tail_backtest_tables.py \\
    --series KXBTC15M --start 2026-09-01 --end 2026-11-07 --workers 2
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import date
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [backfill_tail] %(message)s",
    force=True,
)
log = logging.getLogger("backfill_tail")

DEFAULT_SERIES = (
    "KXBTC15M",
    "KXETH15M",
    "KXSOL15M",
    "KXXRP15M",
    "KXGOLD15M",
    "KXSILVER15M",
    "KXWTI15M",
)


def _score_one(args: tuple[str, str, str]) -> tuple[str, str, list[tuple], str | None]:
    """Worker: stream one day file ticker-by-ticker; return upsert params."""
    series, day_iso, root_s = args
    from datetime import date as date_cls

    from backend.core.tail_backtest_cycles import (
        _row_params,
        iter_score_day,
        load_market_result_cache,
        trades_dir,
    )

    root = Path(root_s) if root_s else trades_dir()
    day = date_cls.fromisoformat(day_iso)
    try:
        cache = load_market_result_cache(root / ".cache_market_result_by_ticker.json")
        params = [
            _row_params(s)
            for s in iter_score_day(series, day, cache=cache, root=root)
        ]
        return series, day_iso, params, None
    except Exception as e:
        return series, day_iso, [], f"{type(e).__name__}: {e}"


def _upsert_day(conn, series: str, params: list[tuple]) -> int:
    from backend.core.tail_backtest_cycles import _upsert_sql, table_for_series

    if not params:
        return 0
    sql = _upsert_sql(table_for_series(series))
    # One ticker row per execute — tiny; avoids holding giant executemany batches.
    with conn.cursor() as cur:
        for row in params:
            cur.execute(sql, row)
    conn.commit()
    return len(params)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--series", nargs="+", default=list(DEFAULT_SERIES))
    ap.add_argument("--start", default="")
    ap.add_argument("--end", default="")
    ap.add_argument(
        "--workers",
        type=int,
        default=1,
        help="Parallel day files (default 1). Each worker still scores one ticker at a time.",
    )
    ap.add_argument(
        "--skip-cycles",
        action="store_true",
        help="Only rebuild rolling rates from existing cycle rows",
    )
    ap.add_argument(
        "--skip-rolling",
        action="store_true",
        help="Only upsert cycle rows",
    )
    ap.add_argument(
        "--force",
        action="store_true",
        help="Re-score days that already have rows in the cycle table (default: skip them)",
    )
    args = ap.parse_args()

    from backend.core.config.database import get_system_postgresql_connection
    from backend.core.tail_backtest_cycles import (
        discover_day_csvs,
        table_for_series,
        trades_dir,
    )
    from backend.core.tail_backtest_rolling_rates import backfill_rolling_rates_all_history

    series = [s.strip().upper() for s in args.series if s.strip()]
    start = date.fromisoformat(args.start) if args.start else None
    end = date.fromisoformat(args.end) if args.end else None
    root = trades_dir()
    jobs = discover_day_csvs(series, root=root, start=start, end=end)
    workers = max(1, int(args.workers))

    skipped_existing = 0
    if not args.skip_cycles and not args.force:
        conn_chk = get_system_postgresql_connection()
        if conn_chk is None:
            log.error("DB connect failed; cannot check existing days")
            return 1
        try:
            existing: dict[str, set[str]] = {}
            with conn_chk.cursor() as cur:
                for ser in series:
                    cur.execute(
                        f"SELECT DISTINCT trading_day::text "
                        f"FROM historical_data.{table_for_series(ser)}"
                    )
                    existing[ser] = {r[0] for r in cur.fetchall()}
            kept = []
            for ser, d in jobs:
                if d.isoformat() in existing.get(ser, ()):
                    skipped_existing += 1
                else:
                    kept.append((ser, d))
            jobs = kept
        finally:
            conn_chk.close()

    log.info(
        "backfill start series=%s jobs=%s skipped_existing=%s workers=%s "
        "root=%s skip_cycles=%s skip_rolling=%s force=%s",
        series,
        len(jobs),
        skipped_existing,
        workers,
        root,
        args.skip_cycles,
        args.skip_rolling,
        args.force,
    )

    total_rows = 0
    failed: list[str] = []
    t0 = time.time()

    if not args.skip_cycles:
        if not jobs:
            log.info("no missing cycle days; nothing to score")
        work = [(ser, d.isoformat(), str(root)) for ser, d in jobs]
        conn = get_system_postgresql_connection()
        if conn is None:
            log.error("DB connect failed")
            return 1
        try:
            done = 0
            if not work:
                pass
            elif workers == 1:
                for w in work:
                    ser, day_iso, params, err = _score_one(w)
                    done += 1
                    if err:
                        failed.append(f"score:{ser}:{day_iso}:{err}")
                        log.warning("FAIL %s %s %s", ser, day_iso, err)
                        continue
                    n = _upsert_day(conn, ser, params)
                    total_rows += n
                    if done % 10 == 0 or done == len(work):
                        log.info(
                            "progress %s/%s rows=%s last=%s %s",
                            done,
                            len(work),
                            total_rows,
                            ser,
                            day_iso,
                        )
            else:
                with ProcessPoolExecutor(max_workers=workers) as pool:
                    futs = {pool.submit(_score_one, w): w for w in work}
                    for fut in as_completed(futs):
                        ser, day_iso, params, err = fut.result()
                        done += 1
                        if err:
                            failed.append(f"score:{ser}:{day_iso}:{err}")
                            log.warning("FAIL %s %s %s", ser, day_iso, err)
                            continue
                        n = _upsert_day(conn, ser, params)
                        total_rows += n
                        if done % 10 == 0 or done == len(work):
                            log.info(
                                "progress %s/%s rows=%s last=%s %s",
                                done,
                                len(work),
                                total_rows,
                                ser,
                                day_iso,
                            )
        finally:
            conn.close()
        log.info(
            "cycles done rows=%s failed=%s elapsed=%.1fs",
            total_rows,
            len(failed),
            time.time() - t0,
        )

    rolling_n = 0
    if not args.skip_rolling:
        rolling_n, roll_failed = backfill_rolling_rates_all_history(series)
        failed.extend(roll_failed)
        log.info("rolling done upserts=%s failed=%s", rolling_n, len(roll_failed))

    log.info(
        "DONE cycle_rows=%s rolling_upserts=%s failures=%s elapsed=%.1fs",
        total_rows,
        rolling_n,
        len(failed),
        time.time() - t0,
    )
    if failed:
        for f in failed[:20]:
            log.warning("failure: %s", f)
        if len(failed) > 20:
            log.warning("... %s more failures", len(failed) - 20)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
