"""Expiration symbol_close: CFB ring 60s window average."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from backend.core.live_price_ring_90m import _est_wall_str, expiration_symbol_close_window_sec

_EST = ZoneInfo("America/New_York")


def test_expiration_window_default_60():
    assert expiration_symbol_close_window_sec() == 60


def test_est_wall_str_format():
    dt = datetime(2026, 6, 4, 16, 0, 0, tzinfo=_EST)
    assert _est_wall_str(dt) == "2026-06-04T16:00:00"
