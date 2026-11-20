"""Tests for synthetic Kalshi 15m tickers (Eastern trading day grid)."""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from scripts.backtest.helpers.kalshi_ticker_construct import (
    kalshi_15m_market_tickers_for_eastern_date,
    kalshi_15m_market_tickers_for_eastern_date_range,
    kalshi_15m_market_tickers_for_hours_back,
    kalshi_15m_settlement_end_est_from_ticker,
    validate_kalshi_series_for_15m_synth,
)

EST = ZoneInfo("America/New_York")


def test_validate_series_requires_15m() -> None:
    with pytest.raises(ValueError, match="15M"):
        validate_kalshi_series_for_15m_synth("KXBTCD")


def test_march_31_2026_96_tickers_shape() -> None:
    tickers = kalshi_15m_market_tickers_for_eastern_date("KXETH15M", date(2026, 3, 31))
    assert len(tickers) == 96
    assert tickers[0] == "KXETH15M-26MAR310000-00"
    assert tickers[1] == "KXETH15M-26MAR310015-15"
    assert tickers[94] == "KXETH15M-26MAR312330-30"
    assert tickers[95] == "KXETH15M-26MAR312345-45"


def test_date_range_two_days_192_tickers_chronological() -> None:
    tickers = kalshi_15m_market_tickers_for_eastern_date_range(
        "KXBTC15M", date(2026, 4, 1), date(2026, 4, 2)
    )
    assert len(tickers) == 192
    day0 = kalshi_15m_market_tickers_for_eastern_date("KXBTC15M", date(2026, 4, 1))
    day1 = kalshi_15m_market_tickers_for_eastern_date("KXBTC15M", date(2026, 4, 2))
    assert tickers[:96] == day0
    assert tickers[96:] == day1


def test_cross_midnight_not_wrapped_to_prior_month_label() -> None:
    """Settlement ends are same calendar day; no Apr 1 00:00 slot in the 96 list."""
    tickers = kalshi_15m_market_tickers_for_eastern_date("KXBTC15M", date(2026, 3, 31))
    assert all("26APR01" not in t for t in tickers)
    assert tickers[-1].endswith("2345-45")


def test_settlement_parse_matches_constructed_ticker() -> None:
    t = "KXBTC15M-26NOV191530-30"
    end = kalshi_15m_settlement_end_est_from_ticker(t)
    assert end == datetime(2026, 11, 19, 15, 30, tzinfo=EST)


def test_hours_back_returns_recent_settlements_only() -> None:
    now = datetime(2026, 11, 19, 15, 30, tzinfo=EST)
    by_day = kalshi_15m_market_tickers_for_hours_back(
        "KXBTC15M", hours_back=2.0, now=now
    )
    assert list(by_day.keys()) == [date(2026, 11, 19)]
    # [13:30, 15:45] inclusive at 15m steps → 10 tickers
    assert len(by_day[date(2026, 11, 19)]) == 10
    assert by_day[date(2026, 11, 19)][0].endswith("1330-30")
    assert by_day[date(2026, 11, 19)][-1].endswith("1545-45")
