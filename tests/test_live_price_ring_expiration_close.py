"""symbol_close from the CFB ring: quarter-hour close at expiration, as-of for early closes."""

from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import backend.core.config.database as db_module
from backend.core.live_price_ring_90m import (
    _utc_wall_str,
    avg_60s_as_of,
    avg_60s_at_quarter_close,
    utc_wall_to_est_wall,
)

_EST = ZoneInfo("America/New_York")
_UTC = timezone.utc


class _FakeCursor:
    def __init__(self, row, calls):
        self._row = row
        self._calls = calls

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        self._calls.append((" ".join(sql.split()), params))

    def fetchone(self):
        return self._row


class _FakeConn:
    def __init__(self, row, calls):
        self._row = row
        self._calls = calls
        self.closed = False

    def cursor(self):
        return _FakeCursor(self._row, self._calls)

    def close(self):
        self.closed = True


def _patch_ring_conn(monkeypatch, row):
    calls = []
    conns = []

    def _factory():
        conn = _FakeConn(row, calls)
        conns.append(conn)
        return conn

    monkeypatch.setattr(db_module, "get_system_postgresql_connection", _factory)
    monkeypatch.delenv("CFBENCHMARKS_RING_PG", raising=False)
    return calls, conns


def test_utc_wall_str_iso_z():
    dt = datetime(2026, 7, 25, 17, 30, 0, tzinfo=_UTC)
    assert _utc_wall_str(dt) == "2026-07-25T17:30:00.000Z"


def test_utc_wall_to_est_wall_dst():
    # 17:30 UTC in July = 13:30 America/New_York (EDT)
    assert utc_wall_to_est_wall("2026-07-25T17:30:00.000Z") == "2026-07-25T13:30:00"


def test_is_quarter_close_ring_timestamp():
    from backend.core.live_price_ring_90m import is_quarter_close_ring_timestamp

    assert is_quarter_close_ring_timestamp("2026-07-28T19:45:00.000Z")
    assert is_quarter_close_ring_timestamp("2026-07-28T17:00:00.000Z")
    assert not is_quarter_close_ring_timestamp("2026-07-28T19:45:01.000Z")
    assert not is_quarter_close_ring_timestamp("2026-07-28T19:44:00.000Z")


def test_avg_60s_at_quarter_close_requires_symbol():
    assert avg_60s_at_quarter_close("", datetime(2026, 7, 25, 13, 30, tzinfo=_EST)) is None


def test_avg_60s_as_of_guards():
    when = datetime(2026, 7, 25, 13, 37, 42, tzinfo=_EST)
    assert avg_60s_as_of("", when) is None
    assert avg_60s_as_of("NOPE", when) is None
    assert avg_60s_as_of("BTC", None) is None


def test_avg_60s_as_of_returns_newest_tick_in_window(monkeypatch):
    calls, conns = _patch_ring_conn(monkeypatch, (63421.55,))

    # 13:37:42 EDT == 17:37:42 UTC
    got = avg_60s_as_of("BTC", datetime(2026, 7, 25, 13, 37, 42, tzinfo=_EST))

    assert got == 63421.55
    sql, params = calls[0]
    assert "live_data.live_price_ring_90m_btc" in sql
    assert "avg_60s IS NOT NULL" in sql
    assert "ORDER BY timestamp DESC" in sql
    # Bounded window ending at the close instant, newest tick first.
    assert params == ("2026-07-25T17:37:42.000Z", "2026-07-25T17:37:27.000Z")
    assert conns[0].closed is True


def test_avg_60s_as_of_lookback_is_configurable(monkeypatch):
    calls, _ = _patch_ring_conn(monkeypatch, (1.0,))

    avg_60s_as_of(
        "ETH",
        datetime(2026, 7, 25, 13, 37, 42, tzinfo=_EST),
        max_lookback_seconds=3,
    )

    _, params = calls[0]
    assert params == ("2026-07-25T17:37:42.000Z", "2026-07-25T17:37:39.000Z")


def test_avg_60s_as_of_empty_window_is_none(monkeypatch):
    _patch_ring_conn(monkeypatch, None)

    assert avg_60s_as_of("BTC", datetime(2026, 7, 25, 13, 37, 42, tzinfo=_EST)) is None


def test_avg_60s_as_of_naive_when_is_est(monkeypatch):
    calls, _ = _patch_ring_conn(monkeypatch, (5.0,))

    avg_60s_as_of("SOL", datetime(2026, 7, 25, 13, 37, 42))

    _, params = calls[0]
    assert params[0] == "2026-07-25T17:37:42.000Z"


def test_avg_60s_as_of_disabled_ring(monkeypatch):
    _patch_ring_conn(monkeypatch, (1.0,))
    monkeypatch.setenv("CFBENCHMARKS_RING_PG", "0")

    assert avg_60s_as_of("BTC", datetime(2026, 7, 25, 13, 37, 42, tzinfo=_EST)) is None
