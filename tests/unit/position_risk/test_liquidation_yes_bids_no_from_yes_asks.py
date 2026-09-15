"""YES bids vs NO implied from YES asks (liquidation walk)."""

from __future__ import annotations

from backend.core.position_risk.liquidation import (
    executable_bid_levels,
    walk_executable_liquidation,
)


def test_yes_walks_yes_bids():
    yes = {"0.90": "5", "0.89": "5"}
    no = {"0.10": "100"}  # would imply YES asks if used incorrectly for YES
    levels = executable_bid_levels(yes, no, "yes")
    assert levels[0][0] == 0.90
    out = walk_executable_liquidation(yes, no, "Y", 8)
    assert out["ok"] is True
    assert abs(float(out["gross_lvwap"]) - ((0.90 * 5 + 0.89 * 3) / 8)) < 1e-9
    assert out["worst_consumed_price"] == 0.89


def test_no_from_yes_asks_not_independent_no_book():
    # YES asks via complementary_asks(side=yes) use NO bids: yes_ask = 1 - no_bid
    # Implied NO bids = 1 - yes_ask = no_bid levels.
    yes = {"0.50": "1"}  # YES bids must not drive NO liquidation
    no = {"0.92": "10", "0.91": "10"}  # → YES asks 0.08 / 0.09 → NO bids 0.92 / 0.91
    levels = executable_bid_levels(yes, no, "no")
    assert levels[0] == (0.92, 10.0)
    out = walk_executable_liquidation(yes, no, "N", 10)
    assert out["ok"] is True
    assert out["gross_lvwap"] == 0.92
    # Poisoned independent NO-looking path would use yes bids if wrong
    assert out["gross_lvwap"] != 0.50


def test_partial_coverage_no_gross_lvwap():
    yes = {"0.90": "2"}
    no = {}
    out = walk_executable_liquidation(yes, no, "yes", 10)
    assert out["ok"] is False
    assert out["reason"] == "DEPTH_INSUFFICIENT"
    assert out["gross_lvwap"] is None
    assert out["full_coverage"] is False


def test_fee_slippage_separate_from_gross():
    yes = {"0.90": "10"}
    no = {}
    out = walk_executable_liquidation(
        yes,
        no,
        "yes",
        10,
        estimated_taker_fee_per_contract=0.01,
        slippage_reserve=0.005,
    )
    assert out["gross_lvwap"] == 0.90
    assert abs(float(out["net_lvwap"]) - 0.885) < 1e-9
