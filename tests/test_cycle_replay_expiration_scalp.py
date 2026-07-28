"""Unit tests for Expiration Scalp offline gates + cycle package load."""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.util.auto_entry_expiration_scalp_gates import (
    evaluate_expiration_scalp_entry,
    evaluate_expiration_scalp_floor_exit,
)


SETTINGS = {
    "min_time": 15,
    "max_time": 60,
    "min_probability": 0,
    "max_probability": 100,
    "min_ask": 0.90,
    "max_ask": 0.99,
    "stop_loss_price": 0.35,
}


def test_expiration_scalp_entry_passes_in_band():
    passed, reason = evaluate_expiration_scalp_entry(
        SETTINGS,
        ttc_seconds=56,
        side="yes",
        ask_dollars=0.958,
        probability=55.0,
    )
    assert reason is None
    assert passed is not None
    assert passed["buy_price"] == 0.958
    assert passed["side"] == "yes"


def test_expiration_scalp_entry_rejects_ask_below_min():
    passed, reason = evaluate_expiration_scalp_entry(
        SETTINGS,
        ttc_seconds=56,
        side="yes",
        ask_dollars=0.85,
        probability=55.0,
    )
    assert passed is None
    assert reason == "ask_outside_band"


def test_expiration_scalp_floor_exit_triggers_on_opp_ask():
    # stop_loss_price=0.35 → threshold opp ask > 0.65
    should, count, detail = evaluate_expiration_scalp_floor_exit(
        SETTINGS,
        position_side="yes",
        yes_ask=0.30,
        no_ask=0.70,
        confirm_ticks=1,
        prior_confirm_count=0,
    )
    assert should is True
    assert count == 1
    assert detail is not None


def test_project_taker_buy_from_levels_vwap():
    from backend.core.orderbook_strike_prices import project_taker_buy_from_levels

    # yes buy walks no bids → asks = 1 - bid
    # no bid 0.20 (size 10) → ask 0.80; no bid 0.10 (size 10) → ask 0.90
    yes = {}
    no = {"0.20": "10", "0.10": "10"}
    proj = project_taker_buy_from_levels(yes, no, "yes", 15, limit_price=0.95)
    assert proj["ok"] is True
    assert proj["filled"] == 15
    # 10 @ 0.80 + 5 @ 0.90 = 12.5 / 15 = 0.8333...
    assert abs(float(proj["initial_proj_price"]) - (10 * 0.8 + 5 * 0.9) / 15) < 1e-6


@pytest.mark.skipif(
    not Path(
        "backend/data/historical_data/backtesting_data/KXBTC15M/2026/2026_07_JUL/"
        "KXBTC15M-26JUL271700-00.tar.xz"
    ).is_file(),
    reason="sample cycle package not present",
)
def test_replay_trade_31232_package_first_entry():
    from backend.util.cycle_replay.runner import run_cycle_replay

    pkg = (
        "backend/data/historical_data/backtesting_data/KXBTC15M/2026/2026_07_JUL/"
        "KXBTC15M-26JUL271700-00.tar.xz"
    )
    settings = {
        **SETTINGS,
        "total_position": 25,
        "time_in_force": "immediate_or_cancel",
        "order_type": "market",
        "min_fill_price": 0.86,
    }
    result = run_cycle_replay(pkg, settings, strategy="Expiration Scalp")
    assert result.first_entry is not None
    e = result.first_entry
    assert e.side == "Y"
    assert e.ticket_ask is not None and abs(e.ticket_ask - 0.958) < 0.01
    assert e.filled == 25
    assert e.fees is not None and e.fees >= 0
    # Paper IOC fill at first-eligible book (thick at ticket ask)
    assert abs(e.buy_price - 0.958) < 0.01
    assert e.ttc_seconds == 60
    assert result.positions
    assert result.positions[0].exit is not None
    assert result.positions[0].exit.close_method == "expired"
    assert result.positions[0].exit.status == "closed"
    assert result.positions[0].exit.win_loss == "W"
    assert result.positions[0].exit.sell_price == 1.0
    assert result.positions[0].side == "Y"

def test_min_fill_rejects_paper_entry():
    from datetime import datetime, timezone

    from backend.core.cycle_package import CycleTick
    from backend.util.cycle_replay.fills import apply_paper_entry_fill
    from backend.util.cycle_replay.types import EntryEvent

    # Book only has ask 0.80 for yes (no bid 0.20)
    tick = CycleTick(
        timestamp=datetime(2026, 7, 27, 20, 59, 0, tzinfo=timezone.utc),
        ttc_seconds=60,
        spot=65000.0,
        avg_60s=None,
        yes_ask=0.80,
        no_ask=0.20,
        probability_15m=55.0,
        yes_prob_15m=55.0,
        no_prob_15m=45.0,
        fair_price=None,
        floor_strike=None,
        yes_book={},
        no_book={"0.20": "100"},
    )
    intent = EntryEvent(
        timestamp=tick.timestamp,
        side="Y",
        ticket_ask=0.95,
        buy_price=0.95,
        probability=55.0,
        ttc_seconds=60,
    )
    filled, reason = apply_paper_entry_fill(
        intent,
        tick,
        {
            "total_position": 10,
            "time_in_force": "immediate_or_cancel",
            "order_type": "limit",
            "min_fill_price": 0.90,
        },
    )
    assert filled is None
    assert reason and "min_fill_price_rejected" in reason


def test_market_order_uses_099_limit_not_ticket_ask():
    from datetime import datetime, timezone

    from backend.core.cycle_package import CycleTick
    from backend.util.cycle_replay.fills import apply_paper_entry_fill
    from backend.util.cycle_replay.types import EntryEvent

    # Top ask 0.95 (size 5), next 0.97 (size 20) — market IOC @ 0.99 walks both;
    # limit @ ticket 0.95 would only take 5.
    tick = CycleTick(
        timestamp=datetime(2026, 7, 27, 20, 59, 0, tzinfo=timezone.utc),
        ttc_seconds=60,
        spot=65000.0,
        avg_60s=None,
        yes_ask=0.95,
        no_ask=0.05,
        probability_15m=55.0,
        yes_prob_15m=55.0,
        no_prob_15m=45.0,
        fair_price=None,
        floor_strike=None,
        yes_book={},
        no_book={"0.05": "5", "0.03": "20"},  # asks 0.95 and 0.97
    )
    intent = EntryEvent(
        timestamp=tick.timestamp,
        side="Y",
        ticket_ask=0.95,
        buy_price=0.95,
        probability=55.0,
        ttc_seconds=60,
    )
    market_fill, _ = apply_paper_entry_fill(
        intent,
        tick,
        {
            "total_position": 25,
            "time_in_force": "immediate_or_cancel",
            "order_type": "market",
            "min_fill_price": 0.0,
        },
    )
    assert market_fill is not None
    assert market_fill.filled == 25
    assert market_fill.detail.get("limit_price") == 0.99
    # 5@0.95 + 20@0.97 = 24.15/25 = 0.966
    assert abs(market_fill.buy_price - 0.966) < 1e-6

    limit_fill, _ = apply_paper_entry_fill(
        intent,
        tick,
        {
            "total_position": 25,
            "time_in_force": "immediate_or_cancel",
            "order_type": "limit",
            "min_fill_price": 0.0,
        },
    )
    assert limit_fill is not None
    assert limit_fill.filled == 5
    assert limit_fill.detail.get("limit_price") == 0.95
    assert abs(limit_fill.buy_price - 0.95) < 1e-6
