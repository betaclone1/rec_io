"""Quarter-hour expiry eligibility and canonical held-to-expiration close time."""

from datetime import datetime
from zoneinfo import ZoneInfo

import backend.trade_manager as trade_manager
from backend.trade_manager import (
    _contract_expiration_est,
    _expiration_closed_at,
    _trade_eligible_for_quarter_hour_expiry,
)

_EST = ZoneInfo("America/New_York")


def test_market_15m_any_strategy():
    assert _trade_eligible_for_quarter_hour_expiry("15m") is True
    assert _trade_eligible_for_quarter_hour_expiry(" 15m ") is True


def test_market_hourly_or_null_top_of_hour_only():
    assert _trade_eligible_for_quarter_hour_expiry("hourly") is False
    assert _trade_eligible_for_quarter_hour_expiry(None) is False
    assert _trade_eligible_for_quarter_hour_expiry("") is False


def test_expiration_closed_at_uses_contract_boundary_not_sweep_time():
    sweep_time = datetime(2026, 7, 29, 15, 45, 7, tzinfo=_EST)
    expiration = _contract_expiration_est("2026-07-29", "BTC 3:45pm", sweep_time)

    assert expiration == datetime(2026, 7, 29, 15, 45, 0, tzinfo=_EST)
    assert _expiration_closed_at(expiration) == "15:45:00"


def test_hourly_expiration_closed_at_is_top_of_hour():
    sweep_time = datetime(2026, 7, 29, 16, 0, 9, tzinfo=_EST)
    expiration = _contract_expiration_est("2026-07-29", "BTC 4pm", sweep_time)

    assert _expiration_closed_at(expiration) == "16:00:00"


def test_expiration_closed_at_converts_to_est_and_drops_microseconds():
    utc = ZoneInfo("UTC")
    expiration = datetime(2026, 7, 29, 19, 30, 0, 900000, tzinfo=utc)

    assert _expiration_closed_at(expiration) == "15:30:00"


def test_expired_finalization_corrects_delayed_closed_at(monkeypatch):
    """Venue-result arrival must preserve cycle time, not the later sweep time."""
    row = (
        "expired",
        "yes",
        "yes",
        0.40,
        10,
        0.25,
        1000,
        1000,
        63250.0,
        0.70,
        0.35,
        "15:45:07",  # old behavior: processing time
        "KXBTC15M-26JUL291545-T63249.99",
        False,
        "BTC 3:45pm",
        "2026-07-29",
    )

    class Cursor:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def execute(self, *_args, **_kwargs):
            return None

        def fetchone(self):
            return row

    class Conn:
        def cursor(self):
            return Cursor()

        def close(self):
            return None

    captured = {}
    monkeypatch.setattr(trade_manager, "get_postgresql_connection", lambda: Conn())
    monkeypatch.setattr(
        trade_manager,
        "update_trade_status_with_ret_pct",
        lambda **kwargs: captured.update(kwargs),
    )
    monkeypatch.setattr(
        trade_manager, "notify_active_trade_supervisor_direct", lambda *_: None
    )
    monkeypatch.setattr(
        trade_manager, "notify_strike_table_trade_change", lambda *_: None
    )

    assert trade_manager.finalize_expired_trade_from_market_result(123) is True
    assert captured["status"] == "closed"
    assert captured["closed_at"] == "15:45:00"
    assert captured["close_method"] == "expired"
