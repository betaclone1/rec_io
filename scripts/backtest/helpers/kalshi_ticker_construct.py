"""
Construct Kalshi crypto **15m** market tickers for an Eastern **trading calendar day**.

Aligns with ``trade.date`` / ``today_est()`` semantics: ``YYYY-MM-DD`` is the US Eastern
**calendar date** (``backend.core.time_eastern.EST``), same convention as trade history filters.

Ticker shape matches ``kalshi_contract_settlement_end_est`` in ``backend/active_trade_supervisor.py``:
``{SERIES}-{YY}{MMM}{DD}{HHMM}-{MM}`` where ``HHMM`` is the **period end** (settlement instant)
in Eastern wall time and the trailing ``MM`` is ``00``, ``15``, ``30``, or ``45``.

A full Eastern day has **96** fifteen-minute settlement endpoints: ``00:00`` through ``23:45``
inclusive, stepping by 15 minutes.

**Hourly / daily** contracts (e.g. ``KXBTCD-...-T...``) encode strike in the ticker; this module
does **not** synthesize those (use explicit tickers or API discovery).
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

EST = ZoneInfo("America/New_York")

MON_SHORT = (
    "JAN",
    "FEB",
    "MAR",
    "APR",
    "MAY",
    "JUN",
    "JUL",
    "AUG",
    "SEP",
    "OCT",
    "NOV",
    "DEC",
)

_SERIES_SAFE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_\-]*$")


def validate_kalshi_series_for_15m_synth(series_ticker: str) -> str:
    raw = series_ticker.strip()
    if not raw or not _SERIES_SAFE.fullmatch(raw):
        raise ValueError(f"invalid series ticker: {series_ticker!r}")
    st = raw.upper()
    if "15M" not in st:
        raise ValueError(
            f"synthetic 15m tickers require a series containing '15M' (e.g. KXETH15M); got {st!r}"
        )
    return st


def kalshi_15m_market_tickers_for_eastern_date(series_ticker: str, trading_day: date) -> list[str]:
    """
    Return **96** market tickers for ``trading_day`` (inclusive Eastern calendar day).

    Ordered by settlement end time ascending (``00:00`` … ``23:45`` Eastern).
    """
    st = validate_kalshi_series_for_15m_synth(series_ticker)
    if trading_day.year < 2000 or trading_day.year > 2100:
        raise ValueError(f"trading_day out of range: {trading_day!r}")

    start_midnight = datetime(
        trading_day.year, trading_day.month, trading_day.day, 0, 0, tzinfo=EST
    )
    out: list[str] = []
    for i in range(96):
        end = start_midnight + timedelta(minutes=15 * i)
        yy = end.year % 100
        mon = MON_SHORT[end.month - 1]
        dd = end.day
        hh = end.hour
        minute = end.minute
        mid = f"{yy:02d}{mon}{dd:02d}{hh:02d}{minute:02d}"
        suffix = f"{minute:02d}"
        out.append(f"{st}-{mid}-{suffix}")
    return out


def parse_eastern_trading_day_arg(s: str) -> date:
    """``YYYY-MM-DD`` calendar date (Eastern label; no timezone on :class:`date`)."""
    parts = s.strip().split("-")
    if len(parts) != 3:
        raise ValueError(f"expected YYYY-MM-DD, got {s!r}")
    y, m, d = int(parts[0]), int(parts[1]), int(parts[2])
    return date(y, m, d)


def kalshi_15m_market_tickers_for_eastern_date_range(
    series_ticker: str, start_day: date, end_day: date
) -> list[str]:
    """
    Concatenate **96** tickers per Eastern calendar day from ``start_day`` through ``end_day``
    inclusive (``end_day >= start_day``). Order: chronological by day, then by settlement time.
    """
    if end_day < start_day:
        raise ValueError(f"end_day {end_day} must be >= start_day {start_day}")
    out: list[str] = []
    d = start_day
    one = timedelta(days=1)
    while d <= end_day:
        out.extend(kalshi_15m_market_tickers_for_eastern_date(series_ticker, d))
        d += one
    return out
