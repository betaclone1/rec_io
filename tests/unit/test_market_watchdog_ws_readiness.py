import pytest


from backend.market_watchdog_ws import _markets_all_have_usable_strike_inputs


def test_readiness_requires_explicit_floor_strike_even_if_subtitle_derivable():
    """Rollover gate: subtitle-only is not enough; API must expose floor_strike for seeding."""
    event_data = {
        "markets": [
            {
                "subtitle": "$101 or above",
                "floor_strike": None,
                "yes_bid_dollars": "0.45",
                "yes_ask_dollars": "0.55",
            }
        ]
    }
    assert _markets_all_have_usable_strike_inputs(event_data) is False


def test_readiness_passes_with_floor_strike_and_quotes():
    event_data = {
        "markets": [
            {
                "floor_strike": 1010000,
                "yes_bid_dollars": "0.45",
                "yes_ask_dollars": "0.55",
            }
        ]
    }
    assert _markets_all_have_usable_strike_inputs(event_data) is True


def test_readiness_requires_yes_ask_and_yes_bid_dollars():
    event_data_missing_yes_ask = {
        "markets": [
            {
                "subtitle": "$101 or above",
                "floor_strike": None,
                "yes_bid_dollars": "0.45",
                "yes_ask_dollars": "",
            }
        ]
    }
    assert _markets_all_have_usable_strike_inputs(event_data_missing_yes_ask) is False

