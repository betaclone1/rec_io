"""symbols_list.live_data_level is the feed-depth switch."""

from __future__ import annotations

from backend.core import live_data_level as lvl
from backend.core.market_watchdog.venues.kalshi.schedule import is_lean_market_symbol


def _install(monkeypatch, rows):
    monkeypatch.setattr(lvl, "_has_snapshot", False)
    monkeypatch.setattr(lvl, "_loaded_mono", 0.0)
    monkeypatch.setattr(lvl, "_order", ())
    monkeypatch.setattr(lvl, "_levels", {})
    monkeypatch.setattr(lvl, "_load_from_db", lambda: rows)


def test_level_of_and_groups(monkeypatch):
    _install(
        monkeypatch,
        (
            ("BTC", "ETH", "SOL", "GOLD"),
            {"BTC": "full", "ETH": "full", "SOL": "none", "GOLD": "market"},
        ),
    )
    assert lvl.level_of("btc") == "full"
    assert lvl.level_of("SOL") == "none"
    assert lvl.level_of("MISSING") == "none"
    assert lvl.full_package_symbols() == ("BTC", "ETH")
    assert lvl.market_feed_symbols() == ("BTC", "ETH", "GOLD")
    assert lvl.price_feed_symbols() == ("BTC", "ETH", "GOLD")
    assert is_lean_market_symbol("GOLD") is True
    assert is_lean_market_symbol("BTC") is False
    assert is_lean_market_symbol("SOL") is False


def test_unknown_level_is_none(monkeypatch):
    _install(monkeypatch, (("ZZZ",), {"ZZZ": "nope"}))
    # Loader normalizes unknown before cache. Simulate that here.
    monkeypatch.setattr(
        lvl,
        "_load_from_db",
        lambda: (("ZZZ",), {"ZZZ": "none"}),
    )
    assert lvl.level_of("ZZZ") == "none"


def test_refresh_failure_keeps_last_snapshot(monkeypatch):
    _install(
        monkeypatch,
        (("BTC",), {"BTC": "full"}),
    )
    assert lvl.level_of("BTC") == "full"

    def _boom():
        raise RuntimeError("db down")

    monkeypatch.setattr(lvl, "_load_from_db", _boom)
    monkeypatch.setattr(lvl, "_loaded_mono", 0.0)
    assert lvl.level_of("BTC") == "full"
