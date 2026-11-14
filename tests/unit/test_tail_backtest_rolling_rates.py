"""Unit tests for trading-day rolling LT/UT rate helpers."""

from __future__ import annotations

from datetime import date

import backend.core.tail_backtest_rolling_rates as rr


def test_crypto_trading_day_every_calendar_day():
    sat = date(2026, 11, 7)
    assert rr.is_trading_day("KXBTC15M", sat)


def test_commodity_saturday_energy_still_has_one_slot():
    sat = date(2026, 11, 7)
    assert rr.is_trading_day("KXWTI15M", sat)
    # Metals fully dark Saturday
    assert not rr.is_trading_day("KXGOLD15M", sat)


def test_trading_days_ending_counts_trading_not_calendar():
    # From Monday 2026-11-09 back 7 trading days for WTI (skip full dark Saturday
    # except Sat 00:00 counts as trading day under session gate).
    mon = date(2026, 11, 9)
    days = rr.trading_days_ending("KXWTI15M", mon, 7)
    assert len(days) == 7
    assert days[-1] == mon


def test_aggregate_side_null_win_loss_excluded_from_rate():
    rows = [
        ("yes", True),
        ("no", False),
        (None, None),  # no fill
        ("yes", None),  # unsettled
    ]
    stats = rr._aggregate_side(rows)
    assert stats.cycles == 4
    assert stats.filled == 3
    assert stats.scored == 2
    assert stats.wins == 1
    assert stats.win_rate == 0.5
    assert stats.participation == 0.75


def test_windows_constant():
    assert rr.ROLLING_WINDOWS == (7, 30, 90)


def test_tail_score_from_win_rate_matches_ui_formula():
    # UI: (wr_pct - baseline) * 100, then Math.round
    # 1.6103% LT → (1.6103 - 1) * 100 = 61.03 → 61
    assert rr.tail_score_from_win_rate(0.016103, side="lt") == 61
    # 98.3897% UT → (98.3897 - 99) * 100 = -61.03 → -61
    assert rr.tail_score_from_win_rate(0.983897, side="ut") == -61
    assert rr.tail_score_from_win_rate(None, side="lt") is None
