"""Quarter-hour expiry eligibility: only ``trades.market`` = ``15m``."""

from backend.trade_manager import _trade_eligible_for_quarter_hour_expiry


def test_market_15m_any_strategy():
    assert _trade_eligible_for_quarter_hour_expiry("15m") is True
    assert _trade_eligible_for_quarter_hour_expiry(" 15m ") is True


def test_market_hourly_or_null_top_of_hour_only():
    assert _trade_eligible_for_quarter_hour_expiry("hourly") is False
    assert _trade_eligible_for_quarter_hour_expiry(None) is False
    assert _trade_eligible_for_quarter_hour_expiry("") is False
