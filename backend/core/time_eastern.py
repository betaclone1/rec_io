"""
US Eastern wall-clock helpers and PostgreSQL session timezone option.

All trading-domain "now" and "today" values should use this module so behavior
is independent of the host OS timezone.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Dict, Mapping, Optional
from zoneinfo import ZoneInfo

# Canonical IANA zone for Kalshi / US market conventions (avoid US/Eastern alias in code).
EST = ZoneInfo("America/New_York")

# psycopg2: pin session timezone so TIMESTAMP WITHOUT TIME ZONE and naive adapters match docs.
PG_SESSION_TIMEZONE_OPTIONS = "-c timezone=America/New_York"


def now_est() -> datetime:
    return datetime.now(EST)


def today_est() -> date:
    return now_est().date()


def eastern_wall_naive(dt: datetime) -> datetime:
    """US Eastern wall clock as timezone-naive (``historical_data`` timestamp convention).

    Aware datetimes are converted with :data:`EST`; naive values are returned unchanged
    (already treated as Eastern wall in the database layer).
    """
    if dt.tzinfo is None:
        return dt
    return dt.astimezone(EST).replace(tzinfo=None)


def timestamptz_wire_iso_et(dt: Any) -> Optional[str]:
    """ISO string with **America/New_York** offset for API clients (not host-local tz).

    ``TIMESTAMPTZ`` rows read via psycopg2 often use the client connection tz; naive values
    from legacy paths are treated as Eastern wall.
    """
    if dt is None:
        return None
    if isinstance(dt, str):
        return dt
    if not isinstance(dt, datetime):
        return str(dt)
    if dt.tzinfo is None:
        return dt.replace(tzinfo=EST).isoformat()
    return dt.astimezone(EST).isoformat()


def timestamptz_bind_utc(dt: datetime) -> datetime:
    """UTC-aware instant for ``TIMESTAMPTZ`` query parameters (psycopg2).

    Naive datetimes are treated as **US Eastern wall** (same as trade logs). Using an
    explicit offset avoids PostgreSQL interpreting naive values in the wrong session
    or client timezone (e.g. host set to Pacific).
    """
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=EST)
    else:
        dt = dt.astimezone(EST)
    return dt.astimezone(timezone.utc)


def merge_psycopg2_connect_kwargs(base: Mapping[str, Any]) -> Dict[str, Any]:
    """Return a copy of base suitable for psycopg2.connect, with Eastern session TZ.

    If ``options`` is already set, append the timezone directive (semicolon-separated).
    """
    out: Dict[str, Any] = dict(base)
    existing = (out.get("options") or "").strip()
    need = PG_SESSION_TIMEZONE_OPTIONS.strip()
    if "timezone=America/New_York" in existing:
        return out
    if not existing:
        out["options"] = need
    else:
        out["options"] = f"{existing}; {need}"
    return out


def utc_now_iso_z() -> str:
    """ISO-8601 UTC instant with Z suffix (wire / APIs).

    Uses real UTC, not Eastern.
    """
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
