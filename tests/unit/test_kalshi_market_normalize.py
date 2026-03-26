"""Unit tests for Kalshi ticker normalization (WebSocket market ticker → DB row shape)."""

from backend.core.kalshi_market_normalize import (
    derive_no_side_dollars_from_yes,
    normalize_kalshi_dollar_text,
    strike_from_kalshi_15m_rest_market,
    ticker_msg_to_row_values,
)


def test_derive_no_side_dollars_complement():
    no_bid, no_ask = derive_no_side_dollars_from_yes("0.45", "0.55")
    assert no_bid == "0.45"
    assert no_ask == "0.55"


def test_derive_no_side_partial_yes_ask_only():
    no_bid, no_ask = derive_no_side_dollars_from_yes(None, "0.52")
    assert no_bid == "0.48"
    assert no_ask is None


def test_derive_no_side_partial_yes_bid_only():
    no_bid, no_ask = derive_no_side_dollars_from_yes("0.48", None)
    assert no_bid is None
    assert no_ask == "0.52"


def test_derive_no_side_uses_max_input_precision_three_dp():
    no_bid, no_ask = derive_no_side_dollars_from_yes("0.450", "0.530")
    assert no_bid == "0.470"
    assert no_ask == "0.550"


def test_normalize_dollar_coerces_float_json_to_four_dp():
    assert normalize_kalshi_dollar_text(0.7, 4) == "0.7000"
    assert normalize_kalshi_dollar_text(0.69, 4) == "0.6900"


def test_strike_from_rest_prefers_floor_strike_over_subtitle():
    m = {"subtitle": "$100 or above", "floor_strike": 101500}
    assert strike_from_kalshi_15m_rest_market(m) == "$101,500"


def test_strike_from_rest_subtitle_when_no_floor():
    m = {"subtitle": "$42,500 or above"}
    assert strike_from_kalshi_15m_rest_market(m) == "$42,500"


def test_strike_from_rest_none_when_empty():
    assert strike_from_kalshi_15m_rest_market({}) is None


def test_ticker_msg_to_row_values_maps_fields():
    msg = {
        "market_ticker": "KXBTC15M-TEST-T100000",
        "price_dollars": "0.42",
        "yes_bid_dollars": "0.40",
        "yes_ask_dollars": "0.44",
        "volume_fp": "12345.0",
        "open_interest_fp": "999.0",
    }
    row = ticker_msg_to_row_values(
        msg, symbol="BTC", event_ticker="KXBTC15M-TEST", exchange="kalshi"
    )
    (
        sym,
        br,
        event_ticker,
        market_ticker,
        market_val,
        strike,
        yes_bid_dollars,
        yes_ask_dollars,
        no_bid_dollars,
        no_ask_dollars,
        last_price_dollars,
        volume_fp,
        open_interest_fp,
    ) = row
    assert sym == "BTC"
    assert br == "kalshi"
    assert event_ticker == "KXBTC15M-TEST"
    assert market_ticker == "KXBTC15M-TEST-T100000"
    assert market_val == "15m"
    assert strike == "$100,000"
    assert yes_bid_dollars == "0.4000"
    assert yes_ask_dollars == "0.4400"
    assert no_bid_dollars == "0.5600"
    assert no_ask_dollars == "0.6000"
    assert last_price_dollars == "0.4200"
    assert volume_fp == "12345.00"
    assert open_interest_fp == "999.00"


def test_ticker_msg_requires_market_ticker():
    try:
        ticker_msg_to_row_values(
            {}, symbol="BTC", event_ticker="KX-E", exchange="kalshi"
        )
    except ValueError as e:
        assert "market_ticker" in str(e).lower()
    else:
        raise AssertionError("expected ValueError")
