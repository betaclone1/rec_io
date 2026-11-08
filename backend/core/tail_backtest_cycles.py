"""Exact-cent LT/UT backtest cycle rows → historical_data.*_tail_backtest_cycles.

Backtest tape only (first $0.01 / $0.99 public print). Not the live OB monitor path.
Written by the hourly public_trades_drive_sync worker after catchup.
"""

from __future__ import annotations

import csv
import json
import logging
import os
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Optional, Sequence

from zoneinfo import ZoneInfo

from backend.core.kalshi_contract_settlement import kalshi_contract_settlement_end_est
from backend.core.market_watchdog.venues.kalshi.schedule import (
    commodity_15m_rest_session_open,
    is_commodity_15m_series,
    ticker_for_15m_end,
)

log = logging.getLogger("tail_backtest_cycles")

EST = ZoneInfo("America/New_York")

LT_LIMIT = 0.01
UT_LIMIT = 0.99

SERIES_TO_TABLE: dict[str, str] = {
    "KXBTC15M": "kxbtc15m_tail_backtest_cycles",
    "KXETH15M": "kxeth15m_tail_backtest_cycles",
    "KXSOL15M": "kxsol15m_tail_backtest_cycles",
    "KXXRP15M": "kxxrp15m_tail_backtest_cycles",
    "KXGOLD15M": "kxgold15m_tail_backtest_cycles",
    "KXSILVER15M": "kxsilver15m_tail_backtest_cycles",
    "KXWTI15M": "kxwti15m_tail_backtest_cycles",
}

CRYPTO_SERIES = frozenset(
    {"KXBTC15M", "KXETH15M", "KXSOL15M", "KXXRP15M", "KXDOGE15M"}
)

# Known Kalshi maintenance / venue dark windows (Eastern calendar dates).
# Extend as Kalshi publishes outages; days in this set are not flagged as data_gap.
KNOWN_MAINTENANCE_DAYS_ET: frozenset[date] = frozenset()

# Crypto day with fewer than this many public-trade rows → sparse gap (unless maintenance).
SPARSE_DAY_TRADE_FLOOR = 100

_REPO = Path(__file__).resolve().parents[2]
DEFAULT_TRADES_DIR = _REPO / "backend" / "data" / "historical_data" / "kalshi_public_trades"


@dataclass(frozen=True)
class TailFill:
    side: str  # yes | no
    fill_ts: datetime  # ET naive
    price: float


@dataclass
class CycleScore:
    ticker: str
    timestamp: datetime  # settlement end ET naive
    trading_day: date
    market_result: Optional[str]
    lt: Optional[TailFill]
    ut: Optional[TailFill]
    lt_win_loss: Optional[bool]
    ut_win_loss: Optional[bool]
    data_gap: bool = False
    data_gap_reason: Optional[str] = None


def table_for_series(series: str) -> str:
    key = str(series).strip().upper()
    if key not in SERIES_TO_TABLE:
        raise ValueError(f"unsupported series for tail_backtest_cycles: {series!r}")
    return SERIES_TO_TABLE[key]


def trades_dir() -> Path:
    raw = os.getenv("KALSHI_PUBLIC_TRADES_DIR", "").strip()
    return Path(raw) if raw else DEFAULT_TRADES_DIR


def load_market_result_cache(path: Optional[Path] = None) -> dict[str, Any]:
    p = path or (trades_dir() / ".cache_market_result_by_ticker.json")
    if not p.is_file():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        log.warning("market_result cache unreadable %s: %s", p, e)
        return {}
    return data if isinstance(data, dict) else {}


def market_result_for(cache: dict[str, Any], ticker: str) -> Optional[str]:
    v = cache.get(ticker)
    if isinstance(v, dict):
        mr = v.get("mr")
    else:
        mr = v
    if mr in ("yes", "no"):
        return str(mr)
    return None


def _parse_created_time_et_naive(raw: Any) -> Optional[datetime]:
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    try:
        if s.endswith("Z"):
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        else:
            dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        # Treat naive as already ET wall (rare); keep as-is.
        return dt.replace(microsecond=0)
    return dt.astimezone(EST).replace(tzinfo=None, microsecond=0)


def first_exact_touch(rows: Sequence[dict], limit: float) -> Optional[TailFill]:
    """First tape print at exact cent ``limit`` on yes or no; chronological."""
    L = round(float(limit), 2)
    ordered = sorted(
        rows,
        key=lambda r: (str(r.get("created_time") or ""), str(r.get("trade_id") or "")),
    )
    for r in ordered:
        try:
            y = round(float(r["yes_price_dollars"]), 2)
            n = round(float(r["no_price_dollars"]), 2)
        except (KeyError, TypeError, ValueError):
            continue
        side: Optional[str] = None
        price: Optional[float] = None
        if y == L:
            side, price = "yes", L
        elif n == L:
            side, price = "no", L
        if side is None or price is None:
            continue
        ts = _parse_created_time_et_naive(r.get("created_time"))
        if ts is None:
            continue
        return TailFill(side=side, fill_ts=ts, price=price)
    return None


def _win_loss(fill: Optional[TailFill], market_result: Optional[str]) -> Optional[bool]:
    if fill is None or market_result not in ("yes", "no"):
        return None
    return fill.side == market_result


def settlement_end_et_naive(ticker: str) -> Optional[datetime]:
    end = kalshi_contract_settlement_end_est(ticker)
    if end is None:
        return None
    return end.replace(tzinfo=None)


def expected_tickers_for_day(series: str, trading_day: date) -> list[str]:
    """Cycles expected to list that Eastern day (crypto 96; commodities session-gated)."""
    series_u = series.strip().upper()
    start_midnight = datetime(
        trading_day.year, trading_day.month, trading_day.day, 0, 0, tzinfo=EST
    )
    out: list[str] = []
    for i in range(96):
        end = start_midnight + timedelta(minutes=15 * i)
        if is_commodity_15m_series(series_u):
            open_t = end - timedelta(minutes=15)
            if not commodity_15m_rest_session_open(series_u, open_t):
                continue
        out.append(ticker_for_15m_end(series_u, end))
    return out


def _day_gap(
    series: str,
    trading_day: date,
    *,
    day_csv: Path,
    trade_row_count: int,
) -> tuple[bool, Optional[str]]:
    if series not in CRYPTO_SERIES:
        return False, None
    if trading_day in KNOWN_MAINTENANCE_DAYS_ET:
        return False, None
    if not day_csv.is_file() or day_csv.stat().st_size <= 0:
        return True, "missing_day_csv"
    if trade_row_count < SPARSE_DAY_TRADE_FLOOR:
        return True, "sparse_day_tape"
    return False, None


def score_day(
    series: str,
    trading_day: date,
    *,
    cache: Optional[dict[str, Any]] = None,
    root: Optional[Path] = None,
) -> list[CycleScore]:
    """Score every expected cycle for one Eastern day. Never omits an expected cycle."""
    series_u = series.strip().upper()
    root = root or trades_dir()
    cache = cache if cache is not None else load_market_result_cache(root / ".cache_market_result_by_ticker.json")
    day_csv = root / f"{series_u}_public_trades_{trading_day.isoformat()}_et.csv"

    by_ticker: dict[str, list[dict]] = {}
    trade_row_count = 0
    if day_csv.is_file() and day_csv.stat().st_size > 0:
        with day_csv.open(newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                t = (row.get("ticker") or "").strip()
                if not t:
                    continue
                by_ticker.setdefault(t, []).append(row)
                trade_row_count += 1

    gap, gap_reason = _day_gap(
        series_u, trading_day, day_csv=day_csv, trade_row_count=trade_row_count
    )

    scores: list[CycleScore] = []
    for ticker in expected_tickers_for_day(series_u, trading_day):
        ts = settlement_end_et_naive(ticker)
        if ts is None:
            continue
        rows = by_ticker.get(ticker) or []
        mr = market_result_for(cache, ticker)
        lt = first_exact_touch(rows, LT_LIMIT)
        ut = first_exact_touch(rows, UT_LIMIT)
        scores.append(
            CycleScore(
                ticker=ticker,
                timestamp=ts,
                trading_day=trading_day,
                market_result=mr,
                lt=lt,
                ut=ut,
                lt_win_loss=_win_loss(lt, mr),
                ut_win_loss=_win_loss(ut, mr),
                data_gap=gap,
                data_gap_reason=gap_reason if gap else None,
            )
        )
    return scores


def _upsert_sql(table: str) -> str:
    return f"""
        INSERT INTO historical_data.{table} (
            "timestamp", ticker, trading_day, market_result,
            lt_fill_ts, lt_side, lt_price, lt_win_loss,
            ut_fill_ts, ut_side, ut_price, ut_win_loss,
            data_gap, data_gap_reason, updated_at
        ) VALUES (
            %s, %s, %s, %s,
            %s, %s, %s, %s,
            %s, %s, %s, %s,
            %s, %s, CURRENT_TIMESTAMP
        )
        ON CONFLICT (ticker) DO UPDATE SET
            "timestamp" = EXCLUDED."timestamp",
            trading_day = EXCLUDED.trading_day,
            market_result = EXCLUDED.market_result,
            lt_fill_ts = EXCLUDED.lt_fill_ts,
            lt_side = EXCLUDED.lt_side,
            lt_price = EXCLUDED.lt_price,
            lt_win_loss = EXCLUDED.lt_win_loss,
            ut_fill_ts = EXCLUDED.ut_fill_ts,
            ut_side = EXCLUDED.ut_side,
            ut_price = EXCLUDED.ut_price,
            ut_win_loss = EXCLUDED.ut_win_loss,
            data_gap = EXCLUDED.data_gap,
            data_gap_reason = EXCLUDED.data_gap_reason,
            updated_at = CURRENT_TIMESTAMP
    """


def _row_params(s: CycleScore) -> tuple:
    return (
        s.timestamp,
        s.ticker,
        s.trading_day,
        s.market_result,
        s.lt.fill_ts if s.lt else None,
        s.lt.side if s.lt else None,
        s.lt.price if s.lt else None,
        s.lt_win_loss,
        s.ut.fill_ts if s.ut else None,
        s.ut.side if s.ut else None,
        s.ut.price if s.ut else None,
        s.ut_win_loss,
        s.data_gap,
        s.data_gap_reason,
    )


def upsert_scores(conn, series: str, scores: Sequence[CycleScore]) -> int:
    if not scores:
        return 0
    table = table_for_series(series)
    sql = _upsert_sql(table)
    params = [_row_params(s) for s in scores]
    with conn.cursor() as cur:
        cur.executemany(sql, params)
    conn.commit()
    return len(scores)


def discover_day_csvs(
    series: Sequence[str],
    *,
    root: Optional[Path] = None,
    start: Optional[date] = None,
    end: Optional[date] = None,
) -> list[tuple[str, date]]:
    """Return (series, day) pairs for non-empty day CSVs on disk."""
    root = root or trades_dir()
    out: list[tuple[str, date]] = []
    for ser in series:
        ser_u = str(ser).strip().upper()
        prefix = f"{ser_u}_public_trades_"
        for p in sorted(root.glob(f"{prefix}*_et.csv")):
            if p.stat().st_size <= 0:
                continue
            mid = p.name[len(prefix) : -len("_et.csv")]
            if len(mid) != 10:
                continue
            try:
                d = date.fromisoformat(mid)
            except ValueError:
                continue
            if start is not None and d < start:
                continue
            if end is not None and d > end:
                continue
            out.append((ser_u, d))
    return out


def score_and_upsert_range(
    series: Sequence[str],
    start: date,
    end: date,
    *,
    conn=None,
    root: Optional[Path] = None,
) -> tuple[int, list[str]]:
    """Score [start, end] inclusive for each series; upsert into PG. Returns (rows, failures)."""
    from backend.core.config.database import get_system_postgresql_connection

    own_conn = conn is None
    if own_conn:
        conn = get_system_postgresql_connection()
    root = root or trades_dir()
    cache = load_market_result_cache(root / ".cache_market_result_by_ticker.json")
    failed: list[str] = []
    total = 0
    try:
        for ser in series:
            ser_u = str(ser).strip().upper()
            try:
                table_for_series(ser_u)
            except ValueError as e:
                failed.append(str(e))
                continue
            d = start
            while d <= end:
                try:
                    scores = score_day(ser_u, d, cache=cache, root=root)
                    total += upsert_scores(conn, ser_u, scores)
                except Exception as e:
                    log.exception("score failed %s %s", ser_u, d)
                    failed.append(f"score:{ser_u}:{d.isoformat()}:{e}")
                d += timedelta(days=1)
    finally:
        if own_conn and conn is not None:
            conn.close()
    return total, failed


def score_lookback_for_sync(
    series: Sequence[str],
    *,
    lookback_days: int,
    root: Optional[Path] = None,
) -> tuple[int, list[str]]:
    today = datetime.now(EST).date()
    start = today - timedelta(days=max(0, lookback_days - 1))
    return score_and_upsert_range(series, start, today, root=root)
