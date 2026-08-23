"""ATS position-gated failsafe / ladder notify helpers."""

from __future__ import annotations

from unittest.mock import MagicMock

from backend.core.tradeflow_latest_only_lane import (
    LatestOnlyLaneHub,
    ladder_keys_for_tracked_monitors,
)


def test_ladder_keys_for_tracked_monitors_intersects():
    rows = [
        {"monitor_id": "m1", "symbol": "BTC", "market": "hourly"},
        {"monitor_id": "m2", "symbol": "ETH", "market": "15m"},
        {"monitor_id": "m3", "symbol": "SOL", "market": "hourly"},
    ]
    assert ladder_keys_for_tracked_monitors(rows, ["m2", "m1", "m9"]) == [
        ("BTC", "hourly"),
        ("ETH", "15m"),
    ]
    assert ladder_keys_for_tracked_monitors(rows, []) == []
    assert ladder_keys_for_tracked_monitors(rows, ["m9"]) == []


def test_ladder_keys_fallback_market():
    rows = [{"monitor_id": "m1", "symbol": "BTC", "market": "weird"}]
    assert ladder_keys_for_tracked_monitors(
        rows, ["m1"], fallback_market="15m"
    ) == [("BTC", "15m")]


def test_failsafe_refresh_keys_only_notifies_given():
    calls = []

    hub = LatestOnlyLaneHub(
        service="ats_test",
        fetch_snap=lambda s, m: {"symbol": s, "market": m},
        evaluate_lane=lambda _lane, _slot: None,
        ladder_keys=lambda: [("BTC", "hourly"), ("ETH", "hourly"), ("SOL", "15m")],
        parallelism=1,
    )
    hub.on_ladder_notify = MagicMock(side_effect=lambda s, m: calls.append((s, m)))  # type: ignore[method-assign]
    hub.failsafe_refresh_keys([("ETH", "hourly"), ("ETH", "hourly"), ("", "hourly")])
    assert calls == [("ETH", "hourly")]


def test_failsafe_refresh_keys_empty_is_noop():
    hub = LatestOnlyLaneHub(
        service="ats_test",
        fetch_snap=lambda s, m: None,
        evaluate_lane=lambda _lane, _slot: None,
        ladder_keys=lambda: [("BTC", "hourly")],
        parallelism=1,
    )
    hub.on_ladder_notify = MagicMock()  # type: ignore[method-assign]
    hub.failsafe_refresh_keys([])
    hub.on_ladder_notify.assert_not_called()
