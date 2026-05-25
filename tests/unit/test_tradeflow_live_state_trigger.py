"""tradeflow_live_state_trigger — parse and coalesce."""

from __future__ import annotations

from backend.core.tradeflow_live_state_trigger import (
    TradeflowLiveStateCoalescer,
    parse_tradeflow_symbol_market,
    tradeflow_live_state_trigger_enabled,
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


def test_parse_orderbook_cold_ticker_empty():
    pairs = parse_tradeflow_symbol_market(
        {
            "kind": "orderbook",
            "market_ticker": "KXBTC15M-26MAY241899-99",
        }
    )
    assert pairs == []


def test_coalescer_rate_limits():
    c = TradeflowLiveStateCoalescer(10.0)
    assert c.should_fire("BTC", "15m")
    assert not c.should_fire("BTC", "15m")


def test_trigger_enabled_default_on():
    assert tradeflow_live_state_trigger_enabled() is True
