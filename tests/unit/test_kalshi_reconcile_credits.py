"""Unit tests for Kalshi reconcile credit split into journal lines."""

from __future__ import annotations

import pytest

from backend.bookkeeper.kalshi_reconcile_credits import build_kalshi_reconcile_je_lines


def _line_map(lines: list[dict]) -> dict[tuple[str, str], float]:
    return {(L["posting_type"], L["label"]): L["amount"] for L in lines}


def test_gain_splits_interest_and_incentives_from_trading_income() -> None:
    # QB $100 below Kalshi → gap -100; $10 interest + $5 incentives → trading credit $85
    lines = build_kalshi_reconcile_je_lines(
        gap=-100.0,
        interest_dollars=10.0,
        incentive_dollars=5.0,
        kalshi_account_id="1",
        trading_income_account_id="2",
        interest_income_account_id="3",
        incentives_income_account_id="4",
    )
    m = _line_map(lines)
    assert m[("Debit", "Kalshi Trading Account")] == 100.0
    assert m[("Credit", "Interest Income")] == 10.0
    assert m[("Credit", "Kalshi Incentives Income")] == 5.0
    assert m[("Credit", "Trading Income")] == 85.0
    assert len(lines) == 4


def test_gain_without_credits_is_two_line() -> None:
    lines = build_kalshi_reconcile_je_lines(
        gap=-42.5,
        interest_dollars=0.0,
        incentive_dollars=0.0,
        kalshi_account_id="1",
        trading_income_account_id="2",
    )
    m = _line_map(lines)
    assert m[("Debit", "Kalshi Trading Account")] == 42.5
    assert m[("Credit", "Trading Income")] == 42.5
    assert len(lines) == 2


def test_loss_with_credits_increases_trading_debit() -> None:
    # QB $100 above Kalshi + $10 interest + $5 incentives → debit trading $115
    lines = build_kalshi_reconcile_je_lines(
        gap=100.0,
        interest_dollars=10.0,
        incentive_dollars=5.0,
        kalshi_account_id="1",
        trading_income_account_id="2",
        interest_income_account_id="3",
        incentives_income_account_id="4",
    )
    m = _line_map(lines)
    assert m[("Credit", "Kalshi Trading Account")] == 100.0
    assert m[("Credit", "Interest Income")] == 10.0
    assert m[("Credit", "Kalshi Incentives Income")] == 5.0
    assert m[("Debit", "Trading Income")] == 115.0


def test_interest_only_matches_gap() -> None:
    lines = build_kalshi_reconcile_je_lines(
        gap=-10.18,
        interest_dollars=10.18,
        incentive_dollars=0.0,
        kalshi_account_id="1",
        trading_income_account_id="2",
        interest_income_account_id="3",
    )
    m = _line_map(lines)
    assert m[("Debit", "Kalshi Trading Account")] == 10.18
    assert m[("Credit", "Interest Income")] == 10.18
    assert "Trading Income" not in {L["label"] for L in lines}


def test_zero_gap_with_credits_reclassifies_from_trading() -> None:
    lines = build_kalshi_reconcile_je_lines(
        gap=0.0,
        interest_dollars=10.0,
        incentive_dollars=5.0,
        kalshi_account_id="1",
        trading_income_account_id="2",
        interest_income_account_id="3",
        incentives_income_account_id="4",
    )
    m = _line_map(lines)
    assert m[("Debit", "Trading Income")] == 15.0
    assert m[("Credit", "Interest Income")] == 10.0
    assert m[("Credit", "Kalshi Incentives Income")] == 5.0


def test_interest_requires_account_id() -> None:
    with pytest.raises(ValueError, match="interest_income_account_id"):
        build_kalshi_reconcile_je_lines(
            gap=-10.0,
            interest_dollars=10.0,
            incentive_dollars=0.0,
            kalshi_account_id="1",
            trading_income_account_id="2",
            interest_income_account_id=None,
        )
