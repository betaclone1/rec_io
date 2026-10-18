"""Watchdog WS must fan out lifecycle outcomes to tenant consumers."""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

import backend.core.market_watchdog.venues.kalshi.ws_ingest as ws_ingest


def test_publish_lifecycle_trades_event_calls_redis_helper():
    with patch(
        "backend.core.trading_redis_comms.publish_kalshi_lifecycle_trades_event",
        return_value=True,
    ) as pub:
        ws_ingest._publish_lifecycle_trades_event(
            "KXBTC15M-26OCT181045-45", "no", "determined"
        )
    pub.assert_called_once_with(
        market_ticker="KXBTC15M-26OCT181045-45",
        result_raw="no",
        event_type="determined",
        source="market_watchdog_ws",
    )


def test_handle_lifecycle_v2_publishes_even_when_not_tracked():
    master = MagicMock()
    master.lock = asyncio.Lock()

    with (
        patch.object(ws_ingest, "_publish_lifecycle_trades_event") as pub,
        patch.object(ws_ingest, "_matches_tracked_series", return_value=False),
        patch.object(ws_ingest, "_apply_market_result_ws") as apply_ws,
    ):
        asyncio.run(
            ws_ingest._handle_lifecycle_v2(
                master,
                {
                    "event_type": "determined",
                    "market_ticker": "KXBTC15M-26OCT181045-45",
                    "result": "no",
                },
            )
        )

    pub.assert_called_once_with("KXBTC15M-26OCT181045-45", "no", "determined")
    apply_ws.assert_not_called()


def test_handle_lifecycle_v2_applies_when_tracked():
    master = MagicMock()
    master.lock = asyncio.Lock()

    with (
        patch.object(ws_ingest, "_publish_lifecycle_trades_event") as pub,
        patch.object(ws_ingest, "_matches_tracked_series", return_value=True),
        patch.object(ws_ingest, "_apply_market_result_ws") as apply_ws,
    ):
        asyncio.run(
            ws_ingest._handle_lifecycle_v2(
                master,
                {
                    "event_type": "settled",
                    "market_ticker": "KXBTC15M-26OCT181100-00",
                    "market_result": "yes",
                },
            )
        )

    pub.assert_called_once_with("KXBTC15M-26OCT181100-00", "yes", "settled")
    apply_ws.assert_called_once_with(
        master, "KXBTC15M-26OCT181100-00", "yes", source="lifecycle_ws"
    )
