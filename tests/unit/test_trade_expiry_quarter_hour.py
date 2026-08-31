"""Quarter-hour expiry eligibility and canonical held-to-expiration close time."""

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

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
        0,
        None,
        None,
        None,
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
    assert captured["sell_price"] == 1.0
    assert captured["win_loss"] == "W"
    assert captured["pnl"] == round((1.0 - 0.40) * 10 - 0.25, 6)


def _expiry_conn(row):
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

        def commit(self):
            return None

    return Conn()


def test_live_hws_expiry_mixes_gtc_slice_with_remainder(monkeypatch):
    """400 @ 0.99 GTC + 2100 leftover winning expiry, live HWS."""
    row = (
        "expired",
        "yes",
        "yes",
        0.90,
        2500,
        5.00,
        100000,
        100000,
        63250.0,
        0.99,
        0.90,
        "15:45:07",
        "KXBTC15M-26JUL291545-T63249.99",
        False,
        "BTC 3:45pm",
        "2026-07-29",
        400,
        0.99,
        "High Water Scalp",
        "gtc-oid",
    )
    captured = {}
    monkeypatch.setattr(trade_manager, "get_postgresql_connection", lambda: _expiry_conn(row))
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
    monkeypatch.setattr(
        trade_manager,
        "_hws_kalshi_order_close_slice",
        lambda *_a, **_k: {
            "order_id": "gtc-oid",
            "fill_qty": 400.0,
            "sell_price": 0.99,
            "fees": 1.25,
        },
    )

    assert trade_manager.finalize_expired_trade_from_market_result(7) is True
    # 400*0.99 + 2100*1.00 = 2496; buy 2250; fees 5+1.25 → pnl 239.75
    assert captured["sell_price"] == pytest.approx(2496.0 / 2500.0)
    assert captured["pnl"] == 239.75
    assert captured["fees"] == 6.25
    assert captured["win_loss"] == "W"
    assert captured["close_method"] == "expired"
    assert captured["ret_pct"] == round((239.75 / (100000 / 100.0)) * 100, 5)


def test_live_hws_expiry_remainder_loss_keeps_gtc_slice(monkeypatch):
    row = (
        "expired",
        "no",
        "yes",
        0.90,
        2500,
        5.00,
        100000,
        100000,
        63250.0,
        0.99,
        0.90,
        "15:45:07",
        "KXBTC15M-26JUL291545-T63249.99",
        False,
        "BTC 3:45pm",
        "2026-07-29",
        400,
        0.99,
        "High Water Scalp",
        "gtc-oid",
    )
    captured = {}
    monkeypatch.setattr(trade_manager, "get_postgresql_connection", lambda: _expiry_conn(row))
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
    monkeypatch.setattr(trade_manager, "_hws_kalshi_order_close_slice", lambda *_a, **_k: None)

    assert trade_manager.finalize_expired_trade_from_market_result(7) is True
    # 400*0.99 + 2100*0 = 396; buy 2250; fees 5 → pnl -1859
    assert captured["sell_price"] == pytest.approx(396.0 / 2500.0)
    assert captured["pnl"] == -1859.0
    assert captured["win_loss"] == "L"
    assert captured["fees"] == 5.0


def test_live_hws_expiry_waits_when_gtc_slice_unpriced(monkeypatch):
    row = (
        "expired",
        "yes",
        "yes",
        0.90,
        2500,
        5.00,
        100000,
        100000,
        63250.0,
        0.99,
        0.90,
        "15:45:07",
        "KXBTC15M-26JUL291545-T63249.99",
        False,
        "BTC 3:45pm",
        "2026-07-29",
        400,
        None,
        "High Water Scalp",
        "gtc-oid",
    )
    captured = {}
    monkeypatch.setattr(trade_manager, "get_postgresql_connection", lambda: _expiry_conn(row))
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
    monkeypatch.setattr(trade_manager, "_hws_kalshi_order_close_slice", lambda *_a, **_k: None)

    assert trade_manager.finalize_expired_trade_from_market_result(7) is False
    assert captured == {}


def test_paper_hws_expiry_still_full_hold(monkeypatch):
    row = (
        "expired",
        "yes",
        "yes",
        0.90,
        2500,
        5.00,
        100000,
        100000,
        63250.0,
        0.99,
        0.90,
        "15:45:07",
        "KXBTC15M-26JUL291545-T63249.99",
        True,
        "BTC 3:45pm",
        "2026-07-29",
        400,
        0.99,
        "High Water Scalp",
        None,
    )
    captured = {}
    monkeypatch.setattr(trade_manager, "get_postgresql_connection", lambda: _expiry_conn(row))
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

    assert trade_manager.finalize_expired_trade_from_market_result(7) is True
    assert captured["sell_price"] == 1.0
    assert captured["pnl"] == round((1.0 - 0.90) * 2500 - 5.00, 6)
