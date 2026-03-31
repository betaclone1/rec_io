"""Unit tests for strike_table_generator YES/NO ask extrema (full contract window)."""

from backend.strike_table_generator import (
    final_quarter_ask_tracking_fields,
    merge_ask_extrema,
    parse_ask_dollars_float,
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
