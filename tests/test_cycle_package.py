"""Unit tests for cycle package path helpers."""

from datetime import datetime, timezone
from unittest.mock import patch

from backend.core.cycle_hot_tables import (
    active_hot_tickers_for_ts,
    cycle_window_utc,
    is_cycle_ticker,
    parse_cycle_ticker_end_est,
    series_from_ticker,
    symbol_from_cycle_ticker,
)
from backend.core.cycle_packager import month_folder, package_path_for_ticker

_MT = "KXBTC15M-26JUL271045-45"
_ETH = "KXETH15M-26JUL271045-45"


def test_parse_ticker_end_est():
    end = parse_cycle_ticker_end_est("KXBTC15M-26JUL261345-45")
    assert end is not None
    assert end.tzinfo is not None
    assert end.year == 2026 and end.month == 7 and end.day == 26
    assert end.hour == 13 and end.minute == 45


def test_cycle_window_utc():
    open_u, close_u = cycle_window_utc("KXBTC15M-26JUL261345-45")
    assert (close_u - open_u).total_seconds() == 900


def test_cycle_window_quarter_hour_bounds_utc():
    """Named ticker ends 10:45 EDT → open 14:30Z, close 14:45Z inclusive endpoints."""
    open_u, close_u = cycle_window_utc(_MT)
    assert open_u == datetime(2026, 7, 27, 14, 30, tzinfo=timezone.utc)
    assert close_u == datetime(2026, 7, 27, 14, 45, tzinfo=timezone.utc)


def test_active_hot_includes_open_and_close_ticks():
    with (
        patch("backend.core.cycle_hot_tables.list_hot_tickers", return_value=[_MT]),
        patch("backend.core.cycle_hot_tables.refresh_hot_tickers_from_db"),
    ):
        assert _MT in active_hot_tickers_for_ts("2026-07-27T14:30:00.000Z")
        assert _MT in active_hot_tickers_for_ts("2026-07-27T14:45:00.000Z")
        assert _MT in active_hot_tickers_for_ts("2026-07-27T14:37:30.000Z")
        assert _MT not in active_hot_tickers_for_ts("2026-07-27T14:29:59.000Z")
        assert _MT not in active_hot_tickers_for_ts("2026-07-27T14:45:01.000Z")


def test_eth_ticker_identity_and_path():
    assert is_cycle_ticker(_ETH)
    assert series_from_ticker(_ETH) == "KXETH15M"
    assert symbol_from_cycle_ticker(_ETH) == "ETH"
    open_u, close_u = cycle_window_utc(_ETH)
    assert open_u == datetime(2026, 7, 27, 14, 30, tzinfo=timezone.utc)
    assert close_u == datetime(2026, 7, 27, 14, 45, tzinfo=timezone.utc)
    path = package_path_for_ticker(_ETH)
    assert path is not None
    assert path.parts[-3:] == ("2026", "2026_07_JUL", f"{_ETH}.tar.xz")
    assert "KXETH15M" in path.parts


def test_month_folder_and_path():
    end = parse_cycle_ticker_end_est("KXBTC15M-26JUL261345-45")
    year, month = month_folder(end)
    assert year == "2026"
    assert month == "2026_07_JUL"
    path = package_path_for_ticker("KXBTC15M-26JUL261345-45")
    assert path is not None
    assert path.parts[-3:] == ("2026", "2026_07_JUL", "KXBTC15M-26JUL261345-45.tar.xz")
    assert "backtesting_data" in path.parts
    assert "KXBTC15M" in path.parts
