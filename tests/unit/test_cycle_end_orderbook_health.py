"""Cycle-end empty/incomplete orderbooks must not mark monitors degraded."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from backend.core.strike_pipeline_health import (
    is_expected_cycle_end_orderbook_failure,
    is_orderbook_touch_incomplete_reason,
)


EST = ZoneInfo("America/New_York")


def test_orderbook_incomplete_reason_detection():
    assert is_orderbook_touch_incomplete_reason(
        "orderbook_degraded:orderbook_incomplete:no_ask_dollars:strike=1:ticker=x"
    )
    assert is_orderbook_touch_incomplete_reason("orderbook_empty")
    assert not is_orderbook_touch_incomplete_reason("orderbook_stale:40.0s>30.0s")
    assert not is_orderbook_touch_incomplete_reason("orderbook_miss")
    assert not is_orderbook_touch_incomplete_reason("strike_refresh_failed")


def test_expected_near_settlement_before():
    # Settlement 10:15 ET; clock 10:14:30 → 30s before.
    now = datetime(2026, 11, 20, 10, 14, 30, tzinfo=EST)
    assert is_expected_cycle_end_orderbook_failure(
        fail_reason="orderbook_degraded:orderbook_incomplete:no_ask_dollars",
        event_ticker="KXBTC15M-26NOV201015-15",
        now=now,
        before_sec=90,
        after_sec=120,
    )


def test_expected_shortly_after_settlement():
    # Still regenerating dying ticker a few seconds after the boundary.
    now = datetime(2026, 11, 20, 10, 15, 6, tzinfo=EST)
    assert is_expected_cycle_end_orderbook_failure(
        fail_reason="orderbook_incomplete:no_ask_dollars",
        event_ticker="KXETH15M-26NOV201015-15",
        now=now,
        before_sec=90,
        after_sec=120,
    )


def test_not_expected_mid_cycle():
    now = datetime(2026, 11, 20, 10, 7, 0, tzinfo=EST)
    assert not is_expected_cycle_end_orderbook_failure(
        fail_reason="orderbook_incomplete:no_ask_dollars",
        event_ticker="KXBTC15M-26NOV201015-15",
        now=now,
        before_sec=90,
        after_sec=120,
    )


def test_not_expected_for_stale_transport():
    now = datetime(2026, 11, 20, 10, 14, 50, tzinfo=EST)
    assert not is_expected_cycle_end_orderbook_failure(
        fail_reason="orderbook_stale:45.0s>30.0s",
        event_ticker="KXBTC15M-26NOV201015-15",
        now=now,
        before_sec=90,
        after_sec=120,
    )


def test_not_expected_without_ticker():
    now = datetime(2026, 11, 20, 10, 14, 50, tzinfo=EST)
    assert not is_expected_cycle_end_orderbook_failure(
        fail_reason="orderbook_incomplete:no_ask_dollars",
        event_ticker=None,
        now=now,
    )
