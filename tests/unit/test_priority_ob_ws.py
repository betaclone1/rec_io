"""Priority OB websocket split helpers."""

from __future__ import annotations

import pytest

from backend.core import orderbook_hot_publish_registry as reg
from backend.core.market_watchdog.venues.kalshi import ws_ingest as wi


def test_priority_ob_ws_enabled_default_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MARKET_WATCHDOG_PRIORITY_OB_WS", raising=False)
    assert wi.priority_ob_ws_enabled() is False
    monkeypatch.setenv("MARKET_WATCHDOG_PRIORITY_OB_WS", "1")
    assert wi.priority_ob_ws_enabled() is True


def test_priority_ob_isolated_thread_default_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("MARKET_WATCHDOG_PRIORITY_OB_ISOLATED_THREAD", raising=False)
    assert wi.priority_ob_isolated_thread_enabled() is False
    monkeypatch.setenv("MARKET_WATCHDOG_PRIORITY_OB_ISOLATED_THREAD", "1")
    assert wi.priority_ob_isolated_thread_enabled() is True


def test_priority_ob_tickers_armed_only_not_all_crypto(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MARKET_WATCHDOG_HOT_TICKER_FLUSH", "1")
    monkeypatch.setenv("MARKET_WATCHDOG_HOT_CRYPTO_15M", "1")
    monkeypatch.setenv("MARKET_WATCHDOG_PRIORITY_OB_ARMED_ONLY", "1")
    monkeypatch.setattr(
        reg,
        "refresh_hot_tickers_if_stale",
        lambda force=False: None,
    )
    monkeypatch.setattr(reg, "_ut_watched", {"KXBTC15M-26NOV022300-00"})
    monkeypatch.setattr(reg, "_watched", None)
    monkeypatch.setattr(reg, "_allowlist", set())

    want = {
        "KXBTC15M-26NOV022300-00",
        "KXETH15M-26NOV022300-00",
        "KXGOLD15M-26NOV022300-00",
    }
    got = wi._priority_ob_tickers(want)
    assert got == {"KXBTC15M-26NOV022300-00"}


def test_priority_ob_tickers_legacy_all_hot_crypto(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MARKET_WATCHDOG_HOT_TICKER_FLUSH", "1")
    monkeypatch.setenv("MARKET_WATCHDOG_HOT_CRYPTO_15M", "1")
    monkeypatch.setenv("MARKET_WATCHDOG_PRIORITY_OB_ARMED_ONLY", "0")
    want = {
        "KXBTC15M-26NOV022300-00",
        "KXETH15M-26NOV022300-00",
        "KXGOLD15M-26NOV022300-00",
    }
    got = wi._priority_ob_tickers(want)
    assert got == {
        "KXBTC15M-26NOV022300-00",
        "KXETH15M-26NOV022300-00",
    }


def test_consume_ob_channel_seq_separate_cursors() -> None:
    master = wi.KalshiMarketWsMaster(cfg=None, symbols=["BTC"])  # type: ignore[arg-type]
    assert wi._consume_ob_channel_seq(master, 1, hot=False)[0] == "apply"
    assert wi._consume_ob_channel_seq(master, 1, hot=True)[0] == "apply"
    assert master.ob_channel_last_seq == 1
    assert master.hot_ob_channel_last_seq == 1
    assert wi._consume_ob_channel_seq(master, 1, hot=False)[0] == "drop"
    assert wi._consume_ob_channel_seq(master, 2, hot=True)[0] == "apply"
    assert master.hot_ob_channel_last_seq == 2
    assert master.ob_channel_last_seq == 1


def test_priority_markets_use_separate_ob_lock() -> None:
    master = wi.KalshiMarketWsMaster(cfg=None, symbols=["BTC"])  # type: ignore[arg-type]
    master.hot_ob_ws_connected = True
    master.hot_ob_ws_markets = {"KXBTC15M-26NOV022300-00"}
    assert wi._lock_for_ob_ticker(master, "KXBTC15M-26NOV022300-00") is master.hot_ob_lock
    assert wi._lock_for_ob_ticker(master, "KXGOLD15M-26NOV022300-00") is master.lock
