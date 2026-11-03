"""Priority OB websocket split helpers — same-loop safe design."""

from __future__ import annotations

import pytest

from backend.core import orderbook_hot_publish_registry as reg
from backend.core.market_watchdog.venues.kalshi import ws_ingest as wi


def test_priority_ob_ws_enabled_default_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MARKET_WATCHDOG_PRIORITY_OB_WS", raising=False)
    assert wi.priority_ob_ws_enabled() is True
    monkeypatch.setenv("MARKET_WATCHDOG_PRIORITY_OB_WS", "0")
    assert wi.priority_ob_ws_enabled() is False


def test_priority_ob_isolated_thread_always_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("MARKET_WATCHDOG_PRIORITY_OB_ISOLATED_THREAD", raising=False)
    assert wi.priority_ob_isolated_thread_enabled() is False
    monkeypatch.setenv("MARKET_WATCHDOG_PRIORITY_OB_ISOLATED_THREAD", "1")
    # Hard-disabled after production outage — env cannot re-enable.
    assert wi.priority_ob_isolated_thread_enabled() is False


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


def test_want_main_ob_keeps_priority_until_ready(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MARKET_WATCHDOG_PRIORITY_OB_WS", "1")
    master = wi.KalshiMarketWsMaster(cfg=None, symbols=["BTC"])  # type: ignore[arg-type]
    want = {
        "KXBTC15M-26NOV022300-00",
        "KXGOLD15M-26NOV022300-00",
    }
    master.hot_ob_ws_connected = True
    master.hot_ob_ws_markets = {"KXBTC15M-26NOV022300-00"}
    master.hot_ob_ready_markets = set()
    # Not ready yet → still on main (no feed gap).
    assert wi._want_main_ob_markets(master, want) == want

    master.hot_ob_ready_markets = {"KXBTC15M-26NOV022300-00"}
    # Ready on priority → drop from main.
    assert wi._want_main_ob_markets(master, want) == {"KXGOLD15M-26NOV022300-00"}


def test_want_main_ob_all_on_main_when_priority_down(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MARKET_WATCHDOG_PRIORITY_OB_WS", "1")
    master = wi.KalshiMarketWsMaster(cfg=None, symbols=["BTC"])  # type: ignore[arg-type]
    want = {"KXBTC15M-26NOV022300-00", "KXGOLD15M-26NOV022300-00"}
    master.hot_ob_ws_connected = False
    master.hot_ob_ready_markets = {"KXBTC15M-26NOV022300-00"}
    assert wi._want_main_ob_markets(master, want) == want


def test_want_main_ob_all_on_main_when_priority_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MARKET_WATCHDOG_PRIORITY_OB_WS", "0")
    master = wi.KalshiMarketWsMaster(cfg=None, symbols=["BTC"])  # type: ignore[arg-type]
    want = {"KXBTC15M-26NOV022300-00"}
    master.hot_ob_ws_connected = True
    master.hot_ob_ready_markets = {"KXBTC15M-26NOV022300-00"}
    assert wi._want_main_ob_markets(master, want) == want


def test_spawn_priority_ob_binds_same_loop_no_thread(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Startup must create_task on the running loop — never Thread/new_event_loop."""
    import asyncio

    monkeypatch.setenv("MARKET_WATCHDOG_PRIORITY_OB_WS", "1")
    monkeypatch.setenv("MARKET_WATCHDOG_PRIORITY_OB_ISOLATED_THREAD", "1")

    async def _run() -> None:
        master = wi.KalshiMarketWsMaster(cfg=None, symbols=["BTC"])  # type: ignore[arg-type]
        loop = asyncio.get_running_loop()
        master.main_loop = loop
        created: list[object] = []

        def _capture_task(coro, *, name=None):  # type: ignore[no-untyped-def]
            created.append((coro, name))
            coro.close()
            return object()

        monkeypatch.setattr(asyncio, "create_task", _capture_task)
        wi._spawn_priority_ob_thread(master)
        assert master.hot_ob_loop is loop
        assert master.hot_ob_loop is master.main_loop
        assert len(created) == 1
        assert created[0][1] == "kalshi-priority-ob"

    asyncio.run(_run())
