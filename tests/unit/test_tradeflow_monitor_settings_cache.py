"""tradeflow_monitor_settings_cache — per-monitor auto_trade cache."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from backend.core.tradeflow_monitor_settings_cache import (
    get_cached_monitor_settings,
    invalidate_monitor_settings_cache,
)


def test_cache_disabled_calls_load_fn():
    with patch(
        "backend.core.tradeflow_monitor_settings_cache.live_state_cache_enabled",
        return_value=False,
    ):
        assert get_cached_monitor_settings("1", 99001, lambda: True) is True
        assert get_cached_monitor_settings("1", 99001, lambda: False) is False


def test_cache_hit_skips_load_fn():
    mock_r = MagicMock()
    mock_r.get.return_value = '{"auto_trade": true}'
    with patch(
        "backend.core.tradeflow_monitor_settings_cache.live_state_cache_enabled",
        return_value=True,
    ):
        with patch(
            "backend.core.tradeflow_monitor_settings_cache.redis_client_optional",
            return_value=mock_r,
        ):
            load = MagicMock(return_value=False)
            assert get_cached_monitor_settings("0001", 99001, load) is True
            load.assert_not_called()


def test_invalidate_deletes_key():
    mock_r = MagicMock()
    invalidate_monitor_settings_cache("0001", 99001, r=mock_r)
    mock_r.delete.assert_called_once_with(
        "rec_io:tradeflow:monitor_settings:v1:0001:99001"
    )
