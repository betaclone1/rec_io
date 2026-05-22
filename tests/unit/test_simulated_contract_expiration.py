"""Simulated 15m settlement must not run before contract wall-clock expiry."""

from datetime import datetime
from zoneinfo import ZoneInfo

from backend.trade_manager import _contract_expiration_est

EST = ZoneInfo("America/New_York")


def test_contract_expiration_15m_label_8pm_same_day():
    trade_date = "2026-05-07"
    exp = _contract_expiration_est(trade_date, "BTC 8:00pm", datetime.now(EST))
    assert exp == datetime(2026, 5, 7, 20, 0, 0, tzinfo=EST)


def test_contract_expiration_15m_skip_until_expiry_wall_clock():
    trade_date = "2026-05-07"
    contract = "BTC 8:00pm"
    exp = _contract_expiration_est(trade_date, contract, datetime.now(EST))

    at_745 = datetime(2026, 5, 7, 19, 45, 0, tzinfo=EST)
    assert at_745 < exp

    at_8 = datetime(2026, 5, 7, 20, 0, 0, tzinfo=EST)
    assert not (at_8 < exp)


def test_contract_expiration_hourly_label_without_minutes():
    trade_date = "2026-05-07"
    exp = _contract_expiration_est(trade_date, "BTC 8pm", datetime.now(EST))
    assert exp == datetime(2026, 5, 7, 20, 0, 0, tzinfo=EST)


def test_contract_expiration_hourly_5pm_not_due_at_4pm():
    """Hourly BTC 5pm must not be treated as expired during the 4pm hour (48538-class bug)."""
    trade_date = "2026-05-22"
    exp = _contract_expiration_est(trade_date, "BTC 5pm", datetime.now(EST))
    assert exp == datetime(2026, 5, 22, 17, 0, 0, tzinfo=EST)

    at_4pm = datetime(2026, 5, 22, 16, 0, 24, tzinfo=EST)
    assert at_4pm < exp
