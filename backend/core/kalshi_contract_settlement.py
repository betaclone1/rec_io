"""Kalshi crypto contract settlement instants parsed from tickers (America/New_York)."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

_KALSHI_MID_15M_SETTLE = re.compile(
    r"^(\d{2})(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)(\d{2})(\d{4})$",
    re.I,
)
_KALSHI_MID_HOURLY_D_START = re.compile(
    r"^(\d{2})(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)(\d{2})(\d{2})$",
    re.I,
)
_KALSHI_MONTH = {
    "JAN": 1,
    "FEB": 2,
    "MAR": 3,
    "APR": 4,
    "MAY": 5,
    "JUN": 6,
    "JUL": 7,
    "AUG": 8,
    "SEP": 9,
    "OCT": 10,
    "NOV": 11,
    "DEC": 12,
}


def kalshi_contract_settlement_end_est(market_ticker: Optional[str]) -> Optional[datetime]:
    """
    Best-effort settlement wall time (America/New_York) encoded in Kalshi crypto tickers.

    - 15m (e.g. KXBTC15M-26MAR251015-45): middle token is YY MMM DD HHMM = period end.
    - Daily hourly (e.g. KXBTCD-26MAR2519-T69999.99): middle token is YY MMM DD HH (or HHMM in the
      15m-shaped tail); that clock is the contract settlement wall time in America/New_York
      (matches UI copy like "7pm" and trade_manager's reading of the ticker).

    Returns None if the ticker does not match a known pattern (caller should not suppress).
    """
    if not market_ticker or "-" not in market_ticker:
        return None
    parts = market_ticker.split("-")
    if len(parts) < 2:
        return None
    series = parts[0].upper()
    mid = parts[1].upper()
    est = ZoneInfo("America/New_York")
    if "15M" in series:
        m = _KALSHI_MID_15M_SETTLE.match(mid)
        if not m:
            return None
        yy = int(m.group(1))
        mon = m.group(2).upper()
        dd = int(m.group(3))
        hhmm = m.group(4)
        month = _KALSHI_MONTH.get(mon)
        if not month:
            return None
        year = 2000 + yy
        hour = int(hhmm[:2])
        minute = int(hhmm[2:])
        return datetime(year, month, dd, hour, minute, tzinfo=est)
    if re.match(r"^KX[A-Z0-9]+D$", series):
        m = _KALSHI_MID_HOURLY_D_START.match(mid)
        if m:
            yy = int(m.group(1))
            mon = m.group(2).upper()
            dd = int(m.group(3))
            hh = int(m.group(4))
            month = _KALSHI_MONTH.get(mon)
            if not month:
                return None
            year = 2000 + yy
            return datetime(year, month, dd, hh, 0, tzinfo=est)
        # Some hourly events use the same YYMMMDDHHMM token shape as 15m (minute often 00).
        m2 = _KALSHI_MID_15M_SETTLE.match(mid)
        if m2:
            yy = int(m2.group(1))
            mon = m2.group(2).upper()
            dd = int(m2.group(3))
            hhmm = m2.group(4)
            month = _KALSHI_MONTH.get(mon)
            if not month:
                return None
            year = 2000 + yy
            hour = int(hhmm[:2])
            minute = int(hhmm[2:])
            return datetime(year, month, dd, hour, minute, tzinfo=est)
        return None
    return None
