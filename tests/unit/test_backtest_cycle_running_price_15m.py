"""Cumulative YES trade price / implied NO extrema for backtest rows (``*_price_*_15m`` columns)."""

from __future__ import annotations

from scripts.backtest.helpers.backtest_strike_span import (
    implied_no_envelope_from_unordered_yes_low_high,
    implied_no_price_min_max_from_yes_price_bar,
)
from scripts.backtest.helpers.kalshi_candles_1m import _cycle_running_price_15m_db_tuple


def test_implied_no_price_matches_envelope_helper() -> None:
    n_lo, n_hi = implied_no_price_min_max_from_yes_price_bar(0.04, 0.69)
    assert round(n_lo, 6) == 0.31
    assert round(n_hi, 6) == 0.96
    a, b = implied_no_envelope_from_unordered_yes_low_high(0.69, 0.04)
    assert round(a, 6) == round(n_lo, 6)
    assert round(b, 6) == round(n_hi, 6)


def test_cycle_tuple_range() -> None:
    t = _cycle_running_price_15m_db_tuple(0.04, 0.69, 0.31, 0.96)
    assert t[0] is not None and t[1] is not None
    assert round(float(t[4]), 6) == 0.65
    assert round(float(t[5]), 6) == 0.65
