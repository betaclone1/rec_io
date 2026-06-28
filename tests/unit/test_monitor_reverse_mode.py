"""Unit tests for monitor REVERSE mode helpers."""

from backend.core.monitor_reverse_mode import (
    apply_reverse_to_strike_data,
    effective_trade_strategy,
    executed_side_for_dedupe,
    flip_side,
    resolve_trade_strategy_for_insert,
)


def test_flip_side_yes_no():
    assert flip_side("yes") == "no"
    assert flip_side("Y") == "no"
    assert flip_side("no") == "yes"
    assert flip_side("N") == "yes"


def test_effective_trade_strategy_prefix():
    assert effective_trade_strategy("Hourly HTC", False) == "Hourly HTC"
    assert effective_trade_strategy("Hourly HTC", True) == "Reverse Hourly HTC"
    assert effective_trade_strategy("", True) == "Reverse Hourly HTC"


def test_apply_reverse_to_strike_data_flips_price_and_diff():
    strike_table = {
        "strikes": [
            {
                "ticker": "TICK-1",
                "yes_ask_dollars": "0.95",
                "no_ask_dollars": "0.05",
                "yes_diff": 1.2,
                "no_diff": 0.3,
            }
        ]
    }
    strike_data = {
        "side": "yes",
        "ticker": "TICK-1",
        "buy_price": 0.95,
        "diff": 1.2,
    }
    out = apply_reverse_to_strike_data(strike_data, strike_table, reverse=True)
    assert out["side"] == "no"
    assert out["buy_price"] == 0.05
    assert out["diff"] == 0.3


def test_apply_reverse_to_strike_data_noop_when_disabled():
    strike_data = {"side": "yes", "buy_price": 0.95}
    out = apply_reverse_to_strike_data(strike_data, None, reverse=False)
    assert out is strike_data


def test_executed_side_for_dedupe():
    assert executed_side_for_dedupe("yes", reverse=False) == "yes"
    assert executed_side_for_dedupe("yes", reverse=True) == "no"
    assert executed_side_for_dedupe("no", reverse=True) == "yes"


def test_resolve_trade_strategy_for_insert():
    assert resolve_trade_strategy_for_insert("Hourly HTC", None) == "Hourly HTC"
    assert resolve_trade_strategy_for_insert(
        "Hourly HTC", {"reverse": True, "strategy": "Hourly HTC"}
    ) == "Reverse Hourly HTC"
    assert resolve_trade_strategy_for_insert(
        "Reverse Hourly HTC", {"reverse": True, "strategy": "Hourly HTC"}
    ) == "Reverse Hourly HTC"
    assert resolve_trade_strategy_for_insert(
        None, {"reverse": True, "strategy": "Expiration Scalp"}
    ) == "Reverse Expiration Scalp"
