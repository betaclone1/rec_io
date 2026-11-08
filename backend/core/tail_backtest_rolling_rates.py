"""7/30/90 trading-day LT/UT rolling win rates from cycle tables.

Refreshed by the hourly public_trades_drive_sync wake after cycle upserts.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Optional, Sequence
from zoneinfo import ZoneInfo

from backend.core.tail_backtest_cycles import (
    SERIES_TO_TABLE,
    expected_tickers_for_day,
    table_for_series,
)

log = logging.getLogger("tail_backtest_rolling_rates")

EST = ZoneInfo("America/New_York")
ROLLING_WINDOWS: tuple[int, ...] = (7, 30, 90)


@dataclass(frozen=True)
class TailWindowStats:
    cycles: int
    filled: int
    scored: int
    wins: int

    @property
    def win_rate(self) -> Optional[float]:
        if self.scored <= 0:
            return None
        return self.wins / self.scored

    @property
    def participation(self) -> Optional[float]:
        if self.cycles <= 0:
            return None
        return self.filled / self.cycles


@dataclass(frozen=True)
class RollingRateRow:
    series: str
    as_of_trading_day: date
    window_trading_days: int
    lt: TailWindowStats
    ut: TailWindowStats
    trading_days_in_window: int
    trading_days_with_rows: int


def is_trading_day(series: str, day: date) -> bool:
    """Crypto: every calendar day. Commodities: any expected session cycle that day."""
    return bool(expected_tickers_for_day(series, day))


def trading_days_ending(series: str, as_of: date, n: int) -> list[date]:
    """Last ``n`` trading days ending at ``as_of`` (inclusive), chronological."""
    if n <= 0:
        return []
    out: list[date] = []
    d = as_of
    # Commodities need extra calendar span for weekend dark hours.
    guard_limit = max(n * 5, n + 14)
    guard = 0
    while len(out) < n and guard < guard_limit:
        if is_trading_day(series, d):
            out.append(d)
        d -= timedelta(days=1)
        guard += 1
    out.reverse()
    return out


def _empty_stats() -> TailWindowStats:
    return TailWindowStats(cycles=0, filled=0, scored=0, wins=0)


def _aggregate_side(
    rows: Sequence[tuple[Optional[str], Optional[bool]]],
) -> TailWindowStats:
    """rows: (fill_side, win_loss) per cycle."""
    cycles = len(rows)
    filled = scored = wins = 0
    for fill_side, win_loss in rows:
        if fill_side is not None:
            filled += 1
        if win_loss is None:
            continue
        scored += 1
        if win_loss:
            wins += 1
    return TailWindowStats(cycles=cycles, filled=filled, scored=scored, wins=wins)


def compute_rolling_rate(
    conn,
    series: str,
    as_of: date,
    window_trading_days: int,
) -> RollingRateRow:
    series_u = series.strip().upper()
    table = table_for_series(series_u)
    days = trading_days_ending(series_u, as_of, window_trading_days)
    if not days:
        empty = _empty_stats()
        return RollingRateRow(
            series=series_u,
            as_of_trading_day=as_of,
            window_trading_days=window_trading_days,
            lt=empty,
            ut=empty,
            trading_days_in_window=0,
            trading_days_with_rows=0,
        )

    sql = f"""
        SELECT trading_day, lt_side, lt_win_loss, ut_side, ut_win_loss
        FROM historical_data.{table}
        WHERE trading_day = ANY(%s)
    """
    with conn.cursor() as cur:
        cur.execute(sql, (days,))
        fetched = cur.fetchall()

    days_with_rows = {r[0] for r in fetched if r[0] is not None}
    lt_pairs = [(r[1], r[2]) for r in fetched]
    ut_pairs = [(r[3], r[4]) for r in fetched]
    return RollingRateRow(
        series=series_u,
        as_of_trading_day=as_of,
        window_trading_days=window_trading_days,
        lt=_aggregate_side(lt_pairs),
        ut=_aggregate_side(ut_pairs),
        trading_days_in_window=len(days),
        trading_days_with_rows=len(days_with_rows),
    )


def _upsert_sql() -> str:
    return """
        INSERT INTO historical_data.tail_backtest_rolling_rates (
            series, as_of_trading_day, window_trading_days,
            lt_cycles, lt_filled, lt_scored, lt_wins, lt_win_rate, lt_participation,
            ut_cycles, ut_filled, ut_scored, ut_wins, ut_win_rate, ut_participation,
            trading_days_in_window, trading_days_with_rows, updated_at
        ) VALUES (
            %s, %s, %s,
            %s, %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s, %s,
            %s, %s, CURRENT_TIMESTAMP
        )
        ON CONFLICT (series, as_of_trading_day, window_trading_days) DO UPDATE SET
            lt_cycles = EXCLUDED.lt_cycles,
            lt_filled = EXCLUDED.lt_filled,
            lt_scored = EXCLUDED.lt_scored,
            lt_wins = EXCLUDED.lt_wins,
            lt_win_rate = EXCLUDED.lt_win_rate,
            lt_participation = EXCLUDED.lt_participation,
            ut_cycles = EXCLUDED.ut_cycles,
            ut_filled = EXCLUDED.ut_filled,
            ut_scored = EXCLUDED.ut_scored,
            ut_wins = EXCLUDED.ut_wins,
            ut_win_rate = EXCLUDED.ut_win_rate,
            ut_participation = EXCLUDED.ut_participation,
            trading_days_in_window = EXCLUDED.trading_days_in_window,
            trading_days_with_rows = EXCLUDED.trading_days_with_rows,
            updated_at = CURRENT_TIMESTAMP
    """


def _params(row: RollingRateRow) -> tuple:
    return (
        row.series,
        row.as_of_trading_day,
        row.window_trading_days,
        row.lt.cycles,
        row.lt.filled,
        row.lt.scored,
        row.lt.wins,
        row.lt.win_rate,
        row.lt.participation,
        row.ut.cycles,
        row.ut.filled,
        row.ut.scored,
        row.ut.wins,
        row.ut.win_rate,
        row.ut.participation,
        row.trading_days_in_window,
        row.trading_days_with_rows,
    )


def upsert_rolling_rates(conn, rows: Sequence[RollingRateRow]) -> int:
    if not rows:
        return 0
    sql = _upsert_sql()
    params = [_params(row) for row in rows]
    with conn.cursor() as cur:
        cur.executemany(sql, params)
    conn.commit()
    return len(rows)


@dataclass(frozen=True)
class _DayAgg:
    cycles: int = 0
    lt_filled: int = 0
    lt_scored: int = 0
    lt_wins: int = 0
    ut_filled: int = 0
    ut_scored: int = 0
    ut_wins: int = 0


def load_daily_aggregates(conn, series: str) -> dict[date, _DayAgg]:
    """One pass over the cycle table → per trading_day fill/score/win counts."""
    table = table_for_series(series)
    sql = f"""
        SELECT trading_day,
               count(*)::int,
               count(lt_side)::int,
               count(lt_win_loss)::int,
               count(*) FILTER (WHERE lt_win_loss IS TRUE)::int,
               count(ut_side)::int,
               count(ut_win_loss)::int,
               count(*) FILTER (WHERE ut_win_loss IS TRUE)::int
        FROM historical_data.{table}
        GROUP BY trading_day
        ORDER BY trading_day
    """
    out: dict[date, _DayAgg] = {}
    with conn.cursor() as cur:
        cur.execute(sql)
        for row in cur.fetchall():
            out[row[0]] = _DayAgg(
                cycles=int(row[1]),
                lt_filled=int(row[2]),
                lt_scored=int(row[3]),
                lt_wins=int(row[4]),
                ut_filled=int(row[5]),
                ut_scored=int(row[6]),
                ut_wins=int(row[7]),
            )
    return out


def _stats_from_days(aggs: dict[date, _DayAgg], days: Sequence[date]) -> tuple[TailWindowStats, TailWindowStats, int]:
    lt_c = lt_f = lt_s = lt_w = 0
    ut_c = ut_f = ut_s = ut_w = 0
    with_rows = 0
    for d in days:
        a = aggs.get(d)
        if a is None:
            continue
        with_rows += 1
        lt_c += a.cycles
        lt_f += a.lt_filled
        lt_s += a.lt_scored
        lt_w += a.lt_wins
        ut_c += a.cycles
        ut_f += a.ut_filled
        ut_s += a.ut_scored
        ut_w += a.ut_wins
    return (
        TailWindowStats(cycles=lt_c, filled=lt_f, scored=lt_s, wins=lt_w),
        TailWindowStats(cycles=ut_c, filled=ut_f, scored=ut_s, wins=ut_w),
        with_rows,
    )


def refresh_rolling_rates_for_series(
    conn,
    series: str,
    as_of_days: Sequence[date],
    *,
    windows: Sequence[int] = ROLLING_WINDOWS,
    daily: Optional[dict[date, _DayAgg]] = None,
) -> int:
    """Recompute and upsert all windows for each as_of day."""
    series_u = series.strip().upper()
    aggs = daily if daily is not None else load_daily_aggregates(conn, series_u)
    rows: list[RollingRateRow] = []
    for as_of in as_of_days:
        for w in windows:
            days = trading_days_ending(series_u, as_of, int(w))
            lt, ut, with_rows = _stats_from_days(aggs, days)
            rows.append(
                RollingRateRow(
                    series=series_u,
                    as_of_trading_day=as_of,
                    window_trading_days=int(w),
                    lt=lt,
                    ut=ut,
                    trading_days_in_window=len(days),
                    trading_days_with_rows=with_rows,
                )
            )
    return upsert_rolling_rates(conn, rows)


def backfill_rolling_rates_all_history(
    series: Sequence[str],
) -> tuple[int, list[str]]:
    """Rebuild 7/30/90 snapshots for every trading day that has cycle rows (plus gaps in between)."""
    from backend.core.config.database import get_system_postgresql_connection

    failed: list[str] = []
    total = 0
    conn = get_system_postgresql_connection()
    try:
        for ser in series:
            ser_u = str(ser).strip().upper()
            if ser_u not in SERIES_TO_TABLE:
                failed.append(f"rolling:unsupported:{ser_u}")
                continue
            try:
                daily = load_daily_aggregates(conn, ser_u)
                if not daily:
                    continue
                d_min = min(daily)
                d_max = max(daily)
                as_ofs: list[date] = []
                d = d_min
                while d <= d_max:
                    if is_trading_day(ser_u, d):
                        as_ofs.append(d)
                    d += timedelta(days=1)
                total += refresh_rolling_rates_for_series(
                    conn, ser_u, as_ofs, daily=daily
                )
            except Exception as e:
                log.exception("rolling backfill failed %s", ser_u)
                failed.append(f"rolling:{ser_u}:{e}")
    finally:
        conn.close()
    return total, failed


def refresh_rolling_rates_after_score(
    series: Sequence[str],
    *,
    lookback_days: int = 1,
    as_of: Optional[date] = None,
) -> tuple[int, list[str]]:
    """
    Refresh rolling snapshots for each series.

    Upserts windows for every trading day from (as_of - lookback) through as_of
    so hourly wakes keep the current day current and recent history intact.
    """
    from backend.core.config.database import get_system_postgresql_connection

    today = as_of or datetime.now(EST).date()
    start = today - timedelta(days=max(0, lookback_days - 1))
    failed: list[str] = []
    total = 0
    conn = get_system_postgresql_connection()
    try:
        for ser in series:
            ser_u = str(ser).strip().upper()
            if ser_u not in SERIES_TO_TABLE:
                failed.append(f"rolling:unsupported:{ser_u}")
                continue
            as_ofs: list[date] = []
            d = start
            while d <= today:
                if is_trading_day(ser_u, d):
                    as_ofs.append(d)
                d += timedelta(days=1)
            if not as_ofs:
                as_ofs = [today]
            try:
                total += refresh_rolling_rates_for_series(conn, ser_u, as_ofs)
            except Exception as e:
                log.exception("rolling refresh failed %s", ser_u)
                failed.append(f"rolling:{ser_u}:{e}")
    finally:
        conn.close()
    return total, failed
