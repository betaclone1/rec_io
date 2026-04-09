"""Tests for synthetic Kalshi 15m tickers (Eastern trading day grid)."""

from __future__ import annotations

from datetime import date

import pytest

from scripts.backtest.helpers.kalshi_ticker_construct import (
    kalshi_15m_market_tickers_for_eastern_date,
    kalshi_15m_market_tickers_for_eastern_date_range,
    validate_kalshi_series_for_15m_synth,
)


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
