#!/usr/bin/env python3
"""
Full-history backfill: public-trades day CSVs → cycle tables → rolling 7/30/90 rates.

Uses a process pool for day scoring (local / catchup). Hourly prod wake only
maintains the recent lookback after this has seeded history.

Example:
  PYTHONPATH=$(pwd) .venv/bin/python scripts/backtest/backfill_tail_backtest_tables.py \\
    --workers 8
  PYTHONPATH=$(pwd) .venv/bin/python scripts/backtest/backfill_tail_backtest_tables.py \\
    --series KXBTC15M --start 2026-09-01 --end 2026-11-07 --workers 4
"""

from __future__ import annotations

import argparse
import logging
import os
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
    """Worker: score one (series, day). Returns params for upsert."""
    series, day_iso, root_s = args
    from datetime import date as date_cls

    from backend.core.tail_backtest_cycles import (
        _row_params,
        load_market_result_cache,
        score_day,
        trades_dir,
    )

    root = Path(root_s) if root_s else trades_dir()
    day = date_cls.fromisoformat(day_iso)
    try:
        cache = load_market_result_cache(root / ".cache_market_result_by_ticker.json")
        scores = score_day(series, day, cache=cache, root=root)
        return series, day_iso, [_row_params(s) for s in scores], None
    except Exception as e:
        return series, day_iso, [], f"{type(e).__name__}: {e}"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--series", nargs="+", default=list(DEFAULT_SERIES))
    ap.add_argument("--start", default="")
    ap.add_argument("--end", default="")
    ap.add_argument("--workers", type=int, default=max(4, (os.cpu_count() or 4)))
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
    args = ap.parse_args()

    from backend.core.config.database import get_system_postgresql_connection
    from backend.core.tail_backtest_cycles import (
        discover_day_csvs,
        table_for_series,
        trades_dir,
        _upsert_sql,
    )
    from backend.core.tail_backtest_rolling_rates import backfill_rolling_rates_all_history

    series = [s.strip().upper() for s in args.series if s.strip()]
    start = date.fromisoformat(args.start) if args.start else None
    end = date.fromisoformat(args.end) if args.end else None
    root = trades_dir()
    jobs = discover_day_csvs(series, root=root, start=start, end=end)
    log.info(
        "backfill start series=%s jobs=%s workers=%s root=%s skip_cycles=%s skip_rolling=%s",
        series,
        len(jobs),
        args.workers,
        root,
        args.skip_cycles,
        args.skip_rolling,
    )

    total_rows = 0
    failed: list[str] = []
    t0 = time.time()

    if not args.skip_cycles:
        work = [(ser, d.isoformat(), str(root)) for ser, d in jobs]
        conn = get_system_postgresql_connection()
        try:
            done = 0
            with ProcessPoolExecutor(max_workers=max(1, int(args.workers))) as pool:
                futs = {pool.submit(_score_one, w): w for w in work}
                for fut in as_completed(futs):
                    ser, day_iso, params, err = fut.result()
                    done += 1
                    if err:
                        failed.append(f"score:{ser}:{day_iso}:{err}")
                        log.warning("FAIL %s %s %s", ser, day_iso, err)
                        continue
                    if not params:
                        if done % 50 == 0 or done == len(work):
                            log.info("progress %s/%s rows=%s", done, len(work), total_rows)
                        continue
                    sql = _upsert_sql(table_for_series(ser))
                    with conn.cursor() as cur:
                        cur.executemany(sql, params)
                    conn.commit()
                    total_rows += len(params)
                    if done % 25 == 0 or done == len(work):
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
