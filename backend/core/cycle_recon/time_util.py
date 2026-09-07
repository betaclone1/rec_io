from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional, Tuple
from zoneinfo import ZoneInfo

_UTC = timezone.utc
_ET = ZoneInfo("America/New_York")


def parse_utc(raw: Any) -> datetime:
    if isinstance(raw, datetime):
        dt = raw
    else:
        s = str(raw or "").strip().replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        return dt.replace(tzinfo=_UTC)
    return dt.astimezone(_UTC)


def to_iso_z(dt: datetime) -> str:
    return dt.astimezone(_UTC).isoformat().replace("+00:00", "Z")


def to_et_display(dt: datetime) -> str:
    return dt.astimezone(_ET).strftime("%Y-%m-%d %H:%M:%S %Z")


def et_wall_naive(dt: datetime) -> datetime:
    return dt.astimezone(_ET).replace(tzinfo=None)


def combine_trade_log_open_utc(date_s: str, time_s: str, created_at: Optional[str] = None) -> datetime:
    """
    Prefer created_at (timestamptz) when present; else interpret date+time as US/Eastern wall.
    """
    if created_at not in (None, ""):
        return parse_utc(created_at)
    d = str(date_s).strip()
    t = str(time_s).strip()
    # HH:MM:SS
    naive = datetime.fromisoformat(f"{d}T{t}")
    return naive.replace(tzinfo=_ET).astimezone(_UTC)


def combine_trade_log_close_utc(
    date_s: str,
    closed_at: Optional[str],
    updated_at: Optional[str] = None,
) -> Optional[datetime]:
    if closed_at in (None, ""):
        if updated_at not in (None, ""):
            return parse_utc(updated_at)
        return None
    ca = str(closed_at).strip()
    # Often Eastern wall clock HH:MM:SS without date
    if "T" in ca or "+" in ca or ca.endswith("Z"):
        return parse_utc(ca)
    if len(ca) <= 8 and ":" in ca:
        naive = datetime.fromisoformat(f"{str(date_s).strip()}T{ca}")
        return naive.replace(tzinfo=_ET).astimezone(_UTC)
    return parse_utc(ca)


def seconds_between(a: datetime, b: datetime) -> float:
    return (b.astimezone(_UTC) - a.astimezone(_UTC)).total_seconds()


def floor_second(dt: datetime) -> datetime:
    return dt.astimezone(_UTC).replace(microsecond=0)


def parse_et_wall(raw: Any) -> datetime:
    """
    Parse an Eastern wall-time string from the UI into aware UTC.

    Accepts:
      - ``YYYY-MM-DD``
      - ``YYYY-MM-DD HH:MM`` / ``YYYY-MM-DD HH:MM:SS``
      - ``YYYY-MM-DDTHH:MM(:SS)`` (no zone → Eastern)
      - ISO with explicit offset / Z (honored as absolute, then returned as UTC)
    """
    if isinstance(raw, datetime):
        dt = raw
        if dt.tzinfo is None:
            return dt.replace(tzinfo=_ET).astimezone(_UTC)
        return dt.astimezone(_UTC)
    s = str(raw or "").strip()
    if not s:
        raise ValueError("empty Eastern timestamp")
    if s.endswith("Z") or "+" in s[10:] or (s.count("-") > 2 and "T" in s):
        # Likely absolute ISO; still allow Z/+offset
        try:
            return parse_utc(s)
        except Exception:
            pass
    s = s.replace("T", " ")
    if len(s) == 10:
        s = s + " 00:00:00"
    elif len(s) == 16:
        s = s + ":00"
    naive = datetime.fromisoformat(s)
    return naive.replace(tzinfo=_ET).astimezone(_UTC)


def et_date_str(dt: datetime) -> str:
    return dt.astimezone(_ET).strftime("%Y-%m-%d")


def et_datetime_input_value(dt: datetime) -> str:
    """Value suitable for ``<input type="datetime-local">`` in Eastern."""
    return dt.astimezone(_ET).strftime("%Y-%m-%dT%H:%M")


def range_preset_et_bounds(preset: str, *, now: Optional[datetime] = None) -> Tuple[Optional[datetime], Optional[datetime]]:
    """
    Return (start_utc, end_utc) for UI presets.
    ``all`` → (None, None).
    """
    from datetime import timedelta

    p = str(preset or "").strip().lower()
    end = (now or datetime.now(_UTC)).astimezone(_UTC)
    if p in ("", "all"):
        return None, None
    if p in ("24h", "1d", "prev_24h"):
        return end - timedelta(hours=24), end
    if p in ("7d", "prev_7d"):
        return end - timedelta(days=7), end
    if p in ("30d", "prev_30d"):
        return end - timedelta(days=30), end
    raise ValueError(f"unknown range preset: {preset!r}")

