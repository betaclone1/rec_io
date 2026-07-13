"""Trade manager orderbook projection uses Redis (same feed as trade_executor)."""

from __future__ import annotations

from unittest.mock import patch

import backend.trade_manager as tm


@patch("backend.core.trade_monitor_live_orderbook_payload.load_orderbook_snapshot_from_redis")
def test_fetch_orderbook_for_projection_uses_redis(mock_load):
    mock_load.return_value = {
        "valid": True,
        "market_ticker": "KXBTCD-26JUL1315-T62399.99",
        "yes": {"0.40": "100", "0.41": "50"},
        "no": {"0.55": "200"},
    }

    ob, reason = tm._fetch_orderbook_for_projection("KXBTCD-26JUL1315-T62399.99")

    assert reason == "redis"
    assert ob is not None
    assert sorted(ob["yes_dollars"]) == [[0.40, 100.0], [0.41, 50.0]]
    assert ob["no_dollars"] == [[0.55, 200.0]]
    mock_load.assert_called_once_with("KXBTCD-26JUL1315-T62399.99")


@patch("backend.core.trade_monitor_live_orderbook_payload.load_orderbook_snapshot_from_redis")
def test_fetch_orderbook_for_projection_miss_stays_miss(mock_load):
    mock_load.return_value = None

    ob, reason = tm._fetch_orderbook_for_projection("KXBTCD-MISSING")

    assert ob is None
    assert reason == "orderbook_miss"


@patch("backend.trade_manager._fetch_orderbook_for_projection")
def test_project_orderbook_entry_vwap_from_redis_shape(mock_fetch):
    # Buying NO walks YES bids → asks at 1-bid
    mock_fetch.return_value = (
        {
            "yes_dollars": [[0.10, 100.0], [0.20, 100.0]],  # asks 0.90, 0.80
            "no_dollars": [],
        },
        "redis",
    )

    proj = tm._project_orderbook_entry("T", "no", 150)

    assert proj["ok"] is True
    assert proj["reason"] == "ok"
    # Best ask first: bid 0.20 → ask 0.80, then bid 0.10 → ask 0.90
    # 100 @ 0.80 + 50 @ 0.90 = 125 / 150
    assert abs(float(proj["initial_proj_price"]) - (100 * 0.80 + 50 * 0.90) / 150) < 1e-6
    assert proj["initial_proj_fees"] is not None
    assert proj["available_contracts"] == 200.0
