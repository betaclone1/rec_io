"""Unit tests for strike_table_generator YES/NO ask extrema (full contract window)."""

from datetime import datetime
from zoneinfo import ZoneInfo

from backend.strike_table_generator import (
    final_quarter_ask_tracking_fields,
    merge_ask_extrema,
    parse_ask_dollars_float,
    resolve_carry_forward_ttc_15m,
    should_delay_hourly_first_quarter_tracking,
    should_reset_hourly_quarter_tracking,
)


def test_parse_ask_dollars_float():
    assert parse_ask_dollars_float("0.0520") == 0.052
    assert parse_ask_dollars_float("  0.75 ") == 0.75
    assert parse_ask_dollars_float("") is None
    assert parse_ask_dollars_float(None) is None


def test_merge_ask_extrema():
    assert merge_ask_extrema(None, None, 0.1) == (0.1, 0.1)
    assert merge_ask_extrema(0.1, 0.3, 0.05) == (0.05, 0.3)
    assert merge_ask_extrema(0.1, 0.3, 0.5) == (0.1, 0.5)
    assert merge_ask_extrema(0.1, 0.3, None) == (0.1, 0.3)


def test_hourly_tracks_full_window_not_gated_by_ttc():
    """Hourly min/max/range match 15m: accumulate whenever asks are present (no final-quarter-only gate)."""
    y_lo, y_hi, n_lo, n_hi, y_r, n_r = final_quarter_ask_tracking_fields(
        event_ticker="E",
        ticker="M",
        yes_ask_dollars="0.5",
        no_ask_dollars="0.5",
        prev=None,
    )
    assert y_lo == y_hi == 0.5
    assert n_lo == n_hi == 0.5
    assert y_r == n_r == 0.0


def test_carries_and_ranges():
    prev = ("E", "M", 0.05, 0.10, 0.40, 0.45)
    y_lo, y_hi, n_lo, n_hi, y_r, n_r = final_quarter_ask_tracking_fields(
        event_ticker="E",
        ticker="M",
        yes_ask_dollars="0.75",
        no_ask_dollars="0.44",
        prev=prev,
    )
    assert y_lo == 0.05
    assert y_hi == 0.75
    assert n_lo == 0.40
    assert n_hi == 0.45
    assert abs(y_r - 0.70) < 1e-9
    assert abs(n_r - 0.05) < 1e-9


def test_full_window_single_snapshot():
    y_lo, y_hi, _, _, y_r, _ = final_quarter_ask_tracking_fields(
        event_ticker="E",
        ticker="M",
        yes_ask_dollars="0.2",
        no_ask_dollars="0.8",
        prev=None,
    )
    assert y_lo == y_hi == 0.2
    assert y_r == 0.0


def test_contract_roll_resets():
    prev = ("OLD", "M", 0.01, 0.99, 0.1, 0.2)
    y_lo, y_hi, _, _, _, _ = final_quarter_ask_tracking_fields(
        event_ticker="NEW",
        ticker="M",
        yes_ask_dollars="0.5",
        no_ask_dollars="0.5",
        prev=prev,
    )
    assert y_lo == y_hi == 0.5


def test_hourly_quarter_tracking_reset_on_ttc_jump():
    # Within same 15m quarter, ttc_15m counts down and should not reset.
    assert should_reset_hourly_quarter_tracking(810, 804) is False
    # New quarter boundary causes ttc_15m jump back up near 900; this must reset.
    assert should_reset_hourly_quarter_tracking(2, 899) is True


def test_resolve_carry_forward_ttc_15m_hourly_ignores_contract_ttc():
    """Hourly meta ``ttc`` is contract countdown; quarter reset needs ``ttc_15m`` only."""
    assert (
        resolve_carry_forward_ttc_15m(
            row={},
            meta={"ttc": 2400, "ttc_15m": None},
            market="hourly",
        )
        is None
    )
    assert (
        resolve_carry_forward_ttc_15m(
            row={},
            meta={"ttc": 2400, "ttc_15m": 812},
            market="hourly",
        )
        == 812
    )
    assert (
        resolve_carry_forward_ttc_15m(
            row={"ttc_15m": 805},
            meta={"ttc": 2400},
            market="hourly",
        )
        == 805
    )


def test_resolve_carry_forward_ttc_15m_15m_legacy_meta_ttc():
    """Legacy 15m ladders stored boundary seconds in meta ``ttc`` only."""
    assert (
        resolve_carry_forward_ttc_15m(
            row={},
            meta={"ttc": 600},
            market="15m",
        )
        == 600
    )


def test_delay_hourly_first_quarter_tracking_only_first_15s_after_hour():
    est = ZoneInfo("America/New_York")
    assert should_delay_hourly_first_quarter_tracking(datetime(2026, 5, 8, 12, 0, 0, tzinfo=est)) is True
    assert should_delay_hourly_first_quarter_tracking(datetime(2026, 5, 8, 12, 0, 14, tzinfo=est)) is True
    assert should_delay_hourly_first_quarter_tracking(datetime(2026, 5, 8, 12, 0, 15, tzinfo=est)) is False
    assert should_delay_hourly_first_quarter_tracking(datetime(2026, 5, 8, 12, 15, 5, tzinfo=est)) is False
