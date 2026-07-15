"""Wall-clock 15m tickers and Kalshi series registry (shared with sandbox feed test)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

SERIES_15M_BY_SYMBOL: dict[str, str] = {
    "BTC": "KXBTC15M",
    "ETH": "KXETH15M",
    "SOL": "KXSOL15M",
    "XRP": "KXXRP15M",
    "DOGE": "KXDOGE15M",
}
SERIES_HOURLY_BY_SYMBOL: dict[str, str] = {
    "BTC": "KXBTCD",
    "ETH": "KXETHD",
    "SOL": "KXSOLD",
    "DOGE": "KXDOGED",
}

EST = ZoneInfo("America/New_York")
MON_SHORT = (
    "JAN", "FEB", "MAR", "APR", "MAY", "JUN",
    "JUL", "AUG", "SEP", "OCT", "NOV", "DEC",
)


def series_15m(symbol: str) -> str:
    return SERIES_15M_BY_SYMBOL[symbol.upper()]


def series_hourly(symbol: str) -> Optional[str]:
    return SERIES_HOURLY_BY_SYMBOL.get(symbol.upper())


def est_15m_period_end(now: datetime) -> datetime:
    est = now.astimezone(EST).replace(second=0, microsecond=0)
    slot_end_min = ((est.minute // 15) + 1) * 15
    if slot_end_min >= 60:
        return est.replace(minute=0) + timedelta(hours=1)
    return est.replace(minute=slot_end_min)


def ticker_for_15m_end(series: str, end: datetime) -> str:
    end_e = end.astimezone(EST)
    yy, mon = end_e.year % 100, MON_SHORT[end_e.month - 1]
    mid = f"{yy:02d}{mon}{end_e.day:02d}{end_e.hour:02d}{end_e.minute:02d}"
    return f"{series}-{mid}-{end_e.minute:02d}"


def clock_current_15m_ticker(symbol: str, now: float) -> str:
    series = series_15m(symbol)
    end = est_15m_period_end(datetime.fromtimestamp(now, timezone.utc))
    return ticker_for_15m_end(series, end)


def clock_previous_15m_ticker(symbol: str, now: float) -> str:
    series = series_15m(symbol)
    end = est_15m_period_end(datetime.fromtimestamp(now, timezone.utc))
    prev_end = end - timedelta(minutes=15)
    return ticker_for_15m_end(series, prev_end)


def on_15m_rollover_boundary(now: float) -> bool:
    est = datetime.fromtimestamp(now, timezone.utc).astimezone(EST)
    return est.minute % 15 == 0 and est.second < 12


def rollover_boundary_key(now: float) -> str:
    est = datetime.fromtimestamp(now, timezone.utc).astimezone(EST)
    return f"{est.year:04d}{est.month:02d}{est.day:02d}{est.hour:02d}{est.minute // 15:02d}"


def on_hour_boundary(now: float) -> bool:
    est = datetime.fromtimestamp(now, timezone.utc).astimezone(EST)
    return est.minute == 0 and est.second < 30


def hour_boundary_key(now: float) -> str:
    est = datetime.fromtimestamp(now, timezone.utc).astimezone(EST)
    return f"{est.year:04d}{est.month:02d}{est.day:02d}{est.hour:02d}"


def hourly_event_ticker_for_clock(symbol: str, now: float) -> Optional[str]:
    series = series_hourly(symbol)
    if not series:
        return None
    est = datetime.fromtimestamp(now, timezone.utc).astimezone(EST)
    upcoming = est + timedelta(hours=1)
    return (
        f"{series}-{upcoming.strftime('%y')}{upcoming.strftime('%b').upper()}"
        f"{upcoming.strftime('%d')}{upcoming.strftime('%H')}"
    )
