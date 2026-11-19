"""Maintain exact-cent LT/UT cycle rows, rolling rates, and symbols_list scores.

Separate from public-trades Drive archiving. This path may lightly refresh
day CSVs + market-result cache for the lookback window, then score into Postgres.
It never packages month tar.xz or uploads to Drive.
"""

from __future__ import annotations

import logging
import os
from datetime import timedelta
from typing import Optional, Sequence

log = logging.getLogger("tail_backtest_score_sync")

DEFAULT_SERIES: tuple[str, ...] = (
    "KXBTC15M",
    "KXETH15M",
    "KXSOL15M",
    "KXXRP15M",
    "KXGOLD15M",
    "KXSILVER15M",
    "KXWTI15M",
)


def _env_first(*names: str, default: str = "") -> str:
    for name in names:
        raw = os.getenv(name)
        if raw is not None and str(raw).strip() != "":
            return str(raw).strip()
    return default


def sync_enabled() -> bool:
    raw = _env_first("TAIL_BACKTEST_SCORE_SYNC", default="1").lower()
    return raw not in ("0", "false", "no", "off")


def interval_sec() -> float:
    try:
        return max(60.0, float(_env_first("TAIL_BACKTEST_SCORE_SYNC_INTERVAL_SEC", default="900")))
    except (TypeError, ValueError):
        return 900.0


def lookback_days() -> int:
    try:
        return max(1, int(_env_first("TAIL_BACKTEST_SCORE_SYNC_LOOKBACK_DAYS", default="2")))
    except (TypeError, ValueError):
        return 2


def pull_workers() -> int:
    try:
        return max(1, min(2, int(_env_first("TAIL_BACKTEST_SCORE_SYNC_WORKERS", default="1"))))
    except (TypeError, ValueError):
        return 1


def series_list(override: Optional[Sequence[str]] = None) -> list[str]:
    if override:
        return [str(s).strip().upper() for s in override if str(s).strip()]
    raw = _env_first("TAIL_BACKTEST_SCORE_SYNC_SERIES", default="")
    if raw:
        return [p.strip().upper() for p in raw.split(",") if p.strip()]
    return list(DEFAULT_SERIES)


def _refresh_lookback_tape(
    series: Sequence[str],
    *,
    lookback: int,
    workers: int,
) -> list[str]:
    """Pull/refresh day CSVs for lookback only — no package/upload."""
    from backend.core.public_trades_drive_sync import (
        TRADES_DIR,
        day_csv_incomplete,
        day_csv_path,
        et_today,
        pull_day,
    )

    TRADES_DIR.mkdir(parents=True, exist_ok=True)
    today = et_today()
    start = today - timedelta(days=max(0, lookback - 1))
    failed: list[str] = []
    for ser in series:
        d = start
        while d <= today:
            path = day_csv_path(ser, d)
            exists = path.is_file()
            truncated = exists and day_csv_incomplete(path, d, today=today)
            if not exists or truncated or d >= today - timedelta(days=1):
                if truncated:
                    log.warning(
                        "day CSV truncated — force re-pull %s %s",
                        ser,
                        d.isoformat(),
                    )
                rc = pull_day(ser, d, force=True, workers=workers)
                if rc != 0:
                    failed.append(f"trades:{ser}:{d.isoformat()}:rc={rc}")
            d += timedelta(days=1)
    return failed


def _refresh_lookback_results(series: Sequence[str], lookback: int) -> list[str]:
    """Refresh market-result cache for months touched by the lookback window."""
    from backend.core.public_trades_drive_sync import et_today, refresh_market_results

    today = et_today()
    start = today - timedelta(days=max(0, lookback - 1))
    months: set[tuple[int, int]] = {(today.year, today.month)}
    d = start
    while d <= today:
        months.add((d.year, d.month))
        d += timedelta(days=1)
    failed: list[str] = []
    for ser in series:
        failed.extend(refresh_market_results(ser, months))
    return failed


def run_once(
    *,
    series: Optional[Sequence[str]] = None,
    lookback: Optional[int] = None,
    workers: Optional[int] = None,
    skip_trades: bool = False,
    skip_results: bool = False,
) -> int:
    """
    One wake: optional light tape/results refresh → cycle upsert → rolling → symbols_list scores.
    """
    from backend.core.public_trades_drive_sync import TRADES_DIR
    from backend.core.tail_backtest_cycles import score_lookback_for_sync
    from backend.core.tail_backtest_rolling_rates import refresh_rolling_rates_after_score

    ser = series_list(series)
    lb = lookback if lookback is not None else lookback_days()
    wk = workers if workers is not None else pull_workers()
    failed: list[str] = []

    log.info(
        "wake start series=%s lookback=%s workers=%s skip_trades=%s skip_results=%s",
        ser,
        lb,
        wk,
        skip_trades,
        skip_results,
    )

    if not skip_trades:
        failed.extend(_refresh_lookback_tape(ser, lookback=lb, workers=wk))
    if not skip_results:
        failed.extend(_refresh_lookback_results(ser, lb))

    scored = 0
    rolling = 0
    try:
        scored, score_failed = score_lookback_for_sync(
            ser, lookback_days=lb, root=TRADES_DIR
        )
        failed.extend(score_failed)
        log.info("tail_backtest_cycles upserted=%s", scored)
    except Exception as e:
        log.exception("tail_backtest_cycles scoring failed")
        failed.append(f"score:fatal:{e}")

    try:
        rolling, roll_failed = refresh_rolling_rates_after_score(
            ser, lookback_days=max(lb, 1)
        )
        failed.extend(roll_failed)
        log.info("tail_backtest_rolling_rates upserted=%s", rolling)
    except Exception as e:
        log.exception("tail_backtest_rolling_rates refresh failed")
        failed.append(f"rolling:fatal:{e}")

    if failed:
        log.warning("failures=%s", failed)
    log.info(
        "wake done scored=%s rolling=%s failures=%s",
        scored,
        rolling,
        len(failed),
    )
    return 1 if failed else 0
