"""tradeflow_live_state_trigger — parse and coalesce."""

from __future__ import annotations

from backend.core.tradeflow_live_state_trigger import (
    TradeflowLiveStateCoalescer,
    parse_tradeflow_symbol_market,
    tradeflow_live_state_trigger_enabled,
    tradeflow_orderbook_trigger_min_interval_sec,
    tradeflow_trigger_min_interval_sec,
)


def test_parse_symbol_expands_hourly_and_15m():
    pairs = parse_tradeflow_symbol_market(
        {
            "kind": "symbol",
            "key": "rec_io:live_state:v1:symbol:BTC",
        }
    )
    assert ("BTC", "hourly") in pairs
    assert ("BTC", "15m") in pairs


def test_parse_active_trades_returns_empty_use_kind_branch():
    assert (
        parse_tradeflow_symbol_market(
            {
                "kind": "active_trades",
                "key": "rec_io:live_state:v1:tenant:0001:active_trades",
            }
        )
        == []
    )


def test_parse_orderbook_hot_ticker(monkeypatch):
    monkeypatch.setenv("MARKET_WATCHDOG_HOT_ORDERBOOK_TICKERS", "KXBTC15M-26MAY241845-45")
    from backend.core.orderbook_hot_publish_registry import refresh_hot_tickers_if_stale

    refresh_hot_tickers_if_stale(force=True)
    pairs = parse_tradeflow_symbol_market(
        {
            "kind": "orderbook",
            "market_ticker": "KXBTC15M-26MAY241845-45",
        }
    )
    assert pairs == [("BTC", "15m")]


def test_parse_orderbook_cold_ticker_empty(monkeypatch):
    # Hourly crypto is not always-hot; without allowlist/watch it stays cold.
    monkeypatch.setenv("MARKET_WATCHDOG_HOT_CRYPTO_15M", "1")
    monkeypatch.delenv("MARKET_WATCHDOG_HOT_ORDERBOOK_TICKERS", raising=False)
    from backend.core.orderbook_hot_publish_registry import refresh_hot_tickers_if_stale

    refresh_hot_tickers_if_stale(force=True)
    pairs = parse_tradeflow_symbol_market(
        {
            "kind": "orderbook",
            "market_ticker": "KXBTCD-26MAY2418-T90000",
        }
    )
    assert pairs == []


def test_coalescer_rate_limits():
    c = TradeflowLiveStateCoalescer(10.0)
    assert c.should_fire("BTC", "15m")
    assert not c.should_fire("BTC", "15m")


def test_trigger_enabled_default_on():
    assert tradeflow_live_state_trigger_enabled() is True


def test_live_state_trigger_min_default_zero(monkeypatch):
    monkeypatch.delenv("TRADEFLOW_LIVE_STATE_TRIGGER_MIN_SEC", raising=False)
    assert tradeflow_trigger_min_interval_sec() == 0.0


def test_orderbook_trigger_min_default_zero(monkeypatch):
    monkeypatch.delenv("TRADEFLOW_ORDERBOOK_TRIGGER_MIN_SEC", raising=False)
    assert tradeflow_orderbook_trigger_min_interval_sec() == 0.0


def test_orderbook_coalescer_zero_never_blocks():
    c = TradeflowLiveStateCoalescer(0.0)
    assert c.should_fire("BTC", "15m")
    assert c.should_fire("BTC", "15m")


def test_general_coalescer_zero_never_blocks():
    c = TradeflowLiveStateCoalescer(0.0)
    assert c.should_fire("ETH", "hourly")
    assert c.should_fire("ETH", "hourly")
