"""Commodity 15m REST session window (weekend dark hours)."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from backend.core.market_watchdog.venues.kalshi.schedule import (
    commodity_15m_rest_session_open,
    is_commodity_15m_series,
)

ET = ZoneInfo("America/New_York")


def _et(y, m, d, hh, mm=0):
    return datetime(y, m, d, hh, mm, tzinfo=ET)


def test_series_membership():
    assert is_commodity_15m_series("KXGOLD15M")
    assert is_commodity_15m_series("kxwti15m")
    assert not is_commodity_15m_series("KXBTC15M")


def test_metals_dark_fri_evening_through_sun_afternoon():
    # Friday 16:59 still open; 17:00 dark (API last Fri close 17:00).
    assert commodity_15m_rest_session_open("KXGOLD15M", _et(2026, 10, 30, 16, 59))
    assert not commodity_15m_rest_session_open("KXGOLD15M", _et(2026, 10, 30, 17, 0))
    assert not commodity_15m_rest_session_open("KXSILVER15M", _et(2026, 10, 31, 12, 0))
    assert not commodity_15m_rest_session_open("KXCOPPER15M", _et(2026, 10, 31, 12, 0))
    # Sunday: metals first close 18:30 → resume 18:15.
    assert not commodity_15m_rest_session_open("KXGOLD15M", _et(2026, 11, 1, 18, 14))
    assert commodity_15m_rest_session_open("KXGOLD15M", _et(2026, 11, 1, 18, 15))


def test_wti_continues_friday_evening_but_saturday_dark():
    assert commodity_15m_rest_session_open("KXWTI15M", _et(2026, 10, 30, 21, 0))
    assert commodity_15m_rest_session_open("KXNATGAS15M", _et(2026, 10, 30, 23, 30))
    assert not commodity_15m_rest_session_open("KXWTI15M", _et(2026, 10, 31, 10, 0))
    # Energy first Sunday close 18:15 → resume 18:00.
    assert not commodity_15m_rest_session_open("KXWTI15M", _et(2026, 11, 1, 17, 59))
    assert commodity_15m_rest_session_open("KXWTI15M", _et(2026, 11, 1, 18, 0))


def test_crypto_always_open_24_7():
    # Crypto is not in COMMODITY_15M_*; Saturday noon is still "open" for REST.
    assert commodity_15m_rest_session_open("KXBTC15M", _et(2026, 10, 31, 12, 0))
    assert commodity_15m_rest_session_open("KXETH15M", _et(2026, 10, 31, 12, 0))
    assert commodity_15m_rest_session_open("KXSOL15M", _et(2026, 10, 31, 12, 0))
    assert commodity_15m_rest_session_open("KXXRP15M", _et(2026, 10, 31, 12, 0))


def test_fetch_skips_rest_when_commodity_session_dark(monkeypatch):
    from backend.core import lower_tail_open as lto

    monkeypatch.setattr(lto, "_markets_cache", {})
    monkeypatch.setattr(lto, "_session_skip_logged", set())
    calls = {"n": 0}

    def _get(*a, **k):
        calls["n"] += 1
        raise AssertionError("REST should not run in commodity dark session")

    monkeypatch.setattr(lto.requests, "get", _get)
    # Saturday noon ET
    monkeypatch.setattr(
        lto,
        "commodity_15m_rest_session_open",
        lambda series, now=None: False,
    )
    monkeypatch.setattr(lto, "is_commodity_15m_series", lambda s: True)
    out = lto.fetch_series_15m_markets("KXGOLD15M")
    assert out == []
    assert calls["n"] == 0
    # Second call uses empty cache — still no REST.
    out2 = lto.fetch_series_15m_markets("KXGOLD15M")
    assert out2 == []
    assert calls["n"] == 0


def test_fetch_caches_empty_success(monkeypatch):
    from backend.core import lower_tail_open as lto

    monkeypatch.setattr(lto, "_markets_cache", {})
    monkeypatch.setattr(lto, "_session_skip_logged", set())
    monkeypatch.setattr(lto, "is_commodity_15m_series", lambda s: False)
    calls = {"n": 0}

    class _Resp:
        def raise_for_status(self):
            return None

        def json(self):
            return {"markets": []}

    def _get(*a, **k):
        calls["n"] += 1
        return _Resp()

    monkeypatch.setattr(lto.requests, "get", _get)
    assert lto.fetch_series_15m_markets("KXBTC15M") == []
    assert calls["n"] == 1
    assert lto.fetch_series_15m_markets("KXBTC15M") == []
    assert calls["n"] == 1  # empty cached
