"""Expiration symbol_close: CFB ring avg_60s at quarter-hour close (ISO UTC)."""

from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from backend.core.live_price_ring_90m import _utc_wall_str, avg_60s_at_quarter_close, utc_wall_to_est_wall

_EST = ZoneInfo("America/New_York")
_UTC = timezone.utc


def test_utc_wall_str_iso_z():
    dt = datetime(2026, 7, 25, 17, 30, 0, tzinfo=_UTC)
    assert _utc_wall_str(dt) == "2026-07-25T17:30:00.000Z"


def test_utc_wall_to_est_wall_dst():
    # 17:30 UTC in July = 13:30 America/New_York (EDT)
    assert utc_wall_to_est_wall("2026-07-25T17:30:00.000Z") == "2026-07-25T13:30:00"


def test_avg_60s_at_quarter_close_requires_symbol():
    assert avg_60s_at_quarter_close("", datetime(2026, 7, 25, 13, 30, tzinfo=_EST)) is None
