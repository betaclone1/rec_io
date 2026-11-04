"""Wall-clock 15m tickers and Kalshi series registry (shared with sandbox feed test)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

# 15m series map. Crypto (BTC/ETH/SOL/XRP/DOGE) is assumed 24/7 — never gate REST
# on weekend dark hours. Commodities need an explicit cohort in COMMODITY_15M_*.
SERIES_15M_BY_SYMBOL: dict[str, str] = {
    "BTC": "KXBTC15M",
    "ETH": "KXETH15M",
    "SOL": "KXSOL15M",
    "XRP": "KXXRP15M",
    "DOGE": "KXDOGE15M",
    # Commodities: 15m series (orderbook when live_data_level=full; lean skips OB).
    "GOLD": "KXGOLD15M",
    "SILVER": "KXSILVER15M",
    "WTI": "KXWTI15M",
}

# ---------------------------------------------------------------------------
# Commodity 15m REST session gates (weekend dark hours)
#
# Crypto symbols are 24/7. Do not put crypto series in these sets;
# commodity_15m_rest_session_open() returns True for anything not listed.
#
# Operating assumption (as of 2026-10-31): the **most recent ~1 month** of
# Kalshi GET /markets close_time edges is the ongoing calendar. Recheck
# periodically (e.g. after a holiday week or when adding a series) by
# listing close_time gaps >=12h over several weekends.
#
# Evidence:
#   Metals (Oct 2026, 4 weekends): Fri 17:00 ET last close → Sun 18:30 first
#     close (dark ~49.5h). Sep 2026 GOLD/SILVER/COPPER used energy-style
#     Sat 00:00→Sun 18:15 instead — schedule can change; do not treat this
#     as eternal.
#   Energy (Sep–Oct 2026, 8 weekends): Sat 00:00 ET last close → Sun 18:15
#     first close (dark ~42.25h). Stable across the full lookback.
#   Neither cohort stays dark until Mon 09:00 — Sunday evening already lists.
#
# NEW TRACKED ASSETS: before enabling a non-crypto 15m series, back-check
# its weekend close_time edges and assign it to metals, energy, or a new
# cohort here. Do not assume metals/energy hours. Crypto → leave out of
# these sets (24/7).
# ---------------------------------------------------------------------------
COMMODITY_15M_METALS_SERIES = frozenset(
    {
        "KXGOLD15M",
        "KXSILVER15M",
        "KXPLATINUM15M",
        "KXPALLADIUM15M",
        "KXCOPPER15M",
    }
)
COMMODITY_15M_ENERGY_SERIES = frozenset(
    {"KXWTI15M", "KXNATGAS15M", "KXBRENT15M"}
)
COMMODITY_15M_SERIES = COMMODITY_15M_METALS_SERIES | COMMODITY_15M_ENERGY_SERIES
_COMMODITY_SESSION_RESUME_DOW = 6  # Sunday
_METALS_SESSION_END_DOW = 4  # Friday
_METALS_SESSION_END_HOUR = 17
# First Sunday metal close is :30 → open :15; energy first close :15 → open :00.
_METALS_SUN_RESUME_HOUR = 18
_METALS_SUN_RESUME_MINUTE = 15
_ENERGY_SUN_RESUME_HOUR = 18
_ENERGY_SUN_RESUME_MINUTE = 0
SERIES_HOURLY_BY_SYMBOL: dict[str, str] = {
    "BTC": "KXBTCD",
    "ETH": "KXETHD",
    "SOL": "KXSOLD",
    "DOGE": "KXDOGED",
}

def lean_market_symbols() -> frozenset[str]:
    """Symbols whose ``live_data_level`` is ``market`` (lean Kalshi feed, no orderbook)."""
    from backend.core.live_data_level import LEVEL_MARKET, symbols_at_levels

    return frozenset(symbols_at_levels(LEVEL_MARKET))


def is_lean_market_symbol(symbol: str) -> bool:
    """True when this symbol's live feed is the lean market package."""
    from backend.core.live_data_level import LEVEL_MARKET, level_of

    return level_of(symbol) == LEVEL_MARKET

EST = ZoneInfo("America/New_York")
MON_SHORT = (
    "JAN", "FEB", "MAR", "APR", "MAY", "JUN",
    "JUL", "AUG", "SEP", "OCT", "NOV", "DEC",
)


def is_commodity_15m_series(series_ticker: str) -> bool:
    return str(series_ticker or "").strip().upper() in COMMODITY_15M_SERIES


def commodity_15m_rest_session_open(
    series_ticker: str,
    now: Optional[datetime] = None,
) -> bool:
    """True when this commodity 15m series is expected to list live windows.

    Crypto / unknown series (not in ``COMMODITY_15M_SERIES``) are treated as
    24/7 and always return True. Outside a commodity session, callers should
    not hammer ``GET /markets`` — empty is normal, not a fetch failure.

    Metals and energy cohorts differ on Friday close. See module comments for
    evidence, recheck cadence, and the rule for new tracked assets.
    """
    series = str(series_ticker or "").strip().upper()
    if series not in COMMODITY_15M_SERIES:
        # Crypto and any series not yet classified: assume 24/7 (no dark gate).
        return True
    if now is None:
        now = datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    et = now.astimezone(EST)
    dow, hour, minute = et.weekday(), et.hour, et.minute
    energy = series in COMMODITY_15M_ENERGY_SERIES
    # Saturday always dark (energy's last Fri window closes Sat 00:00).
    if dow == 5:
        return False
    # Sunday resume (ET).
    if dow == _COMMODITY_SESSION_RESUME_DOW:
        if energy:
            if (hour, minute) < (_ENERGY_SUN_RESUME_HOUR, _ENERGY_SUN_RESUME_MINUTE):
                return False
        elif (hour, minute) < (_METALS_SUN_RESUME_HOUR, _METALS_SUN_RESUME_MINUTE):
            return False
    # Metals stop at Friday 17:00 ET close; energy runs through Friday night.
    if not energy:
        if dow == _METALS_SESSION_END_DOW and hour >= _METALS_SESSION_END_HOUR:
            return False
    return True


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


def clock_next_15m_ticker(symbol: str, now: float) -> str:
    """Upcoming 15m market ticker (current period end + 15m).

    Used to pre-subscribe the next cycle on the OB channel before it opens.
    """
    series = series_15m(symbol)
    end = est_15m_period_end(datetime.fromtimestamp(now, timezone.utc))
    next_end = end + timedelta(minutes=15)
    return ticker_for_15m_end(series, next_end)


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
