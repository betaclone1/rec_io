from unittest.mock import patch

from backend.core.market_watchdog.venues.kalshi import ws_ingest


def test_hourly_spot_price_prefers_live_state():
    with patch(
        "backend.core.tradeflow_live_reads.symbol_spot_price_for_monitoring",
        return_value=75450.0,
    ) as mock_spot:
        assert ws_ingest._hourly_spot_price("btc") == 75450.0
        mock_spot.assert_called_once_with(
            "BTC",
            prefer_max_age_sec=120.0,
            allow_stale_max_age_sec=300.0,
        )
